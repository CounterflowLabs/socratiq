"""SectionPlanner — groups consecutive chunks into topic-coherent sections.

Implements Phase 1 of docs/design/section-planning.md:
  - Layer 1: single-pass skeleton via LLM
  - Layer 3: per-chunk fallback (zero-LLM, equals legacy behavior)

Layer 2 (windowed-skeleton) is reserved for Phase 2; when the Layer 1 input
exceeds the size budget, we currently fall through to Layer 3.

Embeddings are used to compute a per-chunk ``boundary_hint`` (cosine distance
from the prior chunk, TextTiling-smoothed, [0,1]-normalized) that goes into
the prompt as a soft prior for the LLM. The planner never decides buckets
from embeddings alone in this phase.
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.prompt_template import load_prompt
from app.services.content_analyzer import AnalyzedChunk
from app.services.llm.base import LLMError, UnifiedMessage
from app.services.llm.router import ModelRouter, TaskType
from app.tools.extractors.base import RawContentChunk

logger = logging.getLogger(__name__)

_PROMPT = load_prompt(Path(__file__).parent / "prompts" / "section_planning.md")

# Stamp on every plan output. Bump when prompt / model / validator changes
# materially so historical sources can be diffed by planner generation.
PLANNER_VERSION = "v1"

# Skeleton input size budget. Once a serialized chunk_inputs array crosses
# this we fall back instead of risking a truncated LLM context. Phase 2's
# windowed-skeleton fills the gap above this threshold.
_SKELETON_BUDGET_BYTES = 64 * 1024

# Short-circuit thresholds — below these, a single bucket is the honest answer.
_SHORT_CIRCUIT_DURATION_SEC = 480.0   # 8 minutes
_SHORT_CIRCUIT_WORD_COUNT = 2000

# Hard cap on bucket count. The validator clamps overshoots by merging the
# tail buckets — long videos still get coarse granularity.
_MAX_BUCKETS = 12


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
    """Plans bucket assignments for a sequence of analyzed chunks."""

    def __init__(self, model_router: ModelRouter):
        self._router = model_router

    async def plan(
        self,
        *,
        chunks: list[RawContentChunk],
        analyses: list[AnalyzedChunk],
        embeddings: list[list[float]] | None,
        title: str,
    ) -> PlanResult:
        """Return one BucketAssignment per chunk, same order and length.

        Any LLM or parse failure routes to the per-chunk fallback so the
        caller never raises out of section planning. The pipeline must
        survive STRUCTURE_PLANNING route misconfiguration silently.
        """
        started = time.perf_counter()
        n = len(chunks)
        if n == 0:
            return PlanResult(
                assignments=[],
                stats=_build_stats(
                    tier="fallback",
                    assignments=[],
                    elapsed_ms=_elapsed_ms(started),
                    error="empty_input",
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
            return PlanResult(
                assignments=_fallback_assignments(n),
                stats=_build_stats(
                    tier="fallback",
                    assignments=_fallback_assignments(n),
                    elapsed_ms=_elapsed_ms(started),
                    error="length_mismatch",
                ),
            )

        size_unit, sizes = _detect_size_unit(chunks, analyses)
        if _should_short_circuit(size_unit, sizes):
            topic = (analyses[0].topic or title or None) if analyses else None
            assignments = [BucketAssignment(bucket_id=0, bucket_topic=topic) for _ in range(n)]
            return PlanResult(
                assignments=assignments,
                stats=_build_stats(
                    tier="skeleton",
                    assignments=assignments,
                    elapsed_ms=_elapsed_ms(started),
                    short_circuit=True,
                ),
            )

        # Boundary hints: prior-vs-current cosine distance, smoothed and
        # normalized. Failures collapse to zeros — LLM still sees the rest.
        try:
            boundary_hints = _compute_boundary_hints(embeddings_safe)
        except Exception as exc:  # noqa: BLE001
            logger.warning("SectionPlanner: boundary_hint computation failed: %s", exc)
            boundary_hints = [0.0] * n

        chunk_inputs = _build_chunk_inputs(analyses, boundary_hints, size_unit, sizes)
        serialized = json.dumps(chunk_inputs, ensure_ascii=False)
        if len(serialized.encode("utf-8")) > _SKELETON_BUDGET_BYTES:
            logger.info(
                "SectionPlanner: skeleton budget exceeded (%d bytes); falling back",
                len(serialized.encode("utf-8")),
            )
            return PlanResult(
                assignments=_fallback_assignments(n),
                stats=_build_stats(
                    tier="fallback",
                    assignments=_fallback_assignments(n),
                    elapsed_ms=_elapsed_ms(started),
                    error="skeleton_budget_exceeded",
                ),
            )

        try:
            provider = await self._get_provider()
        except LLMError as exc:
            logger.warning("SectionPlanner: no provider available: %s", exc)
            return PlanResult(
                assignments=_fallback_assignments(n),
                stats=_build_stats(
                    tier="fallback",
                    assignments=_fallback_assignments(n),
                    elapsed_ms=_elapsed_ms(started),
                    error=f"no_provider:{exc}",
                ),
            )

        system_prompt = _PROMPT.render(title=title or "Untitled")
        user_message = "Chunks (JSON):\n" + serialized
        messages = [
            UnifiedMessage(role="system", content=system_prompt),
            UnifiedMessage(role="user", content=user_message),
        ]

        try:
            response = await provider.chat(messages, max_tokens=4096, temperature=0.2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("SectionPlanner: LLM call failed: %s", exc)
            return PlanResult(
                assignments=_fallback_assignments(n),
                stats=_build_stats(
                    tier="fallback",
                    assignments=_fallback_assignments(n),
                    elapsed_ms=_elapsed_ms(started),
                    error=f"llm_error:{type(exc).__name__}",
                ),
            )

        response_text = "".join(
            b.text or "" for b in response.content if b.type == "text"
        )
        input_tokens = response.usage.input_tokens if response.usage else 0
        output_tokens = response.usage.output_tokens if response.usage else 0

        parsed = _parse_response_json(response_text)
        if parsed is None:
            return PlanResult(
                assignments=_fallback_assignments(n),
                stats=_build_stats(
                    tier="fallback",
                    assignments=_fallback_assignments(n),
                    elapsed_ms=_elapsed_ms(started),
                    error="json_parse_failed",
                    llm_input_tokens=input_tokens,
                    llm_output_tokens=output_tokens,
                ),
            )

        validated = _validate_and_normalize(parsed, n)
        if validated is None:
            return PlanResult(
                assignments=_fallback_assignments(n),
                stats=_build_stats(
                    tier="fallback",
                    assignments=_fallback_assignments(n),
                    elapsed_ms=_elapsed_ms(started),
                    error="validation_failed",
                    llm_input_tokens=input_tokens,
                    llm_output_tokens=output_tokens,
                ),
            )

        return PlanResult(
            assignments=validated,
            stats=_build_stats(
                tier="skeleton",
                assignments=validated,
                elapsed_ms=_elapsed_ms(started),
                llm_input_tokens=input_tokens,
                llm_output_tokens=output_tokens,
            ),
        )

    async def _get_provider(self):
        """Resolve STRUCTURE_PLANNING with a one-step fallback to EVALUATION.

        Until operators provision a dedicated STRUCTURE_PLANNING route, lean
        on the fast/cheap tier that EVALUATION already points at. Both
        misses surface as LLMError so the caller hits Layer 3.
        """
        try:
            return await self._router.get_provider(TaskType.STRUCTURE_PLANNING)
        except LLMError:
            return await self._router.get_provider(TaskType.EVALUATION)


# --- helpers ---------------------------------------------------------------


def _detect_size_unit(
    chunks: list[RawContentChunk],
    analyses: list[AnalyzedChunk],
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
    if not a or not b:
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


def _build_chunk_inputs(
    analyses: list[AnalyzedChunk],
    boundary_hints: list[float],
    size_unit: str,
    sizes: list[float],
) -> list[dict]:
    inputs: list[dict] = []
    for i, analyzed in enumerate(analyses):
        summary_raw = getattr(analyzed, "summary", "") or getattr(analyzed, "topic", "") or ""
        summary = summary_raw.strip()
        size_val: float | int
        if size_unit == "duration_sec":
            size_val = round(float(sizes[i]), 2)
        else:
            size_val = int(sizes[i])
        inputs.append(
            {
                "idx": i,
                "summary": summary[:600],
                "boundary_hint": round(float(boundary_hints[i]), 3),
                size_unit: size_val,
            }
        )
    return inputs


def _parse_response_json(text: str) -> dict | None:
    """Strip optional markdown fences and parse strict JSON."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("SectionPlanner: response is not valid JSON: %s", cleaned[:200])
        return None


