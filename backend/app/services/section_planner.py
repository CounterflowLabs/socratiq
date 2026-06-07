"""SectionPlanner — groups consecutive chunks into topic-coherent sections.

Implements docs/design/section-planning.md across all four tiers:

  - Layer 1 ("skeleton")        — single-pass LLM call
  - Layer 2 ("windowed")        — windowed-skeleton + LLM seam stitching
                                  (kicks in when input exceeds skeleton budget)
  - Layer 3 ("embedding_only")  — pure TextTiling peak detection, zero LLM
  - Layer 4 ("fallback")        — per-chunk (bucket_id = chunk_index)

Embeddings are used to compute a per-chunk ``boundary_hint`` (cosine distance
from the prior chunk, TextTiling-smoothed, [0,1]-normalized). Layers 1 and 2
feed it to the LLM as a soft prior; Layer 3 uses it as the bucketing signal
itself when no LLM route is available.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.prompt_template import load_prompt
from app.services.content_analyzer import AnalyzedChunk
from app.services.llm.base import LLMError, LLMProvider, UnifiedMessage
from app.services.llm.router import ModelRouter, TaskType
from app.services.llm.runtime import (
    AgentRuntime,
    LLMValidationError,
    ValidationFailed,
)
from app.services.llm.token_budget import count_tokens
from app.tools.extractors.base import RawContentChunk

logger = logging.getLogger(__name__)

_PROMPT = load_prompt(Path(__file__).parent / "prompts" / "section_planning.md")
_STITCH_PROMPT = load_prompt(Path(__file__).parent / "prompts" / "section_stitch.md")

# Stamp on every plan output. Bump when prompt / model / validator changes
# materially so historical sources can be diffed by planner generation.
PLANNER_VERSION = "v2"

# Skeleton input size budget. Once a serialized chunk_inputs array crosses
# this we route to Layer 2 (windowed-skeleton) instead of risking a truncated
# LLM context.
_SKELETON_BUDGET_BYTES = 64 * 1024

# Windowed-skeleton geometry (Layer 2).
_WINDOW_SIZE = 30           # chunks per window
_WINDOW_OVERLAP = 3         # chunks shared with the previous window
_WINDOW_STEP = _WINDOW_SIZE - _WINDOW_OVERLAP

# Short-circuit thresholds — below these, a single bucket is the honest answer.
_SHORT_CIRCUIT_DURATION_SEC = 480.0   # 8 minutes
_SHORT_CIRCUIT_WORD_COUNT = 2000

# Hard cap on bucket count. The validator clamps overshoots by merging the
# tail buckets — long videos still get coarse granularity.
_MAX_BUCKETS = 12

# Layer 3 (embedding-only) bucketing parameters.
_EMBEDDING_BUCKET_TARGET_SEC = 540.0   # ~9-minute buckets (midpoint of 5–15)
_EMBEDDING_BUCKET_TARGET_WORDS = 2750  # midpoint of 1500–4000
_EMBEDDING_MIN_BUCKETS = 3
_EMBEDDING_MAX_BUCKETS = 12

# Conservative cap when the caller doesn't supply a real budget. Keeps unit
# tests and ad-hoc scripts working without forcing every code path to wire a
# provider through. Production callers (content_ingestion) MUST pass the
# real budget computed from the LessonGenerator's provider.
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
    """Plans bucket assignments for a sequence of analyzed chunks."""

    def __init__(self, model_router: ModelRouter):
        self._router = model_router
        self._runtime = AgentRuntime(router=model_router)
        # STRUCTURE_PLANNING is the dedicated tier; EVALUATION is the legacy
        # fallback for deployments that haven't provisioned the new route
        # (matches the historical _get_provider behavior). Resolving via the
        # runtime means the same chain is now visible in trace events.
        self._provider_chain = (
            TaskType.STRUCTURE_PLANNING,
            [TaskType.EVALUATION],
        )

    async def plan(
        self,
        *,
        chunks: list[RawContentChunk],
        analyses: list[AnalyzedChunk],
        embeddings: list[list[float]] | None,
        title: str,
        lesson_input_token_cap: int | None = None,
    ) -> PlanResult:
        """Return one BucketAssignment per chunk, same order and length.

        Tier routing (degrades on failure):
          Layer 1 skeleton  → Layer 2 windowed  → Layer 3 embedding-only
                            → Layer 4 per-chunk

        Layer 1 is the default. Layer 2 takes over when serialized chunk
        inputs exceed the skeleton budget. Layer 3 catches any LLM failure
        when embeddings carry usable signal. Layer 4 is the unconditional
        floor — never raises out of the planner.

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
                tier="skeleton",
                started=started,
                short_circuit=True,
            )

        # Boundary hints: prior-vs-current cosine distance, smoothed and
        # normalized. Failures collapse to zeros — LLM still sees the rest.
        try:
            boundary_hints = _compute_boundary_hints(embeddings_safe)
        except Exception as exc:  # noqa: BLE001
            logger.warning("SectionPlanner: boundary_hint computation failed: %s", exc)
            boundary_hints = [0.0] * n

        chunk_inputs = _build_chunk_inputs(analyses, boundary_hints, size_unit, sizes)
        serialized_size = len(
            json.dumps(chunk_inputs, ensure_ascii=False).encode("utf-8")
        )
        use_windowed = serialized_size > _SKELETON_BUDGET_BYTES

        provider: LLMProvider | None
        provider_error: str | None = None
        try:
            provider = await self._get_provider()
        except LLMError as exc:
            logger.warning("SectionPlanner: no provider available: %s", exc)
            provider = None
            provider_error = f"no_provider:{exc}"

        total_input_tokens = 0
        total_output_tokens = 0

        # --- Layer 1 / Layer 2 ---------------------------------------------
        if provider is not None:
            if use_windowed:
                logger.info(
                    "SectionPlanner: skeleton budget exceeded (%d bytes); "
                    "routing to Layer 2 windowed-skeleton",
                    serialized_size,
                )
                validated, error, tokens = await self._run_layer2_windowed(
                    provider, chunk_inputs, title, n
                )
                tier = "windowed"
            else:
                validated, error, tokens = await self._run_layer1_skeleton(
                    provider, chunk_inputs, title, n
                )
                tier = "skeleton"

            total_input_tokens += tokens[0]
            total_output_tokens += tokens[1]

            if validated is not None:
                return _finalize(
                    raw_assignments=validated,
                    chunks=chunks,
                    cap_tokens=cap_tokens,
                    tier=tier,
                    started=started,
                    llm_input_tokens=total_input_tokens,
                    llm_output_tokens=total_output_tokens,
                )
            llm_error = error
        else:
            llm_error = provider_error or "no_provider"

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
                llm_input_tokens=total_input_tokens,
                llm_output_tokens=total_output_tokens,
                error=llm_error,
            )

        # --- Layer 4 size-greedy floor -------------------------------------
        # Every LLM tier failed and the embedding signal was degenerate. Still
        # coarsen by size rather than emit one-section-per-chunk (the old
        # per-chunk floor is what produced 113-section courses on LLM outage).
        return _finalize(
            raw_assignments=_run_layer4_size_greedy(
                size_unit=size_unit, sizes=sizes, n=n
            ),
            chunks=chunks,
            cap_tokens=cap_tokens,
            tier="fallback",
            started=started,
            llm_input_tokens=total_input_tokens,
            llm_output_tokens=total_output_tokens,
            error=llm_error or "embedding_only_unavailable",
        )

    async def _get_provider(self) -> LLMProvider:
        """Resolve STRUCTURE_PLANNING with a one-step fallback to EVALUATION.

        Pre-resolved once per ``plan()`` call so helpers (Layer 1, windowed
        Layer 2, seam stitch) all share the same provider without churning
        the router cache. The runtime's own provider-fallback chain is
        intentionally NOT used here — keeping resolution out of the per-call
        path means trace events stay focused on the work, not lookup churn.
        """
        try:
            return await self._router.get_provider(TaskType.STRUCTURE_PLANNING)
        except LLMError:
            return await self._router.get_provider(TaskType.EVALUATION)

    async def _run_layer1_skeleton(
        self,
        provider: LLMProvider,
        chunk_inputs: list[dict],
        title: str,
        expected_n: int,
        *,
        phase: str = "section_planner.layer1",
    ) -> tuple[list[BucketAssignment] | None, str | None, tuple[int, int]]:
        """Single-pass skeleton. Returns (assignments | None, error | None, (in_toks, out_toks))."""
        serialized = json.dumps(chunk_inputs, ensure_ascii=False)
        system_prompt = _PROMPT.render(title=title or "Untitled")
        messages = [
            UnifiedMessage(role="system", content=system_prompt),
            UnifiedMessage(role="user", content="Chunks (JSON):\n" + serialized),
        ]

        def _validate(text: str) -> list[BucketAssignment]:
            parsed = _parse_response_json(text)
            if parsed is None:
                raise ValidationFailed(
                    "json_parse_failed",
                    hint="Reply with a single JSON object: `{\"buckets\": [...], \"assignments\": [...]}`.",
                )
            validated = _validate_and_normalize(parsed, expected_n)
            if validated is None:
                raise ValidationFailed(
                    "validation_failed",
                    hint=(
                        f"Return exactly {expected_n} assignments with monotonically "
                        "increasing bucket_ids starting at 0."
                    ),
                )
            return validated

        # max_validation_retries=0 — SectionPlanner's own degradation cascade
        # (Layer 1 → Layer 3 → Layer 4) replaces the runtime's within-layer
        # retry. A bad Layer 1 response should escalate to the next tier
        # rather than burn another STRUCTURE_PLANNING call.
        try:
            result = await self._runtime.call(
                messages,
                primary=provider,
                max_tokens=4096,
                temperature=0.2,
                phase=phase,
                validator=_validate,
                max_validation_retries=0,
            )
        except LLMValidationError as exc:
            return None, exc.reason, (exc.input_tokens, exc.output_tokens)
        except LLMError as exc:
            logger.warning("SectionPlanner: Layer 1 LLM call failed: %s", exc)
            return None, f"llm_error:{type(exc).__name__}", (0, 0)

        return result.parsed, None, (result.input_tokens, result.output_tokens)

    async def _run_layer2_windowed(
        self,
        provider: LLMProvider,
        chunk_inputs: list[dict],
        title: str,
        expected_n: int,
    ) -> tuple[list[BucketAssignment] | None, str | None, tuple[int, int]]:
        """Windowed skeleton with LLM seam stitching.

        Each window covers ``_WINDOW_SIZE`` chunks and overlaps the previous
        window by ``_WINDOW_OVERLAP``. The overlap region is owned by the
        LATER window — earlier windows are truncated at ``end - overlap`` so
        each chunk appears in the final output exactly once.

        After concatenation with monotonically increasing bucket-id offsets,
        a per-seam LLM merge pass collapses adjacent buckets that describe
        the same theme (the design's "窗口缝合方案"). Failed seam calls
        leave the boundary intact — a false split is the safer default.
        """
        windows = _build_window_spans(expected_n)
        if len(windows) <= 1:
            # Degenerates to a single window — run Layer 1 directly.
            return await self._run_layer1_skeleton(
                provider, chunk_inputs, title, expected_n
            )

        async def _gen_window(idx_span: tuple[int, tuple[int, int]]):
            w_idx, span = idx_span
            start, end = span
            # Renumber the per-window idx so the prompt's monotonicity rule
            # is local to this window. The validator also operates on this
            # local indexing.
            window_inputs = [
                {**ci, "idx": j} for j, ci in enumerate(chunk_inputs[start:end])
            ]
            return await self._run_layer1_skeleton(
                provider, window_inputs, title,
                expected_n=end - start,
                phase=f"section_planner.layer2.window[{w_idx + 1}/{len(windows)}]",
            )

        window_results = await asyncio.gather(
            *(_gen_window((i, span)) for i, span in enumerate(windows)),
            return_exceptions=False,
        )

        # Token accounting first — even on failure we report what we spent.
        in_toks = sum(r[2][0] for r in window_results)
        out_toks = sum(r[2][1] for r in window_results)

        if any(r[0] is None for r in window_results):
            errors = [r[1] for r in window_results if r[1]]
            return None, f"windowed_failed:{errors[0] if errors else 'unknown'}", (in_toks, out_toks)

        # Concatenate windows, truncating each non-final window at its
        # non-overlap boundary. The later window owns the overlap chunks.
        combined: list[BucketAssignment] = []
        bucket_offset = 0
        # Track where each window's contribution starts in the combined list,
        # so the stitching pass can find seam positions.
        window_starts_in_combined: list[int] = []
        for w_idx, (span, result) in enumerate(zip(windows, window_results)):
            start, end = span
            window_assignments = result[0]
            assert window_assignments is not None  # checked above

            if w_idx + 1 < len(windows):
                # Drop the overlap tail — next window owns chunks[end-overlap..end)
                usable_len = (end - _WINDOW_OVERLAP) - start
            else:
                usable_len = end - start

            window_starts_in_combined.append(len(combined))
            for a in window_assignments[:usable_len]:
                combined.append(
                    BucketAssignment(
                        bucket_id=a.bucket_id + bucket_offset,
                        bucket_topic=a.bucket_topic,
                    )
                )

            # Next window starts a fresh bucket numbering above this one's max.
            if combined:
                bucket_offset = max(a.bucket_id for a in combined) + 1

        if len(combined) != expected_n:
            logger.warning(
                "SectionPlanner: windowed concat length mismatch %d != %d",
                len(combined), expected_n,
            )
            return None, "windowed_concat_length_mismatch", (in_toks, out_toks)

        # Stitch seams: for each window boundary, ask LLM whether the bucket
        # ending right before the seam should merge with the bucket starting
        # at the seam. The two buckets always differ at this point because
        # bucket_offset bumped on window transition.
        stitched, stitch_in_toks, stitch_out_toks = await self._stitch_seams(
            provider=provider,
            combined=combined,
            chunk_inputs=chunk_inputs,
            window_starts=window_starts_in_combined,
            title=title,
        )
        in_toks += stitch_in_toks
        out_toks += stitch_out_toks

        # Hard cap: even after stitching, never exceed _MAX_BUCKETS.
        stitched = _clamp_bucket_count(stitched, _MAX_BUCKETS)
        return stitched, None, (in_toks, out_toks)

    async def _stitch_seams(
        self,
        *,
        provider: LLMProvider,
        combined: list[BucketAssignment],
        chunk_inputs: list[dict],
        window_starts: list[int],
        title: str,
    ) -> tuple[list[BucketAssignment], int, int]:
        """LLM-judged merge at each window seam.

        ``window_starts`` lists the index in ``combined`` where each window
        contributes its first chunk; seams are at positions [1:] (the very
        first window has no seam in front of it). We process seams in order,
        and after each merge the surviving bucket ids stay valid for the
        remaining seams (smaller ids unaffected).
        """
        in_toks_total = 0
        out_toks_total = 0
        if len(window_starts) <= 1:
            return combined, 0, 0

        result = list(combined)
        for seam_pos in window_starts[1:]:
            # Find adjacent bucket ids around this seam in the CURRENT result.
            # seam_pos may be inside a bucket if a previous merge collapsed
            # things, in which case there's nothing to do for this seam.
            if seam_pos <= 0 or seam_pos >= len(result):
                continue
            prev_bid = result[seam_pos - 1].bucket_id
            next_bid = result[seam_pos].bucket_id
            if prev_bid == next_bid:
                continue  # already merged by a prior seam decision

            decision, in_toks, out_toks = await self._llm_should_merge_seam(
                provider=provider,
                topic_a=result[seam_pos - 1].bucket_topic or "(unnamed)",
                topic_b=result[seam_pos].bucket_topic or "(unnamed)",
                summaries_a=[
                    ci.get("summary", "")
                    for ci in chunk_inputs[max(0, seam_pos - _WINDOW_OVERLAP):seam_pos]
                ],
                summaries_b=[
                    ci.get("summary", "")
                    for ci in chunk_inputs[seam_pos:seam_pos + _WINDOW_OVERLAP]
                ],
                title=title,
            )
            in_toks_total += in_toks
            out_toks_total += out_toks
            if decision:
                result = _merge_seam_buckets(result, next_bid, prev_bid)

        return result, in_toks_total, out_toks_total

    async def _llm_should_merge_seam(
        self,
        *,
        provider: LLMProvider,
        topic_a: str,
        topic_b: str,
        summaries_a: list[str],
        summaries_b: list[str],
        title: str,
    ) -> tuple[bool, int, int]:
        """Ask the LLM whether the two adjacent buckets describe one theme.

        Returns (merge_decision, in_tokens, out_tokens). On any failure
        (transport error, unparseable JSON, missing key) the decision
        defaults to ``False`` (keep boundary) — false-split is the cheaper
        mistake than false-merge.
        """
        sa = "\n".join(f"    - {s}" for s in summaries_a) or "    - (none)"
        sb = "\n".join(f"    - {s}" for s in summaries_b) or "    - (none)"
        prompt = _STITCH_PROMPT.render(
            title=title or "Untitled",
            topic_a=topic_a,
            topic_b=topic_b,
            summaries_a=sa,
            summaries_b=sb,
        )
        messages = [UnifiedMessage(role="system", content=prompt)]

        def _validate(text: str) -> bool:
            parsed = _parse_response_json(text)
            if not isinstance(parsed, dict):
                raise ValidationFailed(
                    "stitch_response_not_object",
                    hint="Reply with a JSON object containing a `merge` boolean.",
                )
            return bool(parsed.get("merge"))

        try:
            result = await self._runtime.call(
                messages,
                primary=provider,
                max_tokens=200,
                temperature=0.0,
                phase="section_planner.stitch_seam",
                validator=_validate,
                max_validation_retries=0,
            )
        except LLMValidationError as exc:
            return False, exc.input_tokens, exc.output_tokens
        except LLMError as exc:
            logger.warning("SectionPlanner: stitch LLM call failed: %s", exc)
            return False, 0, 0

        return bool(result.parsed), result.input_tokens, result.output_tokens


