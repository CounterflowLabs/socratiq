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
    BucketAssignment,
    SectionPlanner,
    _bucket_token_sizes,
    _build_chunk_inputs,
    _build_window_spans,
    _clamp_bucket_count,
    _cosine_distance,
    _compute_boundary_hints,
    _detect_size_unit,
    _fallback_assignments,
    _merge_seam_buckets,
    _run_layer3_embedding_only,
    _should_short_circuit,
    _split_oversized_buckets,
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
    async def test_llm_error_falls_back_to_size_greedy(self):
        # 5 chunks × 120s = 600s. Degenerate embeddings (identical vectors →
        # zero boundary signal) skip Layer 3, so we hit the Layer 4 floor.
        # The floor must coarsen by size (≥_EMBEDDING_MIN_BUCKETS), NOT emit
        # one-section-per-chunk — that fragmentation was the bug.
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

        bucket_ids = [a.bucket_id for a in result.assignments]
        assert len(bucket_ids) == 5
        # Monotonic non-decreasing, contiguous from 0, and coarsened (< per-chunk).
        assert bucket_ids == sorted(bucket_ids)
        assert bucket_ids[0] == 0
        distinct = sorted(set(bucket_ids))
        assert distinct == list(range(len(distinct)))
        assert 1 < len(distinct) < 5  # neither one giant bucket nor per-chunk
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


# --- Phase 2: window splitting --------------------------------------------


class TestWindowSpans:
    def test_small_input_returns_single_window(self):
        assert _build_window_spans(0) == []
        assert _build_window_spans(5) == [(0, 5)]
        assert _build_window_spans(30) == [(0, 30)]

    def test_two_windows_with_overlap(self):
        # 50 chunks, window=30, overlap=3, step=27
        spans = _build_window_spans(50)
        assert spans[0] == (0, 30)
        # second window starts at 30 - 3 = 27, runs to 50
        assert spans[-1][1] == 50
        assert spans[1] == (27, 50)

    def test_three_windows_long_input(self):
        # 80 chunks: [0,30) [27,57) [54,80)
        spans = _build_window_spans(80)
        assert len(spans) == 3
        assert spans[0] == (0, 30)
        assert spans[1] == (27, 57)
        assert spans[2] == (54, 80)
        # Adjacent windows overlap by exactly 3
        for a, b in zip(spans, spans[1:]):
            assert a[1] - b[0] == 3

    def test_terminal_window_smaller_than_full(self):
        # 100 chunks: [0,30) [27,57) [54,84) [81,100)
        spans = _build_window_spans(100)
        assert spans[-1] == (81, 100)
        assert spans[-1][1] - spans[-1][0] == 19  # stub end window

    def test_every_chunk_covered_by_exactly_one_window_after_truncation(self):
        # Each non-final window contributes [start, end - overlap);
        # final window contributes [start, end). Sum must equal n.
        for n in [31, 60, 90, 120, 199]:
            spans = _build_window_spans(n)
            covered = 0
            for i, (start, end) in enumerate(spans):
                if i + 1 < len(spans):
                    covered += (end - 3) - start  # overlap=3
                else:
                    covered += end - start
            assert covered == n, f"coverage mismatch for n={n}"


# --- Phase 2: seam merge logic --------------------------------------------


class TestMergeSeamBuckets:
    def test_merges_and_shifts_higher_ids(self):
        # Combined assignment after concat: 4 buckets, IDs 0..3
        original = [
            BucketAssignment(0, "intro"),
            BucketAssignment(0, "intro"),
            BucketAssignment(1, "core"),
            BucketAssignment(2, "more core"),
            BucketAssignment(3, "wrap up"),
        ]
        # Merge bucket 2 into bucket 1 (same theme across window seam)
        result = _merge_seam_buckets(original, seam_bid=2, target_bid=1)
        ids = [a.bucket_id for a in result]
        topics = [a.bucket_topic for a in result]
        assert ids == [0, 0, 1, 1, 2]
        # Both chunks now in bucket 1 carry bucket 1's topic ("core")
        assert topics[2] == "core"
        assert topics[3] == "core"
        # The previously bucket-3 chunk inherits id 2 with its OWN topic
        assert topics[4] == "wrap up"

    def test_no_higher_ids_no_shift(self):
        original = [BucketAssignment(0, "a"), BucketAssignment(1, "b")]
        result = _merge_seam_buckets(original, seam_bid=1, target_bid=0)
        assert [a.bucket_id for a in result] == [0, 0]


