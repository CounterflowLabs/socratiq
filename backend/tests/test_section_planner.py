"""Unit tests for SectionPlanner — Layer 1 + Layer 3 (Phase 1 scope)."""

import json
from unittest.mock import AsyncMock

import pytest

from app.services.content_analyzer import AnalyzedChunk
from app.services.llm.base import ContentBlock, LLMError, LLMResponse, TokenUsage
from app.services.section_planner import (
    PLANNER_VERSION,
    SECTION_BUCKET_KEY,
    SECTION_BUCKET_TOPIC_KEY,
    SectionPlanner,
    _build_chunk_inputs,
    _cosine_distance,
    _compute_boundary_hints,
    _detect_size_unit,
    _fallback_assignments,
    _should_short_circuit,
    _validate_and_normalize,
    has_section_buckets,
)
from app.tools.extractors.base import RawContentChunk


# --- helpers --------------------------------------------------------------


def _video_chunk(text: str, start: float, end: float) -> RawContentChunk:
    return RawContentChunk(
        source_type="bilibili",
        raw_text=text,
        metadata={"start_time": start, "end_time": end},
    )


def _text_chunk(text: str) -> RawContentChunk:
    return RawContentChunk(source_type="markdown", raw_text=text, metadata={})


def _analyzed(topic: str, summary: str, text: str = "") -> AnalyzedChunk:
    return AnalyzedChunk(topic=topic, summary=summary, raw_text=text or summary)


