"""Unit tests for SectionPlanner — the zero-LLM section floor.

v3 removed the LLM tiers (skeleton / windowed): the planner is now
short-circuit → Layer 3 (embedding peaks) → Layer 4 (size-greedy).
The LLM-grade outline lives in the agentic video→course topology.
"""

import pytest

from app.services.content_analyzer import AnalyzedChunk
from app.services.section_planner import (
    PLANNER_VERSION,
    SECTION_BUCKET_KEY,
    SECTION_BUCKET_TOPIC_KEY,
    BucketAssignment,
    SectionPlanner,
    _bucket_token_sizes,
    _cosine_distance,
    _compute_boundary_hints,
    _detect_size_unit,
    _fallback_assignments,
    _run_layer3_embedding_only,
    _should_short_circuit,
    _split_oversized_buckets,
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


def _timed_chunk(idx: int) -> RawContentChunk:
    """One-minute chunk at position ``idx`` — used for long-source tests."""
    return RawContentChunk(
        source_type="bilibili",
        raw_text="x",
        metadata={"start_time": idx * 60.0, "end_time": (idx + 1) * 60.0},
    )


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

        result = await SectionPlanner().plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=embeddings,
            title="3-minute video",
        )

        assert [a.bucket_id for a in result.assignments] == [0, 0]
        assert result.stats["tier_used"] == "short_circuit"
        assert result.stats["short_circuit"] is True
        assert result.stats["planner_version"] == PLANNER_VERSION
        assert result.stats["bucket_count"] == 1
        # Short-circuit bucket carries the first chunk's topic.
        assert result.assignments[0].bucket_topic == "Intro"

    @pytest.mark.asyncio
    async def test_long_source_with_signal_uses_embedding_tier(self):
        # 30-minute source with a clear topic shift at index 15 → Layer 3.
        n = 30
        chunks = [_timed_chunk(i) for i in range(n)]
        analyses = [_analyzed(f"T{i}", f"Summary {i}") for i in range(n)]
        embeddings = [[1.0, 0.0] if i < 15 else [0.0, 1.0] for i in range(n)]

        result = await SectionPlanner().plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=embeddings,
            title="vid",
        )
        assert result.stats["tier_used"] == "embedding_only"
        assert result.stats["error"] is None
        distinct = {a.bucket_id for a in result.assignments}
        assert 3 <= len(distinct) <= 12
        # No LLM means no topic names.
        assert all(a.bucket_topic is None for a in result.assignments)

    @pytest.mark.asyncio
    async def test_degenerate_signal_floors_to_size_greedy_not_per_chunk(self):
        # Identical embeddings → zero boundary signal → Layer 4 floor. The
        # floor must coarsen by size, NOT emit one-section-per-chunk — that
        # fragmentation was the original bug.
        n = 30
        chunks = [_timed_chunk(i) for i in range(n)]
        analyses = [_analyzed(f"T{i}", f"Summary {i}") for i in range(n)]
        embeddings = [[1.0, 0.0]] * n

        result = await SectionPlanner().plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=embeddings,
            title="vid",
        )
        assert result.stats["tier_used"] == "fallback"
        assert result.stats["error"] == "embedding_only_unavailable"
        bucket_ids = [a.bucket_id for a in result.assignments]
        assert len(bucket_ids) == n
        assert bucket_ids == sorted(bucket_ids)  # monotonic non-decreasing
        distinct = sorted(set(bucket_ids))
        assert distinct == list(range(len(distinct)))  # contiguous from 0
        assert 1 < len(distinct) < n  # coarsened, not per-chunk

    @pytest.mark.asyncio
    async def test_missing_embeddings_still_coarsens(self):
        # embeddings=None (ingestion ran without an embedding provider) —
        # boundary hints collapse to zero and the size-greedy floor takes over.
        n = 12
        chunks = [_timed_chunk(i) for i in range(n)]
        analyses = [_analyzed(f"T{i}", f"S{i}") for i in range(n)]

        result = await SectionPlanner().plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=None,
            title="vid",
        )
        assert result.stats["tier_used"] == "fallback"
        distinct = {a.bucket_id for a in result.assignments}
        assert 1 < len(distinct) < n

    @pytest.mark.asyncio
    async def test_length_mismatch_falls_back_per_chunk(self):
        chunks = [_timed_chunk(i) for i in range(3)]
        analyses = [_analyzed("a", "x")]  # wrong length on purpose

        result = await SectionPlanner().plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=None,
            title="vid",
        )
        assert result.stats["tier_used"] == "fallback"
        assert result.stats["error"] == "length_mismatch"
        assert [a.bucket_id for a in result.assignments] == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        result = await SectionPlanner().plan(
            chunks=[], analyses=[], embeddings=[], title="x"
        )
        assert result.assignments == []
        assert result.stats["error"] == "empty_input"

    @pytest.mark.asyncio
    async def test_duck_typed_metadata_analyses_accepted(self):
        # ensure_section_buckets reconstructs planner inputs from chunk
        # metadata as SimpleNamespace projections — plan() must accept them.
        from types import SimpleNamespace

        n = 4
        chunks = [
            SimpleNamespace(
                raw_text="word " * 50,
                metadata={"start_time": i * 60.0, "end_time": (i + 1) * 60.0},
            )
            for i in range(n)
        ]
        analyses = [
            SimpleNamespace(topic=f"T{i}", summary=f"S{i}") for i in range(n)
        ]
        result = await SectionPlanner().plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=[[1.0, 0.0]] * n,
            title="vid",
        )
        assert len(result.assignments) == n
        # 4 minutes total → short-circuit single bucket
        assert result.stats["tier_used"] == "short_circuit"

    def test_planner_no_longer_owns_llm_tiers(self):
        # Regression guard for the v3 slim-down: a second LLM planner next to
        # the agentic outline would re-introduce the dual-track structure.
        import app.services.section_planner as sp

        assert not hasattr(sp.SectionPlanner, "_run_layer1_skeleton")
        assert not hasattr(sp.SectionPlanner, "_run_layer2_windowed")
        assert not hasattr(sp, "_PROMPT")
        # Constructor takes no router — nothing to resolve.
        SectionPlanner()