# --- Phase 2: clamp ------------------------------------------------------


class TestClampBucketCount:
    def test_under_cap_is_noop(self):
        assignments = [BucketAssignment(i, f"b{i}") for i in range(5)]
        result = _clamp_bucket_count(assignments, cap=12)
        assert [a.bucket_id for a in result] == [0, 1, 2, 3, 4]

    def test_over_cap_collapses_tail(self):
        # 15 buckets, cap=12 → tail buckets (11..14) all merge into 11
        assignments = [BucketAssignment(i, f"b{i}") for i in range(15)]
        result = _clamp_bucket_count(assignments, cap=12)
        ids = [a.bucket_id for a in result]
        assert max(ids) == 11
        # Tail chunks share bucket 11
        tail_chunks = [a for a in result if a.bucket_id == 11]
        assert len(tail_chunks) == 4


# --- Phase 2: end-to-end windowed mode ------------------------------------


def _huge_chunk(idx: int) -> RawContentChunk:
    """A chunk whose serialized JSON is big enough to push past 64KB at
    ~50 chunks. Used to force the Layer 2 routing branch."""
    return RawContentChunk(
        source_type="bilibili",
        raw_text="x",
        metadata={"start_time": idx * 60.0, "end_time": (idx + 1) * 60.0},
    )


class TestPhase2Windowed:
    @pytest.mark.asyncio
    async def test_routes_to_windowed_when_over_budget(self, monkeypatch):
        # Force the budget check by lowering the budget temporarily — easier
        # than constructing a 64KB summary payload in the test.
        import app.services.section_planner as sp_mod

        monkeypatch.setattr(sp_mod, "_SKELETON_BUDGET_BYTES", 200)

        # 60 chunks → 2 windows of [0,30) [27,57) [54,60) but we need
        # _WINDOW_SIZE = 30. Use _WINDOW_SIZE if needed to confirm.
        n = 60
        chunks = [_huge_chunk(i) for i in range(n)]
        analyses = [_analyzed(f"T{i}", f"Summary number {i}") for i in range(n)]
        embeddings = [[1.0, 0.0]] * n

        # Build per-window LLM responses so each window gets a valid plan.
        # Each window has _WINDOW_SIZE chunks except possibly the last.
        window_responses: list[LLMResponse] = []
        # Plan per window: 2 buckets each
        spans = _build_window_spans(n)
        for span in spans:
            length = span[1] - span[0]
            mid = length // 2
            window_responses.append(_mock_llm_response({
                "buckets": [
                    {"id": 0, "topic": f"window-a-{span}"},
                    {"id": 1, "topic": f"window-b-{span}"},
                ],
                "assignments": [
                    {"chunk_index": i, "bucket_id": 0 if i < mid else 1}
                    for i in range(length)
                ],
            }))

        # Stitch responses: refuse to merge all seams (cleaner assertion).
        stitch_response = _mock_llm_response({"merge": False, "reason": "different"})

        provider = AsyncMock()
        # First N calls are window plans; subsequent calls are stitch
        provider.chat = AsyncMock(
            side_effect=[*window_responses] + [stitch_response] * 10
        )

        planner = _planner_with_provider(provider)
        result = await planner.plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=embeddings,
            title="big video",
        )

        assert result.stats["tier_used"] == "windowed"
        # Each window contributes its non-overlap chunks; total = n
        assert len(result.assignments) == n
        # No merge, so distinct buckets = sum of per-window buckets = 2 * len(spans)
        distinct = sorted({a.bucket_id for a in result.assignments})
        # but capped at _MAX_BUCKETS = 12
        assert len(distinct) <= 12

    @pytest.mark.asyncio
    async def test_stitch_merges_when_llm_says_yes(self, monkeypatch):
        import app.services.section_planner as sp_mod

        monkeypatch.setattr(sp_mod, "_SKELETON_BUDGET_BYTES", 200)

        n = 40
        chunks = [_huge_chunk(i) for i in range(n)]
        analyses = [_analyzed(f"T{i}", f"Summary {i}") for i in range(n)]
        embeddings = [[1.0, 0.0]] * n

        spans = _build_window_spans(n)
        assert len(spans) >= 2  # ensure stitch path exercised

        # Each window: single bucket
        window_responses = []
        for span in spans:
            length = span[1] - span[0]
            window_responses.append(_mock_llm_response({
                "buckets": [{"id": 0, "topic": "Same theme"}],
                "assignments": [
                    {"chunk_index": i, "bucket_id": 0} for i in range(length)
                ],
            }))

        # Stitch: always merge
        stitch_yes = _mock_llm_response({"merge": True, "reason": "continuation"})

        provider = AsyncMock()
        provider.chat = AsyncMock(
            side_effect=[*window_responses] + [stitch_yes] * 10
        )

        planner = _planner_with_provider(provider)
        result = await planner.plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=embeddings,
            title="single-theme video",
        )

        assert result.stats["tier_used"] == "windowed"
        # All chunks collapsed into one bucket
        assert {a.bucket_id for a in result.assignments} == {0}