# --- helpers ---------------------------------------------------------------


def _build_window_spans(n: int) -> list[tuple[int, int]]:
    """Compute (start, end) windows of size ``_WINDOW_SIZE`` overlapping the
    previous window by ``_WINDOW_OVERLAP`` chunks.

    For n ≤ _WINDOW_SIZE the caller short-circuits (single window). The last
    window always reaches ``n`` exactly; we tolerate a final stub window
    smaller than ``_WINDOW_SIZE`` rather than padding.
    """
    if n <= 0:
        return []
    if n <= _WINDOW_SIZE:
        return [(0, n)]
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        end = min(start + _WINDOW_SIZE, n)
        spans.append((start, end))
        if end == n:
            break
        next_start = end - _WINDOW_OVERLAP
        # Guard against degenerate parameters that would not advance.
        if next_start <= start:
            spans.append((end, n))
            break
        start = next_start
    return spans


def _merge_seam_buckets(
    assignments: list[BucketAssignment],
    seam_bid: int,
    target_bid: int,
) -> list[BucketAssignment]:
    """Collapse bucket ``seam_bid`` into ``target_bid`` and shift larger ids down.

    All chunks that had ``seam_bid`` adopt ``target_bid`` AND ``target_bid``'s
    topic (so per-bucket topic stays consistent). All ids strictly greater
    than ``seam_bid`` shift down by one to keep ids contiguous.
    """
    target_topic = next(
        (a.bucket_topic for a in assignments if a.bucket_id == target_bid),
        None,
    )
    new: list[BucketAssignment] = []
    for a in assignments:
        if a.bucket_id == seam_bid:
            new.append(BucketAssignment(bucket_id=target_bid, bucket_topic=target_topic))
        elif a.bucket_id > seam_bid:
            new.append(
                BucketAssignment(bucket_id=a.bucket_id - 1, bucket_topic=a.bucket_topic)
            )
        else:
            new.append(a)
    return new