# --- stats sanity ---------------------------------------------------------


class TestStats:
    @pytest.mark.asyncio
    async def test_stats_shape(self):
        n = 30
        chunks = [_timed_chunk(i) for i in range(n)]
        analyses = [_analyzed(f"T{i}", f"S{i}") for i in range(n)]
        embeddings = [[1.0, 0.0] if i < 15 else [0.0, 1.0] for i in range(n)]

        result = await SectionPlanner().plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=embeddings,
            title="vid",
        )
        stats = result.stats
        # All required keys present (matches §6 monitoring schema). The
        # llm_*_tokens keys stay for shape stability — always 0 since v3.
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
        assert stats["llm_input_tokens"] == 0
        assert stats["llm_output_tokens"] == 0
        assert stats["bucket_count"] >= 3
        assert stats["topic_uniqueness"] == 1.0
        assert stats["error"] is None


# --- ContentChunk metadata key constants ----------------------------------


def test_metadata_keys_are_stable():
    # Other layers (course_generator, frontend) rely on these strings.
    assert SECTION_BUCKET_KEY == "section_bucket"
    assert SECTION_BUCKET_TOPIC_KEY == "section_bucket_topic"


# --- Layer 3 embedding-only ------------------------------------------------


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
    async def test_no_signal_floors_to_size_greedy_not_per_chunk(self):
        # Zero-vector embeddings → Layer 4 floor. The floor must coarsen 30
        # chunks by size into a bounded number of buckets
        # (≤ _EMBEDDING_MAX_BUCKETS), NOT emit 30 one-chunk sections.
        from app.services.section_planner import _EMBEDDING_MAX_BUCKETS

        n = 30
        chunks = [_timed_chunk(i) for i in range(n)]
        analyses = [_analyzed(f"T{i}", f"Summary {i}") for i in range(n)]
        embeddings = [[0.0, 0.0] for _ in range(n)]  # zero vectors

        result = await SectionPlanner().plan(
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
        result = await SectionPlanner().plan(
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
        result = await SectionPlanner().plan(
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
        result = await SectionPlanner().plan(
            chunks=chunks,
            analyses=analyses,
            embeddings=[[1.0, 0.0]],
            title="t",
            # lesson_input_token_cap omitted on purpose
        )
        # Stats expose whatever cap was used; sanity-check it's a positive int.
        assert isinstance(result.stats["lesson_input_token_cap"], int)
        assert result.stats["lesson_input_token_cap"] > 0