# --- Phase 4: embedding-only Layer 3 fallback -----------------------------


class TestEmbeddingOnlyLayer:
    def test_zero_signal_returns_none(self):
        # All-zero boundary hints → no actionable signal → None
        result = _run_layer3_embedding_only(
            boundary_hints=[0.0] * 10,
            size_unit="duration_sec",
            sizes=[60.0] * 10,
            n=10,
        )
        assert result is None

    def test_peaks_produce_bucket_boundaries(self):
        # 10 chunks, strong peaks at indices 3 and 7; total 10 min → k≈1,
        # raised to floor _EMBEDDING_MIN_BUCKETS = 3 → expect 3 buckets.
        boundary_hints = [0.0, 0.1, 0.1, 0.9, 0.2, 0.1, 0.1, 0.95, 0.1, 0.1]
        result = _run_layer3_embedding_only(
            boundary_hints=boundary_hints,
            size_unit="duration_sec",
            sizes=[60.0] * 10,
            n=10,
        )
        assert result is not None
        distinct = sorted({a.bucket_id for a in result})
        assert distinct == [0, 1, 2]
        # Boundary at idx 3 → bucket flip; at idx 7 → another flip
        ids = [a.bucket_id for a in result]
        assert ids[2] == 0 and ids[3] == 1  # flip at 3
        assert ids[6] == 1 and ids[7] == 2  # flip at 7
        # No LLM means no topic names
        assert all(a.bucket_topic is None for a in result)

    def test_target_bucket_count_scales_with_total_size(self):
        # 60 min video, target≈540s per bucket → ~6.7 → 7 buckets.
        n = 60
        boundary_hints = [(i / n) for i in range(n)]  # monotonically rising
        result = _run_layer3_embedding_only(
            boundary_hints=boundary_hints,
            size_unit="duration_sec",
            sizes=[60.0] * n,
            n=n,
        )
        assert result is not None
        distinct = {a.bucket_id for a in result}
        # Should pick a count in [3, 12]; for 60 min target we expect ~7
        assert 3 <= len(distinct) <= 12

    @pytest.mark.asyncio
    async def test_llm_failure_routes_to_embedding_then_falls_through_to_per_chunk(self):
        # Provider always errors. Boundary signal is non-trivial so Layer 3
        # should succeed and tier_used == "embedding_only".
        n = 30
        chunks = [_huge_chunk(i) for i in range(n)]
        analyses = [_analyzed(f"T{i}", f"Summary {i}") for i in range(n)]
        # Synthesize embeddings with a clear topic-shift around index 15
        embeddings: list[list[float]] = []
        for i in range(n):
            if i < 15:
                embeddings.append([1.0, 0.0])
            else:
                embeddings.append([0.0, 1.0])

        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=Exception("LLM unreachable"))

        planner = _planner_with_provider(provider)
        result = await planner.plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=embeddings,
            title="vid",
        )
        assert result.stats["tier_used"] == "embedding_only"
        # Error preserved so operators can see WHY LLM was skipped
        assert result.stats["error"].startswith("llm_error:")
        # Distinct buckets in [3, 12]
        distinct = {a.bucket_id for a in result.assignments}
        assert 3 <= len(distinct) <= 12

    @pytest.mark.asyncio
    async def test_no_signal_floors_to_size_greedy_not_per_chunk(self):
        # Provider errors AND embeddings are zero vectors → Layer 4 floor.
        # The floor must coarsen 30 chunks by size into a bounded number of
        # buckets (≤ _EMBEDDING_MAX_BUCKETS), NOT emit 30 one-chunk sections.
        from app.services.section_planner import _EMBEDDING_MAX_BUCKETS

        n = 30
        chunks = [_huge_chunk(i) for i in range(n)]
        analyses = [_analyzed(f"T{i}", f"Summary {i}") for i in range(n)]
        embeddings = [[0.0, 0.0] for _ in range(n)]  # zero vectors

        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=Exception("LLM down"))

        planner = _planner_with_provider(provider)
        result = await planner.plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=embeddings,
            title="vid",
        )
        assert result.stats["tier_used"] == "fallback"
        bucket_ids = [a.bucket_id for a in result.assignments]
        assert len(bucket_ids) == n
        assert bucket_ids == sorted(bucket_ids)  # monotonic non-decreasing
        distinct = sorted(set(bucket_ids))
        assert distinct == list(range(len(distinct)))  # contiguous from 0
        assert 1 < len(distinct) <= _EMBEDDING_MAX_BUCKETS  # coarsened, bounded
        assert len(distinct) < n  # the whole point: not one-section-per-chunk