def _validate_and_normalize(
    payload: dict, expected_n: int
) -> list[BucketAssignment] | None:
    """Enforce the prompt contract and clamp bucket count to ``_MAX_BUCKETS``.

    Reject (return None) for: length mismatch, non-monotonic bucket_ids,
    bucket_ids referencing buckets not declared in ``buckets``. Clamp (don't
    reject) for: bucket count > _MAX_BUCKETS (merge tail), bucket count > n
    (impossible since IDs are monotonic, but covered defensively).
    """
    if not isinstance(payload, dict):
        return None
    buckets_raw = payload.get("buckets")
    assignments_raw = payload.get("assignments")
    if not isinstance(buckets_raw, list) or not isinstance(assignments_raw, list):
        return None
    if len(assignments_raw) != expected_n:
        logger.warning(
            "SectionPlanner: assignments length %d != chunks %d",
            len(assignments_raw),
            expected_n,
        )
        return None

    # Collect ordered bucket_ids, verify monotonic non-decreasing.
    ordered_ids: list[int] = []
    for i, entry in enumerate(assignments_raw):
        if not isinstance(entry, dict):
            return None
        bid = entry.get("bucket_id")
        if not isinstance(bid, int):
            try:
                bid = int(bid)  # tolerate "0" / 0.0
            except (TypeError, ValueError):
                return None
        if ordered_ids and bid < ordered_ids[-1]:
            logger.warning(
                "SectionPlanner: non-monotonic bucket_id at idx %d: %d < %d",
                i, bid, ordered_ids[-1],
            )
            return None
        ordered_ids.append(bid)

    # Build topic lookup. Tolerate missing topics — they're optional.
    topic_by_id: dict[int, str | None] = {}
    for b in buckets_raw:
        if not isinstance(b, dict):
            continue
        bid = b.get("id")
        try:
            bid_int = int(bid) if bid is not None else None
        except (TypeError, ValueError):
            bid_int = None
        if bid_int is None:
            continue
        topic = b.get("topic")
        if isinstance(topic, str):
            topic = topic.strip() or None
        else:
            topic = None
        topic_by_id[bid_int] = topic

    # Every referenced bucket must be declared.
    distinct = sorted(set(ordered_ids))
    for bid in distinct:
        if bid not in topic_by_id:
            logger.warning(
                "SectionPlanner: assignment refers to undeclared bucket %d", bid
            )
            return None

    # Renumber the distinct ids to start at 0 and be contiguous. The prompt
    # already requires this but defensive re-mapping costs nothing.
    remap = {old: new for new, old in enumerate(distinct)}
    normalized_ids = [remap[b] for b in ordered_ids]
    normalized_topics = {remap[old]: topic_by_id[old] for old in distinct}

    # Hard cap: merge tail buckets into bucket _MAX_BUCKETS - 1.
    if len(distinct) > _MAX_BUCKETS:
        logger.info(
            "SectionPlanner: clamping bucket count %d -> %d",
            len(distinct), _MAX_BUCKETS,
        )
        cap = _MAX_BUCKETS - 1
        normalized_ids = [min(b, cap) for b in normalized_ids]
        # Keep topic for the surviving id of the merged tail (first one wins).
        merged_topics: dict[int, str | None] = {}
        for b in normalized_ids:
            if b not in merged_topics:
                merged_topics[b] = normalized_topics.get(b)
        normalized_topics = merged_topics

    return [
        BucketAssignment(bucket_id=b, bucket_topic=normalized_topics.get(b))
        for b in normalized_ids
    ]


def _fallback_assignments(n: int) -> list[BucketAssignment]:
    """Layer 3: bucket_id = chunk_index. Topic stays None — chunk's own
    ``topic`` from ContentAnalyzer is what course_generator uses as the
    section title in this mode (legacy behavior)."""
    return [BucketAssignment(bucket_id=i, bucket_topic=None) for i in range(n)]


def _build_stats(
    *,
    tier: str,
    assignments: list[BucketAssignment],
    elapsed_ms: int,
    error: str | None = None,
    short_circuit: bool = False,
    llm_input_tokens: int = 0,
    llm_output_tokens: int = 0,
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
        "llm_input_tokens": llm_input_tokens,
        "llm_output_tokens": llm_output_tokens,
        "short_circuit": short_circuit,
        "error": error,
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