def _clamp_bucket_count(
    assignments: list[BucketAssignment],
    cap: int,
) -> list[BucketAssignment]:
    """Cap distinct bucket count at ``cap`` by merging tail buckets into
    bucket ``cap - 1``. Idempotent when already under the cap."""
    distinct = sorted({a.bucket_id for a in assignments})
    if len(distinct) <= cap:
        return assignments
    survivor = cap - 1
    new: list[BucketAssignment] = []
    survivor_topic: str | None = None
    for a in assignments:
        new_id = min(a.bucket_id, survivor)
        if new_id == survivor and survivor_topic is None and a.bucket_topic:
            survivor_topic = a.bucket_topic
        new.append(BucketAssignment(bucket_id=new_id, bucket_topic=a.bucket_topic))
    # Normalize topic for the merged tail so it reads consistently.
    return [
        BucketAssignment(
            bucket_id=a.bucket_id,
            bucket_topic=(survivor_topic if a.bucket_id == survivor else a.bucket_topic),
        )
        for a in new
    ]


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
    llm_input_tokens: int = 0,
    llm_output_tokens: int = 0,
) -> PlanResult:
    """Apply the size-cap split, compute stats, return the final PlanResult.

    Centralized so every tier exit path (short-circuit, Layer 1/2, Layer
    3, Layer 4) goes through the same finalize step — no path can bypass
    the size-cap pass.
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
            llm_input_tokens=llm_input_tokens,
            llm_output_tokens=llm_output_tokens,
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
    the caller can drop to Layer 4 per-chunk fallback instead of producing
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


def _run_layer4_size_greedy(
    *,
    size_unit: str,
    sizes: list[float],
    n: int,
) -> list[BucketAssignment]:
    """Layer 4 floor that still coarsens by size — never one-section-per-chunk.

    Reached only when every LLM tier failed AND the embedding signal was
    degenerate (Layer 3 returned ``None``). The old floor here was strict
    per-chunk bucketing, which silently turned a long source into N
    topicless sections (e.g. a 113-chunk video → 113 sections). Instead we
    greedily pack consecutive chunks into buckets targeting the same
    ~9-minute / ~2750-word size as Layer 3, bounded by
    ``_EMBEDDING_MIN/MAX_BUCKETS``. Topic stays ``None`` (no LLM ran).

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
    section title in this mode (legacy behavior). Reserved now for degenerate
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
    llm_input_tokens: int = 0,
    llm_output_tokens: int = 0,
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