# --- token-budget split pass ----------------------------------------------


def _sized_chunk(approx_tokens: int) -> RawContentChunk:
    """Make a chunk whose raw_text roughly encodes to `approx_tokens` tokens.

    cl100k_base tokenizes ASCII words separated by spaces at ~1.3-1.5 chars
    per token; padding with repeated "word " gives a predictable size.
    """
    return RawContentChunk(
        source_type="markdown",
        raw_text=("word " * approx_tokens).strip(),
        metadata={},
    )


class TestSplitOversizedBuckets:
    def test_undersized_bucket_unchanged(self):
        chunks = [_sized_chunk(100), _sized_chunk(100)]
        assignments = [
            BucketAssignment(bucket_id=0, bucket_topic="A"),
            BucketAssignment(bucket_id=0, bucket_topic="A"),
        ]
        new, extra = _split_oversized_buckets(assignments, chunks, cap_tokens=1000)
        assert new == assignments
        assert extra == 0

    def test_oversized_single_bucket_splits_into_parts(self):
        # Build a bucket whose total clearly exceeds the cap (5 × 200 = 1000+).
        chunks = [_sized_chunk(200) for _ in range(5)]
        assignments = [
            BucketAssignment(bucket_id=0, bucket_topic="Big Topic")
            for _ in range(5)
        ]
        new, extra = _split_oversized_buckets(assignments, chunks, cap_tokens=400)
        assert extra >= 1
        # No sub-bucket may exceed the cap.
        sizes = _bucket_token_sizes(new, chunks)
        assert all(s <= 400 for s in sizes)
        # Topics carry "(Part i/N)" suffix for the multi-part bucket.
        topics = {a.bucket_topic for a in new}
        assert any("Part" in (t or "") and "Big Topic" in (t or "") for t in topics)

    def test_oversized_bucket_with_no_topic_keeps_none(self):
        chunks = [_sized_chunk(200) for _ in range(4)]
        assignments = [
            BucketAssignment(bucket_id=0, bucket_topic=None) for _ in range(4)
        ]
        new, extra = _split_oversized_buckets(assignments, chunks, cap_tokens=300)
        assert extra >= 1
        # All new buckets keep topic=None — no (Part i/N) inserted on bare topics.
        assert all(a.bucket_topic is None for a in new)

    def test_other_buckets_left_alone(self):
        # Bucket 0 oversize, bucket 1 small. Only 0 should split; 1 keeps its id.
        chunks = [
            _sized_chunk(300), _sized_chunk(300), _sized_chunk(300),  # bid=0
            _sized_chunk(50),                                          # bid=1
        ]
        assignments = [
            BucketAssignment(bucket_id=0, bucket_topic="Big"),
            BucketAssignment(bucket_id=0, bucket_topic="Big"),
            BucketAssignment(bucket_id=0, bucket_topic="Big"),
            BucketAssignment(bucket_id=1, bucket_topic="Small"),
        ]
        new, extra = _split_oversized_buckets(assignments, chunks, cap_tokens=400)
        assert extra >= 1
        # The small-bucket chunk keeps bucket_id=1 and its topic.
        assert new[-1].bucket_id == 1
        assert new[-1].bucket_topic == "Small"

    def test_chunk_boundaries_never_cross(self):
        # Each chunk stays in exactly one bucket — split never re-orders or
        # duplicates chunks.
        chunks = [_sized_chunk(150) for _ in range(6)]
        assignments = [
            BucketAssignment(bucket_id=0, bucket_topic="T") for _ in range(6)
        ]
        new, _ = _split_oversized_buckets(assignments, chunks, cap_tokens=200)
        # Same length, same order — assignments map 1:1 to original indices.
        assert len(new) == 6
        # First chunk's bucket id should remain 0 (part 1 preserves original id).
        assert new[0].bucket_id == 0

    def test_single_oversize_chunk_stays_its_own_bucket(self):
        # A chunk that's already bigger than the cap can't be split further;
        # it stays as a 1-chunk bucket and runtime LessonGenerator truncation
        # is the safety net.
        chunks = [_sized_chunk(1000)]  # >> cap
        assignments = [BucketAssignment(bucket_id=0, bucket_topic="huge")]
        new, extra = _split_oversized_buckets(assignments, chunks, cap_tokens=200)
        assert extra == 0  # nothing to split — only one chunk
        assert new[0].bucket_id == 0

    def test_empty_assignments_returns_empty(self):
        new, extra = _split_oversized_buckets([], [], cap_tokens=100)
        assert new == []
        assert extra == 0

    def test_zero_cap_is_noop(self):
        # cap_tokens<=0 disables the split (defensive — should never happen).
        chunks = [_sized_chunk(100) for _ in range(3)]
        assignments = [BucketAssignment(bucket_id=0, bucket_topic="x") for _ in range(3)]
        new, extra = _split_oversized_buckets(assignments, chunks, cap_tokens=0)
        assert new == assignments
        assert extra == 0


