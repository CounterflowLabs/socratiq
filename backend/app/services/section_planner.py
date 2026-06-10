"""SectionPlanner — zero-LLM floor that groups consecutive chunks into sections.

Historically this module owned a four-tier cascade whose top tiers called an
LLM (skeleton / windowed-skeleton). Since the agentic video→course outline
(``services/orchestration/topologies/video_to_course.py``) became the default
section-structure authority at course-generation time, the LLM tiers were
removed: keeping a second LLM planner alongside the outline planner meant two
components owning the same decision. What remains is the deterministic floor:

  - Short-circuit                 — tiny sources collapse to a single bucket
  - Layer 3 ("embedding_only")    — TextTiling-style peak detection on the
                                    per-chunk ``boundary_hint`` signal
  - Layer 4 ("fallback")          — size-greedy packing (never per-chunk
                                    unless the input is degenerate)

It runs at course-generation time (see
``course_generator.ensure_section_buckets``) to guarantee assembly never sees
bucket-less chunks, and its output doubles as the agentic outline's warm
start and failure fallback. ``boundary_hint`` is the prior-vs-current cosine
distance of stored chunk embeddings, TextTiling-smoothed and [0,1]-normalized.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field

from app.services.llm.token_budget import count_tokens
from app.tools.extractors.base import RawContentChunk

logger = logging.getLogger(__name__)

# Stamp on every plan output. Bump when the bucketing algorithm or validator
# changes materially so historical sources can be diffed by planner generation.
# v3: LLM tiers (skeleton / windowed) removed — planner is a zero-LLM floor.
PLANNER_VERSION = "v3"

# Short-circuit thresholds — below these, a single bucket is the honest answer.
_SHORT_CIRCUIT_DURATION_SEC = 480.0   # 8 minutes
_SHORT_CIRCUIT_WORD_COUNT = 2000

# Embedding-only (Layer 3) and size-greedy (Layer 4) bucketing parameters.
_EMBEDDING_BUCKET_TARGET_SEC = 540.0   # ~9-minute buckets (midpoint of 5–15)
_EMBEDDING_BUCKET_TARGET_WORDS = 2750  # midpoint of 1500–4000
_EMBEDDING_MIN_BUCKETS = 3
_EMBEDDING_MAX_BUCKETS = 12

# Conservative cap when the caller doesn't supply a real budget. Keeps unit
# tests and ad-hoc scripts working without forcing every code path to wire a
# provider through. Production callers (course_generator) MUST pass the real
# budget computed from the LessonGenerator's provider.
_DEFAULT_BUCKET_TOKEN_CAP = 8_000

# tiktoken treats "\n\n" between joined chunks as ~1 token. Used when summing
# bucket sizes — keeps the predicate consistent with what LessonGenerator
# will actually feed into the model.
_JOIN_TOKEN_OVERHEAD = 1


@dataclass
class BucketAssignment:
    """Per-chunk bucket assignment in the order chunks were submitted."""

    bucket_id: int
    bucket_topic: str | None = None


@dataclass
class PlanResult:
    """Aggregated planner output: per-chunk assignments + run stats."""

    assignments: list[BucketAssignment]
    stats: dict = field(default_factory=dict)


class SectionPlanner:
    """Plans bucket assignments for a sequence of analyzed chunks (no LLM)."""

    async def plan(
        self,
        *,
        chunks: list[RawContentChunk],
        analyses: list,
        embeddings: list[list[float]] | None,
        title: str,
        lesson_input_token_cap: int | None = None,
    ) -> PlanResult:
        """Return one BucketAssignment per chunk, same order and length.

        Tier routing (degrades on failure):
          short-circuit → Layer 3 embedding-only → Layer 4 size-greedy

        ``analyses`` is duck-typed: each item needs ``topic`` and ``summary``
        attributes (``AnalyzedChunk`` or chunk-metadata projections both work).

        ``lesson_input_token_cap`` is the maximum tokens any single bucket's
        joined text may contain — buckets above this are split along chunk
        boundaries before being returned. When ``None`` we fall back to a
        conservative default (``_DEFAULT_BUCKET_TOKEN_CAP``); production
        callers should pass the real budget computed via
        :func:`lesson_input_token_budget` against the provider that
        :class:`LessonGenerator` will use.
        """
        started = time.perf_counter()
        cap_tokens = lesson_input_token_cap or _DEFAULT_BUCKET_TOKEN_CAP
        n = len(chunks)
        if n == 0:
            return PlanResult(
                assignments=[],
                stats=_build_stats(
                    tier="fallback",
                    assignments=[],
                    elapsed_ms=_elapsed_ms(started),
                    error="empty_input",
                    bucket_token_sizes=[],
                    buckets_split_for_size=0,
                    lesson_input_token_cap=cap_tokens,
                ),
            )

        # Length contract — analyses must line up with chunks. Embeddings
        # are optional (None means "no embeddings available, boundary_hint
        # collapses to zeros"); when present they must also line up.
        embeddings_safe: list[list[float]] = embeddings or [[] for _ in range(n)]
        if len(analyses) != n or len(embeddings_safe) != n:
            logger.warning(
                "SectionPlanner: length mismatch chunks=%d analyses=%d embeddings=%s",
                n,
                len(analyses),
                len(embeddings_safe) if embeddings is not None else "None",
            )
            return _finalize(
                raw_assignments=_fallback_assignments(n),
                chunks=chunks,
                cap_tokens=cap_tokens,
                tier="fallback",
                started=started,
                error="length_mismatch",
            )

        size_unit, sizes = _detect_size_unit(chunks, analyses)
        if _should_short_circuit(size_unit, sizes):
            topic = (analyses[0].topic or title or None) if analyses else None
            assignments = [BucketAssignment(bucket_id=0, bucket_topic=topic) for _ in range(n)]
            return _finalize(
                raw_assignments=assignments,
                chunks=chunks,
                cap_tokens=cap_tokens,
                tier="short_circuit",
                started=started,
                short_circuit=True,
            )

        # Boundary hints: prior-vs-current cosine distance, smoothed and
        # normalized. Failures collapse to zeros — Layer 4 still coarsens.
        try:
            boundary_hints = _compute_boundary_hints(embeddings_safe)
        except Exception as exc:  # noqa: BLE001
            logger.warning("SectionPlanner: boundary_hint computation failed: %s", exc)
            boundary_hints = [0.0] * n

        # --- Layer 3 embedding-only -----------------------------------------
        embedding_result = _run_layer3_embedding_only(
            boundary_hints=boundary_hints,
            size_unit=size_unit,
            sizes=sizes,
            n=n,
        )
        if embedding_result is not None:
            return _finalize(
                raw_assignments=embedding_result,
                chunks=chunks,
                cap_tokens=cap_tokens,
                tier="embedding_only",
                started=started,
            )

        # --- Layer 4 size-greedy floor -------------------------------------
        # The embedding signal was degenerate. Still coarsen by size rather
        # than emit one-section-per-chunk (the old per-chunk floor is what
        # produced 113-section courses).
        return _finalize(
            raw_assignments=_run_layer4_size_greedy(
                size_unit=size_unit, sizes=sizes, n=n
            ),
            chunks=chunks,
            cap_tokens=cap_tokens,
            tier="fallback",
            started=started,
            error="embedding_only_unavailable",
        )


# --- helpers ---------------------------------------------------------------


def _bucket_token_sizes(
    assignments: list[BucketAssignment],
    chunks: list[RawContentChunk],
) -> list[int]:
    """Per-bucket joined-text token counts, in bucket-id order.

    Mirrors what LessonGenerator will actually feed into the model:
    chunks belonging to the bucket joined with "\\n\\n" separators.
    Used both by the split predicate and by stats reporting.
    """
    if len(assignments) != len(chunks):
        return []
    by_bucket: dict[int, list[int]] = {}
    for idx, a in enumerate(assignments):
        by_bucket.setdefault(a.bucket_id, []).append(idx)
    sizes: list[int] = []
    for bid in sorted(by_bucket.keys()):
        chunk_indices = by_bucket[bid]
        chunk_tokens = [count_tokens(chunks[i].raw_text or "") for i in chunk_indices]
        joiners = _JOIN_TOKEN_OVERHEAD * max(0, len(chunk_tokens) - 1)
        sizes.append(sum(chunk_tokens) + joiners)
    return sizes


def _split_oversized_buckets(
    assignments: list[BucketAssignment],
    chunks: list[RawContentChunk],
    cap_tokens: int,
) -> tuple[list[BucketAssignment], int]:
    """Re-split any bucket whose joined text exceeds ``cap_tokens``.

    Splits along chunk boundaries (never inside a chunk). When a bucket
    is split into N parts, each part keeps the original topic with a
    ``(Part i/N)`` suffix so the UI can render them as a coherent
    sequence without UI changes.

    Returns ``(new_assignments, extra_buckets_created)``. The extra count
    is the number of buckets added beyond the input count and is reported
    via stats so operators can spot systemic oversizing.

    A single chunk that already exceeds ``cap_tokens`` becomes its own
    bucket — there's no chunk-internal splitting because chunks are the
    extractor's atomic unit. The downstream LessonGenerator will catch
    that case via its own runtime budget check.
    """
    if not assignments or cap_tokens <= 0 or len(assignments) != len(chunks):
        return assignments, 0

    by_bucket: dict[int, list[int]] = {}
    for idx, a in enumerate(assignments):
        by_bucket.setdefault(a.bucket_id, []).append(idx)

    # Token-count each chunk once; we may reference the same chunk's count
    # multiple times when computing running totals.
    chunk_tokens = [count_tokens(c.raw_text or "") for c in chunks]

    new_assignments = list(assignments)
    next_bid = max((a.bucket_id for a in assignments), default=-1) + 1
    extra = 0

    for bid in sorted(by_bucket.keys()):
        chunk_indices = by_bucket[bid]
        sizes = [chunk_tokens[i] for i in chunk_indices]
        joiners = _JOIN_TOKEN_OVERHEAD * max(0, len(sizes) - 1)
        total = sum(sizes) + joiners
        if total <= cap_tokens:
            continue

        # Greedy chunk-boundary packing — accumulate chunks into the
        # current sub-bucket until adding the next would overflow, then
        # start a fresh sub-bucket. Each sub-bucket carries at least one
        # chunk even if that chunk itself exceeds the cap.
        sub_buckets: list[list[int]] = [[]]
        running = 0
        for idx, sz in zip(chunk_indices, sizes):
            join_overhead = _JOIN_TOKEN_OVERHEAD if sub_buckets[-1] else 0
            if sub_buckets[-1] and running + join_overhead + sz > cap_tokens:
                sub_buckets.append([])
                running = 0
                join_overhead = 0
            sub_buckets[-1].append(idx)
            running += join_overhead + sz

        n_parts = len(sub_buckets)
        if n_parts <= 1:
            # Bucket overflowed but only one sub-bucket was produced —
            # happens when the bucket consists of a single oversize chunk.
            # Nothing to split. LessonGenerator's runtime check will trim.
            continue

        original_topic = next(
            (a.bucket_topic for a in assignments if a.bucket_id == bid),
            None,
        )
        for part_i, sub in enumerate(sub_buckets):
            new_bid = bid if part_i == 0 else next_bid
            if part_i > 0:
                next_bid += 1
                extra += 1
            new_topic = (
                f"{original_topic} (Part {part_i + 1}/{n_parts})"
                if original_topic
                else None
            )
            for idx in sub:
                new_assignments[idx] = BucketAssignment(
                    bucket_id=new_bid, bucket_topic=new_topic,
                )

    return new_assignments, extra


def _finalize(
    *,
    raw_assignments: list[BucketAssignment],
    chunks: list[RawContentChunk],
    cap_tokens: int,
    tier: str,
    started: float,
    error: str | None = None,
    short_circuit: bool = False,
) -> PlanResult:
    """Apply the size-cap split, compute stats, return the final PlanResult.

    Centralized so every tier exit path (short-circuit, Layer 3, Layer 4)
    goes through the same finalize step — no path can bypass the size-cap
    pass.
    """
    final, split_count = _split_oversized_buckets(raw_assignments, chunks, cap_tokens)
    bucket_sizes = _bucket_token_sizes(final, chunks)
    return PlanResult(
        assignments=final,
        stats=_build_stats(
            tier=tier,
            assignments=final,
            elapsed_ms=_elapsed_ms(started),
            error=error,
            short_circuit=short_circuit,
            bucket_token_sizes=bucket_sizes,
            buckets_split_for_size=split_count,
            lesson_input_token_cap=cap_tokens,
        ),
    )


def _run_layer3_embedding_only(
    *,
    boundary_hints: list[float],
    size_unit: str,
    sizes: list[float],
    n: int,
) -> list[BucketAssignment] | None:
    """TextTiling-style peak-detection bucketing without LLM.

    Computes a target bucket count from the resource's total size, picks the
    ``K-1`` strongest boundary peaks (avoiding consecutive picks), then walks
    the chunk sequence assigning a fresh bucket id at each chosen peak.
    Topic is ``None`` everywhere — no LLM means no human-readable names.

    Returns ``None`` when the boundary signal is degenerate (all zeros) so
    the caller can drop to the Layer 4 size-greedy floor instead of producing
    arbitrary equal-sized buckets.
    """
    if n <= 1:
        return None
    if not boundary_hints or all(h <= 1e-9 for h in boundary_hints):
        # Zero-vector embeddings or single-chunk source: no signal to act on.
        return None

    total_size = sum(sizes) if sizes else 0.0
    if size_unit == "duration_sec":
        target = total_size / _EMBEDDING_BUCKET_TARGET_SEC
    else:
        target = total_size / max(1.0, _EMBEDDING_BUCKET_TARGET_WORDS)
    k = int(round(target))
    k = max(_EMBEDDING_MIN_BUCKETS, min(_EMBEDDING_MAX_BUCKETS, k))
    # Need k-1 boundary picks across positions 1..n-1.
    k = min(k, n)
    if k <= 1:
        return None

    # Score candidate boundary positions (index 0 is excluded — boundary_hint
    # for the first chunk is the "no prior" floor). We pick top (k-1) peaks
    # by score, then de-duplicate adjacency to avoid clustering picks.
    scored = sorted(
        (
            (boundary_hints[i], i)
            for i in range(1, n)
            if boundary_hints[i] > 0.0
        ),
        reverse=True,
    )
    if not scored:
        return None

    picks: list[int] = []
    for _score, idx in scored:
        if any(abs(idx - p) < 2 for p in picks):
            continue
        picks.append(idx)
        if len(picks) >= k - 1:
            break
    picks.sort()

    if not picks:
        return None

    assignments: list[BucketAssignment] = []
    current_bucket = 0
    pick_set = set(picks)
    for i in range(n):
        if i in pick_set:
            current_bucket += 1
        assignments.append(
            BucketAssignment(bucket_id=current_bucket, bucket_topic=None)
        )
    return assignments


def _detect_size_unit(
    chunks: list[RawContentChunk],
    analyses: list,
) -> tuple[str, list[float]]:
    """Return ('duration_sec', durations) when every chunk has a time range,
    else ('word_count', counts). Mixed sources fall back to word_count.

    Accepts duck-typed objects so unit tests can pass lightweight stand-ins
    (SimpleNamespace etc.) without needing the full Pydantic models.
    """
    durations: list[float] = []
    all_have_time = True
    for c in chunks:
        meta = getattr(c, "metadata", None) or {}
        start = meta.get("start_time") if isinstance(meta, dict) else None
        end = meta.get("end_time") if isinstance(meta, dict) else None
        if start is None or end is None:
            all_have_time = False
            break
        try:
            durations.append(max(0.0, float(end) - float(start)))
        except (TypeError, ValueError):
            all_have_time = False
            break

    if all_have_time and durations:
        return "duration_sec", durations

    word_counts: list[float] = []
    for raw, analyzed in zip(chunks, analyses):
        text = (
            getattr(raw, "raw_text", "")
            or getattr(analyzed, "raw_text", "")
            or ""
        )
        word_counts.append(float(_word_count(text)))
    return "word_count", word_counts


def _word_count(text: str) -> int:
    """Whitespace word count with a CJK-character fallback.

    Pure CJK transcripts (e.g. Chinese subtitles) often render as one giant
    whitespace-free token; counting characters there is a better proxy for
    "content length" than counting tokens. We use the heuristic only when
    whitespace tokenization undercounts vs. the visible character budget.
    """
    if not text:
        return 0
    ws_count = len(text.split())
    cjk_chars = sum(
        1 for ch in text if "一" <= ch <= "鿿" or "぀" <= ch <= "ヿ"
    )
    return max(ws_count, cjk_chars)


def _should_short_circuit(size_unit: str, sizes: list[float]) -> bool:
    if not sizes:
        return True
    total = sum(sizes)
    if size_unit == "duration_sec":
        return total < _SHORT_CIRCUIT_DURATION_SEC
    return total < _SHORT_CIRCUIT_WORD_COUNT


def _compute_boundary_hints(embeddings: list[list[float]]) -> list[float]:
    """Per-chunk topic-shift signal in [0,1].

    Pipeline: prior-vs-current cosine distance → window-3 smoothing →
    min-max normalize. Index 0 is always 0.0 (no prior). Zero-vector
    embeddings (the fallback when no embedding provider is configured)
    return 0.0 for that pair instead of NaN.
    """
    n = len(embeddings)
    if n <= 1:
        return [0.0] * n

    raw_distances: list[float] = [0.0]
    for i in range(1, n):
        prev = embeddings[i - 1]
        curr = embeddings[i]
        raw_distances.append(_cosine_distance(prev, curr))

    smoothed: list[float] = []
    for i in range(n):
        lo = max(0, i - 1)
        hi = min(n, i + 2)
        window = raw_distances[lo:hi]
        smoothed.append(sum(window) / max(1, len(window)))

    lo_val = min(smoothed)
    hi_val = max(smoothed)
    span = hi_val - lo_val
    if span <= 1e-9:
        return [0.0] * n
    return [(v - lo_val) / span for v in smoothed]


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """1 - cosine_similarity, clamped to [0, 2]. Zero-norm vectors → 0.0."""
    if a is None or b is None or len(a) == 0 or len(b) == 0:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    sim = dot / (math.sqrt(na) * math.sqrt(nb))
    sim = max(-1.0, min(1.0, sim))
    return 1.0 - sim


def _run_layer4_size_greedy(
    *,
    size_unit: str,
    sizes: list[float],
    n: int,
) -> list[BucketAssignment]:
    """Layer 4 floor that still coarsens by size — never one-section-per-chunk.

    Reached only when the embedding signal was degenerate (Layer 3 returned
    ``None``). The old floor here was strict per-chunk bucketing, which
    silently turned a long source into N topicless sections (e.g. a
    113-chunk video → 113 sections). Instead we greedily pack consecutive
    chunks into buckets targeting the same ~9-minute / ~2750-word size as
    Layer 3, bounded by ``_EMBEDDING_MIN/MAX_BUCKETS``. Topic stays ``None``.

    Degenerates to per-chunk only when there is no usable size signal
    (missing/zero sizes) or ``n <= 1``.
    """
    if n <= 1 or not sizes or sum(sizes) <= 0 or len(sizes) != n:
        return _fallback_assignments(n)

    target = (
        _EMBEDDING_BUCKET_TARGET_SEC
        if size_unit == "duration_sec"
        else _EMBEDDING_BUCKET_TARGET_WORDS
    )
    total = sum(sizes)
    k = int(round(total / max(1.0, target)))
    k = max(_EMBEDDING_MIN_BUCKETS, min(_EMBEDDING_MAX_BUCKETS, k, n))
    if k <= 1:
        return [BucketAssignment(bucket_id=0, bucket_topic=None) for _ in range(n)]

    per_bucket = total / k
    assignments: list[BucketAssignment] = []
    bucket_id = 0
    running = 0.0
    for i in range(n):
        assignments.append(BucketAssignment(bucket_id=bucket_id, bucket_topic=None))
        running += sizes[i]
        # Advance to the next bucket once this one has reached its size share,
        # leaving at least one chunk for every remaining bucket.
        remaining_chunks = n - (i + 1)
        remaining_buckets = k - (bucket_id + 1)
        if (
            bucket_id < k - 1
            and remaining_chunks > 0
            and (running >= per_bucket or remaining_chunks <= remaining_buckets)
        ):
            bucket_id += 1
            running = 0.0
    return assignments


def _fallback_assignments(n: int) -> list[BucketAssignment]:
    """Strict per-chunk: bucket_id = chunk_index. Topic stays None — chunk's
    own ``topic`` from ContentAnalyzer is what course_generator uses as the
    section title in this mode (legacy behavior). Reserved for degenerate
    inputs (no size signal / length mismatch); the size-aware Layer 4 floor is
    :func:`_run_layer4_size_greedy`."""
    return [BucketAssignment(bucket_id=i, bucket_topic=None) for i in range(n)]


def _build_stats(
    *,
    tier: str,
    assignments: list[BucketAssignment],
    elapsed_ms: int,
    error: str | None = None,
    short_circuit: bool = False,
    bucket_token_sizes: list[int] | None = None,
    buckets_split_for_size: int = 0,
    lesson_input_token_cap: int = 0,
) -> dict:
    distinct = sorted({a.bucket_id for a in assignments})
    bucket_count = len(distinct)
    counts: dict[int, int] = {}
    for a in assignments:
        counts[a.bucket_id] = counts.get(a.bucket_id, 0) + 1
    chunk_counts = list(counts.values()) or [0]
    # topic_uniqueness counts distinct topics across BUCKETS (one per bucket),
    # not across chunks — repeating the same topic across chunks within one
    # bucket is correct behavior, only repeating across buckets is the signal
    # we want to catch (§6 of section-planning.md).
    topic_by_bucket: dict[int, str | None] = {}
    for a in assignments:
        if a.bucket_id not in topic_by_bucket and a.bucket_topic:
            topic_by_bucket[a.bucket_id] = a.bucket_topic
    bucket_topics = [t for t in topic_by_bucket.values() if t]
    topic_uniqueness = (
        len(set(bucket_topics)) / len(bucket_topics) if bucket_topics else 1.0
    )
    sizes = bucket_token_sizes or []
    sorted_sizes = sorted(sizes)
    p50 = sorted_sizes[len(sorted_sizes) // 2] if sorted_sizes else 0
    # llm_*_tokens stay in the payload (always 0 since v3) so the stats panel
    # and any recorded dashboards keep a stable shape across planner versions.
    return {
        "tier_used": tier,
        "planner_version": PLANNER_VERSION,
        "bucket_count": bucket_count,
        "avg_chunks_per_bucket": (
            round(sum(chunk_counts) / max(1, bucket_count), 3)
            if bucket_count else 0.0
        ),
        "min_chunks_per_bucket": min(chunk_counts) if assignments else 0,
        "max_chunks_per_bucket": max(chunk_counts) if assignments else 0,
        "topic_uniqueness": round(topic_uniqueness, 3),
        "planning_duration_ms": elapsed_ms,
        "llm_input_tokens": 0,
        "llm_output_tokens": 0,
        "short_circuit": short_circuit,
        "error": error,
        "bucket_size_tokens_p50": p50,
        "bucket_size_tokens_max": max(sizes) if sizes else 0,
        "buckets_split_for_size": buckets_split_for_size,
        "lesson_input_token_cap": lesson_input_token_cap,
    }


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


# Exported for downstream code that wants to check whether a chunk batch
# carries planner output without importing the metadata key by hand.
SECTION_BUCKET_KEY = "section_bucket"
SECTION_BUCKET_TOPIC_KEY = "section_bucket_topic"


def has_section_buckets(metadatas: list[dict | None]) -> bool:
    """True when at least one chunk metadata carries a section_bucket value."""
    for meta in metadatas:
        if meta and meta.get(SECTION_BUCKET_KEY) is not None:
            return True
    return False


__all__ = [
    "BucketAssignment",
    "PlanResult",
    "SectionPlanner",
    "PLANNER_VERSION",
    "SECTION_BUCKET_KEY",
    "SECTION_BUCKET_TOPIC_KEY",
    "has_section_buckets",
]