def _mock_llm_response(payload: dict, *, input_tokens: int = 100, output_tokens: int = 50) -> LLMResponse:
    return LLMResponse(
        content=[ContentBlock(type="text", text=json.dumps(payload))],
        model="mock",
        usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _planner_with_provider(provider) -> SectionPlanner:
    router = AsyncMock()
    router.get_provider = AsyncMock(return_value=provider)
    return SectionPlanner(router)


# --- size detection -------------------------------------------------------


class TestDetectSizeUnit:
    def test_all_video_chunks_pick_duration_sec(self):
        chunks = [_video_chunk("hi", 0, 60), _video_chunk("there", 60, 120)]
        analyses = [_analyzed("a", "first"), _analyzed("b", "second")]
        unit, sizes = _detect_size_unit(chunks, analyses)
        assert unit == "duration_sec"
        assert sizes == [60.0, 60.0]

    def test_mixed_metadata_falls_back_to_word_count(self):
        chunks = [_video_chunk("alpha beta gamma", 0, 60), _text_chunk("one two three four")]
        analyses = [_analyzed("a", "x"), _analyzed("b", "y")]
        unit, sizes = _detect_size_unit(chunks, analyses)
        assert unit == "word_count"
        assert sizes == [3.0, 4.0]

    def test_pure_text_uses_word_count(self):
        chunks = [_text_chunk("alpha beta"), _text_chunk("one")]
        analyses = [_analyzed("a", "x"), _analyzed("b", "y")]
        unit, sizes = _detect_size_unit(chunks, analyses)
        assert unit == "word_count"
        assert sizes == [2.0, 1.0]

    def test_cjk_text_word_count_uses_character_fallback(self):
        # Whitespace tokenization undercounts pure CJK runs — heuristic
        # picks the CJK character count when it's larger.
        chunks = [_text_chunk("中文测试一二三四五"), _text_chunk("一二")]
        analyses = [_analyzed("a", "x"), _analyzed("b", "y")]
        unit, sizes = _detect_size_unit(chunks, analyses)
        assert unit == "word_count"
        assert sizes == [9.0, 2.0]


# --- short circuit --------------------------------------------------------


class TestShortCircuit:
    def test_short_video_triggers(self):
        # Total = 7 minutes = 420s < 480s threshold
        assert _should_short_circuit("duration_sec", [120.0, 120.0, 180.0]) is True

    def test_long_video_does_not_trigger(self):
        # 12 minutes total
        assert _should_short_circuit("duration_sec", [240.0, 240.0, 240.0]) is False

    def test_threshold_boundary_at_8_minutes(self):
        # Exactly 480s — design says "< 480 sec" → 480 itself does NOT short circuit
        assert _should_short_circuit("duration_sec", [480.0]) is False

    def test_short_text_triggers(self):
        assert _should_short_circuit("word_count", [500.0, 800.0]) is True

    def test_long_text_does_not_trigger(self):
        assert _should_short_circuit("word_count", [1500.0, 1500.0]) is False

    def test_empty_sizes_triggers(self):
        assert _should_short_circuit("duration_sec", []) is True


# --- boundary hints -------------------------------------------------------


class TestBoundaryHints:
    def test_empty_returns_empty(self):
        assert _compute_boundary_hints([]) == []

    def test_single_chunk_returns_single_zero(self):
        assert _compute_boundary_hints([[1.0, 0.0]]) == [0.0]

    def test_identical_vectors_yield_zero_hint(self):
        v = [1.0, 0.0, 0.0]
        hints = _compute_boundary_hints([v, v, v])
        assert all(abs(h - 0.0) < 1e-9 for h in hints)

    def test_zero_vector_safely_returns_zero_distance(self):
        # Zero-vector embeddings (fallback when no embed provider) must not
        # blow up with NaN — they collapse to 0.0 cosine distance.
        v = [0.0, 0.0, 0.0]
        hints = _compute_boundary_hints([v, v])
        assert hints == [0.0, 0.0]

    def test_orthogonal_step_produces_max_hint(self):
        # Two clusters: A, A, B, B. The boundary signal should be largest
        # at or adjacent to index 2 (the transition). Window-3 smoothing
        # spreads the signal across i=2 and i=3, so we accept either.
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        hints = _compute_boundary_hints([a, a, b, b])
        # Index 0 should be the floor (no prior chunk)
        assert hints[0] == min(hints)
        # Boundary region (indices 2-3) carries the max signal
        boundary_max = max(hints[2], hints[3])
        assert boundary_max == max(hints)
        # Non-boundary indices stay strictly below boundary indices
        assert hints[0] < boundary_max
        assert hints[1] < boundary_max  # ← smoothing leaks slightly here but
                                          # the boundary still dominates

    def test_cosine_distance_clamps_extremes(self):
        # Numerical safety: nearly-identical vectors don't return negative
        assert _cosine_distance([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0, abs=1e-9)
        assert _cosine_distance([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(2.0, abs=1e-9)


# --- input shaping --------------------------------------------------------


class TestBuildChunkInputs:
    def test_duration_unit_emits_float_duration_sec(self):
        analyses = [_analyzed("Intro", "A summary."), _analyzed("Body", "Second part.")]
        inputs = _build_chunk_inputs(analyses, [0.0, 0.7], "duration_sec", [60.0, 75.5])
        assert inputs[0] == {
            "idx": 0,
            "summary": "A summary.",
            "boundary_hint": 0.0,
            "duration_sec": 60.0,
        }
        assert inputs[1]["duration_sec"] == 75.5
        assert inputs[1]["boundary_hint"] == 0.7

    def test_word_count_unit_emits_int_word_count(self):
        analyses = [_analyzed("a", "s")]
        inputs = _build_chunk_inputs(analyses, [0.3], "word_count", [120.7])
        assert inputs[0]["word_count"] == 120  # int truncation
        assert "duration_sec" not in inputs[0]

    def test_empty_summary_falls_back_to_topic(self):
        analyses = [AnalyzedChunk(topic="Intro", summary="", raw_text="")]
        inputs = _build_chunk_inputs(analyses, [0.0], "word_count", [100])
        assert inputs[0]["summary"] == "Intro"


# --- validator ------------------------------------------------------------


class TestValidator:
    def test_happy_path(self):
        payload = {
            "buckets": [
                {"id": 0, "topic": "intro"},
                {"id": 1, "topic": "core"},
            ],
            "assignments": [
                {"chunk_index": 0, "bucket_id": 0},
                {"chunk_index": 1, "bucket_id": 0},
                {"chunk_index": 2, "bucket_id": 1},
            ],
        }
        result = _validate_and_normalize(payload, expected_n=3)
        assert result is not None
        assert [a.bucket_id for a in result] == [0, 0, 1]
        assert [a.bucket_topic for a in result] == ["intro", "intro", "core"]

    def test_length_mismatch_rejected(self):
        payload = {
            "buckets": [{"id": 0, "topic": "x"}],
            "assignments": [{"chunk_index": 0, "bucket_id": 0}],
        }
        assert _validate_and_normalize(payload, expected_n=5) is None

    def test_non_monotonic_rejected(self):
        payload = {
            "buckets": [
                {"id": 0, "topic": "a"},
                {"id": 1, "topic": "b"},
            ],
            "assignments": [
                {"chunk_index": 0, "bucket_id": 0},
                {"chunk_index": 1, "bucket_id": 1},
                {"chunk_index": 2, "bucket_id": 0},  # regression — rejected
            ],
        }
        assert _validate_and_normalize(payload, expected_n=3) is None

    def test_undeclared_bucket_rejected(self):
        payload = {
            "buckets": [{"id": 0, "topic": "a"}],
            "assignments": [
                {"chunk_index": 0, "bucket_id": 0},
                {"chunk_index": 1, "bucket_id": 1},  # bucket 1 not declared
            ],
        }
        assert _validate_and_normalize(payload, expected_n=2) is None

    def test_bucket_count_over_12_clamped_not_rejected(self):
        # 15 distinct buckets — validator must clamp tail into bucket 11.
        buckets = [{"id": i, "topic": f"b{i}"} for i in range(15)]
        assignments = [
            {"chunk_index": i, "bucket_id": i} for i in range(15)
        ]
        result = _validate_and_normalize(
            {"buckets": buckets, "assignments": assignments}, expected_n=15
        )
        assert result is not None
        distinct = sorted({a.bucket_id for a in result})
        assert distinct == list(range(12))  # 0..11
        # The 4 overflow chunks land in bucket 11
        tail_count = sum(1 for a in result if a.bucket_id == 11)
        assert tail_count == 4

    def test_non_contiguous_ids_remapped_to_zero_based(self):
        # LLM emitted gaps in bucket ids (id=2, id=5, id=9) — validator
        # remaps to contiguous 0,1,2.
        payload = {
            "buckets": [
                {"id": 2, "topic": "alpha"},
                {"id": 5, "topic": "beta"},
                {"id": 9, "topic": "gamma"},
            ],
            "assignments": [
                {"chunk_index": 0, "bucket_id": 2},
                {"chunk_index": 1, "bucket_id": 5},
                {"chunk_index": 2, "bucket_id": 9},
            ],
        }
        result = _validate_and_normalize(payload, expected_n=3)
        assert [a.bucket_id for a in result] == [0, 1, 2]
        assert [a.bucket_topic for a in result] == ["alpha", "beta", "gamma"]

    def test_string_bucket_ids_tolerated(self):
        payload = {
            "buckets": [{"id": 0, "topic": "x"}],
            "assignments": [{"chunk_index": 0, "bucket_id": "0"}],
        }
        result = _validate_and_normalize(payload, expected_n=1)
        assert result is not None
        assert result[0].bucket_id == 0


# --- fallback helpers -----------------------------------------------------


class TestFallback:
    def test_fallback_assignments_are_per_chunk(self):
        result = _fallback_assignments(4)
        assert [a.bucket_id for a in result] == [0, 1, 2, 3]
        assert all(a.bucket_topic is None for a in result)

    def test_has_section_buckets_helper(self):
        assert has_section_buckets([None, {}, {"section_bucket": 1}]) is True
        assert has_section_buckets([{}, None, {"foo": 1}]) is False
        assert has_section_buckets([]) is False


# --- end-to-end plan() ----------------------------------------------------


class TestPlanEndToEnd:
    @pytest.mark.asyncio
    async def test_short_circuit_returns_single_bucket(self):
        chunks = [_video_chunk("hi", 0, 60), _video_chunk("bye", 60, 180)]
        analyses = [_analyzed("Intro", "Hello"), _analyzed("End", "Goodbye")]
        embeddings = [[1.0, 0.0], [1.0, 0.0]]
        planner = _planner_with_provider(provider=AsyncMock())

        result = await planner.plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=embeddings,
            title="3-minute video",
        )

        assert [a.bucket_id for a in result.assignments] == [0, 0]
        assert result.stats["tier_used"] == "skeleton"
        assert result.stats["short_circuit"] is True
        assert result.stats["planner_version"] == PLANNER_VERSION
        assert result.stats["bucket_count"] == 1

    @pytest.mark.asyncio
    async def test_layer1_skeleton_happy_path(self):
        # 12-minute video: 6 chunks × 120s = 720s total → above short-circuit
        chunks = [_video_chunk(f"part {i}", i * 120, (i + 1) * 120) for i in range(6)]
        analyses = [_analyzed(f"Topic {i}", f"Summary {i}") for i in range(6)]
        embeddings = [[1.0, 0.0]] * 6

        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=_mock_llm_response(
                {
                    "buckets": [
                        {"id": 0, "topic": "Beginning"},
                        {"id": 1, "topic": "Middle"},
                        {"id": 2, "topic": "End"},
                    ],
                    "assignments": [
                        {"chunk_index": 0, "bucket_id": 0},
                        {"chunk_index": 1, "bucket_id": 0},
                        {"chunk_index": 2, "bucket_id": 1},
                        {"chunk_index": 3, "bucket_id": 1},
                        {"chunk_index": 4, "bucket_id": 2},
                        {"chunk_index": 5, "bucket_id": 2},
                    ],
                },
                input_tokens=400,
                output_tokens=80,
            )
        )

        planner = _planner_with_provider(provider)
        result = await planner.plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=embeddings,
            title="long video",
        )

        assert [a.bucket_id for a in result.assignments] == [0, 0, 1, 1, 2, 2]
        assert [a.bucket_topic for a in result.assignments] == [
            "Beginning", "Beginning", "Middle", "Middle", "End", "End",
        ]
        assert result.stats["tier_used"] == "skeleton"
        assert result.stats["bucket_count"] == 3
        assert result.stats["llm_input_tokens"] == 400
        assert result.stats["llm_output_tokens"] == 80
        assert result.stats["short_circuit"] is False

    @pytest.mark.asyncio
    async def test_llm_error_falls_back_to_per_chunk(self):
        chunks = [_video_chunk(f"p{i}", i * 120, (i + 1) * 120) for i in range(5)]
        analyses = [_analyzed(f"T{i}", f"S{i}") for i in range(5)]
        embeddings = [[1.0, 0.0]] * 5

        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=LLMError("provider unavailable"))

        planner = _planner_with_provider(provider)
        result = await planner.plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=embeddings,
            title="vid",
        )

        assert [a.bucket_id for a in result.assignments] == [0, 1, 2, 3, 4]
        assert result.stats["tier_used"] == "fallback"
        assert result.stats["error"].startswith("llm_error:")

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back(self):
        chunks = [_video_chunk(f"p{i}", i * 120, (i + 1) * 120) for i in range(5)]
        analyses = [_analyzed(f"T{i}", f"S{i}") for i in range(5)]
        embeddings = [[1.0, 0.0]] * 5

        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=LLMResponse(
                content=[ContentBlock(type="text", text="not json at all")],
                model="mock",
                usage=TokenUsage(input_tokens=50, output_tokens=10),
            )
        )

        planner = _planner_with_provider(provider)
        result = await planner.plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=embeddings,
            title="vid",
        )

        assert result.stats["tier_used"] == "fallback"
        assert result.stats["error"] == "json_parse_failed"
        # Tokens from the failed call should still be reported
        assert result.stats["llm_input_tokens"] == 50

    @pytest.mark.asyncio
    async def test_length_mismatch_in_llm_response_falls_back(self):
        chunks = [_video_chunk(f"p{i}", i * 120, (i + 1) * 120) for i in range(5)]
        analyses = [_analyzed(f"T{i}", f"S{i}") for i in range(5)]
        embeddings = [[1.0, 0.0]] * 5

        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=_mock_llm_response(
                {
                    "buckets": [{"id": 0, "topic": "x"}],
                    "assignments": [
                        {"chunk_index": 0, "bucket_id": 0},
                        {"chunk_index": 1, "bucket_id": 0},
                    ],  # only 2 — chunks has 5
                }
            )
        )

        planner = _planner_with_provider(provider)
        result = await planner.plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=embeddings,
            title="vid",
        )
        assert result.stats["tier_used"] == "fallback"
        assert result.stats["error"] == "validation_failed"

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        planner = _planner_with_provider(AsyncMock())
        result = await planner.plan(
            chunks=[], analyses=[], embeddings=[], title="x"
        )
        assert result.assignments == []
        assert result.stats["error"] == "empty_input"

    @pytest.mark.asyncio
    async def test_route_misconfigured_falls_back_to_evaluation(self):
        # First lookup (STRUCTURE_PLANNING) raises; second (EVALUATION) succeeds.
        fallback_provider = AsyncMock()
        fallback_provider.chat = AsyncMock(
            return_value=_mock_llm_response(
                {
                    "buckets": [{"id": 0, "topic": "single"}],
                    "assignments": [
                        {"chunk_index": i, "bucket_id": 0} for i in range(5)
                    ],
                }
            )
        )
        router = AsyncMock()
        call_count = {"n": 0}

        async def fake_get_provider(task_type):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise LLMError("no STRUCTURE_PLANNING route")
            return fallback_provider

        router.get_provider = fake_get_provider
        planner = SectionPlanner(router)

        chunks = [_video_chunk(f"p{i}", i * 120, (i + 1) * 120) for i in range(5)]
        analyses = [_analyzed(f"T{i}", f"S{i}") for i in range(5)]
        embeddings = [[1.0, 0.0]] * 5

        result = await planner.plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=embeddings,
            title="vid",
        )
        assert call_count["n"] == 2
        assert result.stats["tier_used"] == "skeleton"
        assert result.stats["bucket_count"] == 1

    @pytest.mark.asyncio
    async def test_no_provider_at_all_falls_back(self):
        router = AsyncMock()
        router.get_provider = AsyncMock(side_effect=LLMError("nothing configured"))
        planner = SectionPlanner(router)

        chunks = [_video_chunk(f"p{i}", i * 120, (i + 1) * 120) for i in range(5)]
        analyses = [_analyzed(f"T{i}", f"S{i}") for i in range(5)]
        embeddings = [[1.0, 0.0]] * 5

        result = await planner.plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=embeddings,
            title="vid",
        )
        assert result.stats["tier_used"] == "fallback"
        assert result.stats["error"].startswith("no_provider:")