class TestBucketTokenSizes:
    def test_per_bucket_sum_with_join_overhead(self):
        chunks = [_sized_chunk(50), _sized_chunk(50), _sized_chunk(80)]
        assignments = [
            BucketAssignment(bucket_id=0, bucket_topic=None),
            BucketAssignment(bucket_id=0, bucket_topic=None),
            BucketAssignment(bucket_id=1, bucket_topic=None),
        ]
        sizes = _bucket_token_sizes(assignments, chunks)
        # Two buckets, in bucket-id order.
        assert len(sizes) == 2
        # Bucket 0 has 2 chunks + 1 joiner token (~1); bucket 1 has 1 chunk.
        assert sizes[0] > sizes[1]

    def test_mismatched_lengths_returns_empty(self):
        # Defensive — protects against caller bugs.
        chunks = [_sized_chunk(50)]
        assignments = [
            BucketAssignment(bucket_id=0, bucket_topic=None),
            BucketAssignment(bucket_id=1, bucket_topic=None),
        ]
        assert _bucket_token_sizes(assignments, chunks) == []


# --- plan() integration: stats fields + split pass through tiers ----------


class TestPlanFinalize:
    @pytest.mark.asyncio
    async def test_stats_include_token_budget_fields(self):
        # Tiny input → short-circuit tier; stats must still carry the new keys.
        chunks = [_text_chunk("alpha beta gamma")]
        analyses = [_analyzed("a", "x", text="alpha beta gamma")]
        planner = SectionPlanner(AsyncMock())
        result = await planner.plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=[[1.0, 0.0]],
            title="t",
            lesson_input_token_cap=500,
        )
        assert "bucket_size_tokens_p50" in result.stats
        assert "bucket_size_tokens_max" in result.stats
        assert "buckets_split_for_size" in result.stats
        assert result.stats["lesson_input_token_cap"] == 500

    @pytest.mark.asyncio
    async def test_oversized_short_circuit_bucket_gets_split(self):
        # Short input (total < 2000 words) but its single bucket exceeds the
        # cap — split pass runs even after short-circuit.
        chunks = [_sized_chunk(300) for _ in range(3)]  # total ~900 tokens
        analyses = [_analyzed(f"T{i}", f"s{i}", text=c.raw_text) for i, c in enumerate(chunks)]
        planner = SectionPlanner(AsyncMock())
        result = await planner.plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=[[1.0, 0.0]] * 3,
            title="t",
            lesson_input_token_cap=400,
        )
        # short_circuit tier still ran...
        assert result.stats["short_circuit"] is True
        # ...but the oversized single bucket was split.
        assert result.stats["buckets_split_for_size"] >= 1
        assert result.stats["bucket_size_tokens_max"] <= 400

    @pytest.mark.asyncio
    async def test_default_cap_used_when_caller_omits(self):
        chunks = [_text_chunk("alpha")]
        analyses = [_analyzed("a", "x", text="alpha")]
        planner = SectionPlanner(AsyncMock())
        result = await planner.plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=[[1.0, 0.0]],
            title="t",
            # lesson_input_token_cap omitted on purpose
        )
        # Stats expose whatever cap was used; sanity-check it's a positive int.
        assert isinstance(result.stats["lesson_input_token_cap"], int)
        assert result.stats["lesson_input_token_cap"] > 0
