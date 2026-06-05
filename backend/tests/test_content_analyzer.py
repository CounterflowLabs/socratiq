"""Unit tests for ``_build_analysis_from_text`` length-contract enforcement.

The analyzer prompt says the LLM's ``chunks`` array must match the input
length 1:1. When the LLM violates that (drops or adds entries), downstream
SectionPlanner short-circuits to Layer 4 per-chunk fallback because its
length check fails — turning a long video into one-section-per-chunk.
These tests pin the post-parse normalization that prevents that.
"""

import json

import pytest

from app.services.content_analyzer import _build_analysis_from_text
from app.tools.extractors.base import RawContentChunk


def _raw(text: str, **meta) -> RawContentChunk:
    return RawContentChunk(source_type="bilibili", raw_text=text, metadata=meta)


def _payload(chunk_count: int, *, concept_count: int = 0) -> str:
    return json.dumps(
        {
            "source_title": "Demo",
            "overall_summary": "",
            "overall_difficulty": 3,
            "concepts": [
                {"name": f"c{i}", "description": ""} for i in range(concept_count)
            ],
            "chunks": [
                {
                    "topic": f"LLM topic {i}",
                    "summary": f"LLM summary {i}",
                    "concepts": [],
                    "difficulty": 3,
                    "key_terms": [],
                    "has_code": False,
                    "has_formula": False,
                }
                for i in range(chunk_count)
            ],
            "estimated_study_minutes": 0,
        }
    )


def test_matching_length_passes_through_unchanged():
    chunks = [_raw("text-a", start_time=0), _raw("text-b", start_time=60)]
    result = _build_analysis_from_text(_payload(2), "title", chunks)

    assert len(result.chunks) == 2
    assert result.chunks[0].topic == "LLM topic 0"
    assert result.chunks[1].topic == "LLM topic 1"
    # Original extractor metadata must survive — section planner reads it.
    assert result.chunks[0].metadata == {"start_time": 0}
    assert result.chunks[1].metadata == {"start_time": 60}


def test_llm_under_returns_pads_to_input_length(caplog):
    chunks = [
        _raw("text-a", start_time=0),
        _raw("text-b", start_time=60),
        _raw("text-c", start_time=120),
    ]
    with caplog.at_level("WARNING", logger="app.services.content_analyzer"):
        result = _build_analysis_from_text(_payload(2), "title", chunks)

    assert len(result.chunks) == 3
    # First two come from the LLM payload.
    assert result.chunks[0].topic == "LLM topic 0"
    assert result.chunks[1].topic == "LLM topic 1"
    # Third is the padded degenerate — generic topic but real raw_text +
    # metadata preserved so embedding/section planning still see the chunk.
    assert result.chunks[2].topic == "Section 3"
    assert result.chunks[2].raw_text == "text-c"
    assert result.chunks[2].metadata == {"start_time": 120}
    # And we logged the contract violation so it's noticeable in prod.
    assert any(
        "returned 2 chunks for 3 input chunks" in rec.message for rec in caplog.records
    )


def test_llm_over_returns_truncates_to_input_length(caplog):
    chunks = [_raw("text-a", start_time=0)]
    with caplog.at_level("WARNING", logger="app.services.content_analyzer"):
        result = _build_analysis_from_text(_payload(3), "title", chunks)

    assert len(result.chunks) == 1
    assert result.chunks[0].topic == "LLM topic 0"
    # No phantom entries past the input length.
    assert all(c.raw_text != "" for c in result.chunks)


def test_llm_returns_zero_chunks_pads_all_input(caplog):
    chunks = [_raw("text-a"), _raw("text-b")]
    with caplog.at_level("WARNING", logger="app.services.content_analyzer"):
        result = _build_analysis_from_text(_payload(0), "title", chunks)

    assert len(result.chunks) == 2
    for i, c in enumerate(result.chunks):
        assert c.topic == f"Section {i + 1}"
        assert c.raw_text == chunks[i].raw_text


def test_invalid_json_raises_validation_failed():
    from app.services.llm.runtime import ValidationFailed

    with pytest.raises(ValidationFailed):
        _build_analysis_from_text("not json", "title", [_raw("x")])