# --- stats sanity ---------------------------------------------------------


class TestStats:
    @pytest.mark.asyncio
    async def test_stats_shape(self):
        chunks = [_video_chunk(f"p{i}", i * 120, (i + 1) * 120) for i in range(6)]
        analyses = [_analyzed(f"T{i}", f"S{i}") for i in range(6)]
        embeddings = [[1.0, 0.0]] * 6
        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=_mock_llm_response(
                {
                    "buckets": [
                        {"id": 0, "topic": "A"},
                        {"id": 1, "topic": "B"},
                    ],
                    "assignments": [
                        {"chunk_index": 0, "bucket_id": 0},
                        {"chunk_index": 1, "bucket_id": 0},
                        {"chunk_index": 2, "bucket_id": 0},
                        {"chunk_index": 3, "bucket_id": 1},
                        {"chunk_index": 4, "bucket_id": 1},
                        {"chunk_index": 5, "bucket_id": 1},
                    ],
                }
            )
        )

        planner = _planner_with_provider(provider)
        result = await planner.plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=embeddings,
            title="vid",
        )
        stats = result.stats
        # All required keys present (matches §6 monitoring schema)
        for key in (
            "tier_used",
            "planner_version",
            "bucket_count",
            "avg_chunks_per_bucket",
            "min_chunks_per_bucket",
            "max_chunks_per_bucket",
            "topic_uniqueness",
            "planning_duration_ms",
            "llm_input_tokens",
            "llm_output_tokens",
            "short_circuit",
            "error",
        ):
            assert key in stats, f"missing stat key: {key}"
        assert stats["bucket_count"] == 2
        assert stats["min_chunks_per_bucket"] == 3
        assert stats["max_chunks_per_bucket"] == 3
        assert stats["avg_chunks_per_bucket"] == 3.0
        assert stats["topic_uniqueness"] == 1.0
        assert stats["error"] is None


# --- ContentChunk metadata key constants ----------------------------------


def test_metadata_keys_are_stable():
    # Other layers (course_generator, frontend) rely on these strings.
    assert SECTION_BUCKET_KEY == "section_bucket"
    assert SECTION_BUCKET_TOPIC_KEY == "section_bucket_topic"
