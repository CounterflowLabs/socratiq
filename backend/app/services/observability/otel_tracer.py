"""OtelTracer — maps AgentRuntime / MentorAgent / course-gen trace events to
OpenTelemetry spans + metrics.

Designed to satisfy ``app.services.llm.runtime.Tracer``'s single-method
contract (``emit(event, **fields)``) without changing any caller.

Event → OTel mapping
--------------------

Span pairs (open on first event, close on second; both must carry the same
``phase`` field):

* ``phase_start`` / ``phase_end``                 → span name = phase
* ``agent_turn_start`` / ``agent_turn_end``       → span name = ``mentor.turn``

Retroactive spans (one-shot event with ``elapsed_ms`` — span is created with
``start_time = now - elapsed_ms`` and ended immediately):

* ``provider_call``                  → child span ``provider_call``
* ``agent_loop_iter``                → child span ``mentor.loop.iter[N]``
* ``agent_tool_result``              → child span ``mentor.tool.<name>``
* ``section_planner.plan_finalized`` → span ``section_planner.plan``
* ``course_generation.course_finalized`` → span ``course_generation.finalize``

Events on the currently active span (no own span):

* ``provider_fallback``, ``provider_resolve_failed``
* ``validation_failed``, ``validation_retry``

Unknown events fall through to ``span.add_event(name, attrs)`` on the current
span so future runtime events stay observable without an OtelTracer release.

Metrics
-------

Emitted directly from ``emit()`` — no extra instrumentation needed in callers.
See ``_AgentMetrics`` for the full list. Token / latency dimensions follow OTel
GenAI semantic conventions where stable (``gen_ai.usage.input_tokens`` etc.);
project-specific dimensions live under ``socratiq.*``.

High-cardinality fields (``course_id``, ``user_id``, ``tool_use_id``) become
span attributes only — never metric labels — to keep Prometheus series count
bounded.

Async-context safety
--------------------

Active-phase state lives in a ContextVar keyed by phase string. Each asyncio
task gets its own contextvar copy at task creation, so parallel SectionPlanner
windowed-Layer-2 ``runtime.call`` invocations don't share span state. OTel's
own context-propagation (via ``opentelemetry.context``) is also ContextVar-
backed, so parent/child relationships across ``asyncio.gather`` are correct.
"""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import metrics, trace
from opentelemetry.trace import Span, Status, StatusCode, set_span_in_context

logger = logging.getLogger(__name__)

_INSTRUMENTATION_NAME = "socratiq.agent"
_INSTRUMENTATION_VERSION = "0.1.0"

# Fields we don't want to copy verbatim onto spans / events — either captured
# explicitly under a semconv attribute, or too noisy. Everything else from the
# emit call lands on the span under the ``socratiq.*`` namespace.
_DROPPED_FIELDS = frozenset(
    {
        "phase",
        "elapsed_ms",
        "input_tokens",
        "output_tokens",
        "provider",
        "provider_used",
        "tool_name",
        "tool_use_id",
        "status",
        "error",
        "iteration",
        "iterations",
        "tier_used",
        "course_id",
        "user_id",
    }
)


class _AgentMetrics:
    """The 12 explicit instruments emitted from OtelTracer.

    Auto-instrumentation (fastapi / asyncpg / celery / httpx) adds the
    HTTP, DB, Celery and outbound-HTTP metrics on top of these.
    """

    def __init__(self, meter: metrics.Meter) -> None:
        self.phase_duration = meter.create_histogram(
            name="socratiq.agent.phase.duration_ms",
            unit="ms",
            description="AgentRuntime phase latency (one per runtime.call).",
        )
        self.provider_tokens = meter.create_counter(
            name="socratiq.agent.provider.tokens",
            unit="{token}",
            description="LLM tokens consumed, separated by direction (in/out).",
        )
        self.provider_fallback = meter.create_counter(
            name="socratiq.agent.provider.fallback_total",
            description="Provider chain fallback events.",
        )
        self.validation_failed = meter.create_counter(
            name="socratiq.agent.validation.failed_total",
            description="Schema-validator rejections per phase.",
        )
        self.turn_duration = meter.create_histogram(
            name="socratiq.agent.turn.duration_ms",
            unit="ms",
            description="MentorAgent.process() end-to-end latency.",
        )
        self.turn_iterations = meter.create_histogram(
            name="socratiq.agent.turn.loop_iterations",
            description="Tool-calling loop iterations per mentor turn.",
        )
        self.tool_duration = meter.create_histogram(
            name="socratiq.agent.tool.duration_ms",
            unit="ms",
            description="Per-tool execution latency inside mentor loop.",
        )
        self.section_planner_total = meter.create_counter(
            name="socratiq.section_planner.plan_total",
            description=(
                "SectionPlanner.plan() outcomes by tier "
                "(skeleton/windowed/embedding_only/fallback)."
            ),
        )
        self.section_planner_bucket_count = meter.create_histogram(
            name="socratiq.section_planner.bucket_count",
            description="Bucket count distribution per plan, by tier.",
        )
        self.course_gen_duration = meter.create_histogram(
            name="socratiq.course_generation.duration_ms",
            unit="ms",
            description="CourseGenerator.generate() end-to-end latency.",
        )
        self.lesson_outcome = meter.create_counter(
            name="socratiq.course_generation.lesson.outcome_total",
            description="Per-lesson generation outcomes (ok/failed).",
        )
        self.lab_outcome = meter.create_counter(
            name="socratiq.course_generation.lab.outcome_total",
            description="Per-lab generation outcomes (ok/skipped/failed).",
        )


_ActiveSpans = dict[str, tuple[Span, object]]
"""phase → (span, otel_context_token). Lives in a ContextVar (task-local)."""


class OtelTracer:
    """Implements the ``Tracer`` protocol from ``app.services.llm.runtime``.

    Construct one per process. ``bootstrap.init_otel()`` does this and swaps
    it in via ``set_default_tracer``. Constructing additional instances is
    safe — they share the global TracerProvider / MeterProvider — but in
    practice one is enough.
    """

    def __init__(self) -> None:
        self._tracer = trace.get_tracer(_INSTRUMENTATION_NAME, _INSTRUMENTATION_VERSION)
        self._meter = metrics.get_meter(_INSTRUMENTATION_NAME, _INSTRUMENTATION_VERSION)
        self._m = _AgentMetrics(self._meter)
        self._active: ContextVar[_ActiveSpans] = ContextVar(
            "otel_active_spans", default={}
        )

    # ------------------------------------------------------------------ emit

    def emit(self, event: str, **fields: Any) -> None:
        # The dispatch is split into helpers so the type checker and tests
        # can target each branch without a giant match-case to wade through.
        try:
            handler = _HANDLERS.get(event)
            if handler is not None:
                handler(self, fields)
                return
            # Fall-through: unknown events still land on the current span so
            # operators can see them in Tempo without a tracer release.
            self._add_event_to_current(event, fields)
        except Exception:  # noqa: BLE001
            # Tracing must never break the request — log + continue.
            logger.exception("OtelTracer.emit failed for event=%s", event)

    # -------------------------------------------------------- span lifecycle

    def _open_span(self, span_name: str, phase_key: str, fields: dict[str, Any]) -> None:
        """Open a span and push it onto the task-local active-span map.

        The active map is keyed by ``phase_key`` (usually the phase string)
        so that two parallel runtime.call invocations with different phases
        don't collide. Same-key collisions (e.g. nested ``phase_start`` with
        the same phase) are logged and the newer span wins — recovery from
        a bug-induced double-open is better than dropping the close call.
        """
        attrs = _socratiq_attrs(fields)
        span = self._tracer.start_span(name=span_name, attributes=attrs)
        token = otel_context.attach(set_span_in_context(span))
        current = dict(self._active.get())
        if phase_key in current:
            # Defensive: replace, but warn — caller has a bug.
            logger.warning(
                "OtelTracer: duplicate phase_start for key=%s; replacing", phase_key
            )
            prev_span, prev_token = current[phase_key]
            otel_context.detach(prev_token)
            prev_span.end()
        current[phase_key] = (span, token)
        self._active.set(current)

    def _close_span(
        self,
        phase_key: str,
        *,
        attrs: dict[str, Any] | None = None,
        status: Status | None = None,
    ) -> Span | None:
        """Pop and end the span recorded under ``phase_key``.

        Returns the closed span (for callers that want to record metrics from
        its attributes) or ``None`` if no matching span was found — which
        indicates a missing ``phase_start`` and is logged.
        """
        current = dict(self._active.get())
        entry = current.pop(phase_key, None)
        self._active.set(current)
        if entry is None:
            logger.warning("OtelTracer: phase_end without matching start: %s", phase_key)
            return None
        span, token = entry
        if attrs:
            for k, v in attrs.items():
                if v is not None:
                    span.set_attribute(k, v)
        if status is not None:
            span.set_status(status)
        otel_context.detach(token)
        span.end()
        return span

    def _retro_span(
        self,
        span_name: str,
        elapsed_ms: float,
        *,
        attrs: dict[str, Any] | None = None,
        status: Status | None = None,
    ) -> None:
        """Create a span that already finished ``elapsed_ms`` ago.

        Used for ``emit()`` calls that report a completed action with a
        duration field but no paired start event (``provider_call``,
        ``agent_loop_iter``, ``agent_tool_result``, the two finalize events).

        Parent attachment is implicit via OTel's context propagation —
        whichever span is currently active in the calling task becomes the
        parent.
        """
        end_ns = time.time_ns()
        start_ns = end_ns - max(0, int(elapsed_ms * 1_000_000))
        span = self._tracer.start_span(
            name=span_name,
            start_time=start_ns,
            attributes=attrs or {},
        )
        if status is not None:
            span.set_status(status)
        span.end(end_time=end_ns)

    def _add_event_to_current(self, event: str, fields: dict[str, Any]) -> None:
        span = trace.get_current_span()
        if span is None or not span.is_recording():
            return
        attrs = _socratiq_attrs(fields)
        span.add_event(event, attributes=attrs)

    # ----------------------------------------------------------- handlers

    def _on_phase_start(self, fields: dict[str, Any]) -> None:
        phase = str(fields.get("phase", "unknown"))
        attrs = _phase_start_attrs(fields)
        self._open_span(span_name=phase, phase_key=_phase_key("phase", phase), fields=attrs)

    def _on_phase_end(self, fields: dict[str, Any]) -> None:
        phase = str(fields.get("phase", "unknown"))
        status_str = str(fields.get("status", "ok"))
        otel_status = (
            Status(StatusCode.OK) if status_str == "ok" else Status(StatusCode.ERROR, status_str)
        )
        end_attrs = _phase_end_attrs(fields)
        self._close_span(
            phase_key=_phase_key("phase", phase),
            attrs=end_attrs,
            status=otel_status,
        )
        elapsed = _to_float(fields.get("elapsed_ms"))
        if elapsed is not None:
            self._m.phase_duration.record(
                elapsed,
                attributes={
                    "phase": phase,
                    "status": status_str,
                    "provider_used": str(fields.get("provider_used") or "unknown"),
                },
            )

    def _on_provider_call(self, fields: dict[str, Any]) -> None:
        provider = str(fields.get("provider") or "unknown")
        phase = str(fields.get("phase") or "unknown")
        elapsed = _to_float(fields.get("elapsed_ms")) or 0.0
        in_tok = _to_int(fields.get("input_tokens"))
        out_tok = _to_int(fields.get("output_tokens"))
        attrs = {
            "gen_ai.request.model": provider,
            "gen_ai.usage.input_tokens": in_tok or 0,
            "gen_ai.usage.output_tokens": out_tok or 0,
            "socratiq.agent.phase": phase,
            "socratiq.agent.fallback_depth": _to_int(fields.get("fallback_depth")) or 0,
            "socratiq.agent.attempt": _to_int(fields.get("attempt")) or 0,
            "socratiq.agent.response_chars": _to_int(fields.get("response_chars")) or 0,
        }
        self._retro_span("provider_call", elapsed, attrs=attrs)
        if in_tok:
            self._m.provider_tokens.add(
                in_tok,
                attributes={"provider": provider, "phase": phase, "direction": "in"},
            )
        if out_tok:
            self._m.provider_tokens.add(
                out_tok,
                attributes={"provider": provider, "phase": phase, "direction": "out"},
            )

    def _on_provider_fallback(self, fields: dict[str, Any]) -> None:
        self._add_event_to_current("provider_fallback", fields)
        self._m.provider_fallback.add(
            1,
            attributes={
                "from_provider": str(fields.get("from_provider") or "unknown"),
                "phase": str(fields.get("phase") or "unknown"),
            },
        )

    def _on_provider_resolve_failed(self, fields: dict[str, Any]) -> None:
        self._add_event_to_current("provider_resolve_failed", fields)
        self._m.provider_fallback.add(
            1,
            attributes={
                "from_provider": str(fields.get("ref") or "unknown"),
                "phase": str(fields.get("phase") or "unknown"),
            },
        )

    def _on_validation_failed(self, fields: dict[str, Any]) -> None:
        self._add_event_to_current("validation_failed", fields)
        self._m.validation_failed.add(
            1,
            attributes={
                "phase": str(fields.get("phase") or "unknown"),
                "reason": str(fields.get("reason") or "unknown")[:64],
            },
        )

    def _on_validation_retry(self, fields: dict[str, Any]) -> None:
        self._add_event_to_current("validation_retry", fields)

    def _on_agent_turn_start(self, fields: dict[str, Any]) -> None:
        attrs = _socratiq_attrs(fields)
        # user/course id useful for span search but stripped from metric labels
        if "user_id" in fields and fields["user_id"]:
            attrs["socratiq.user_id"] = str(fields["user_id"])
        if "course_id" in fields and fields["course_id"]:
            attrs["socratiq.course_id"] = str(fields["course_id"])
        self._open_span(span_name="mentor.turn", phase_key="mentor.turn", fields=attrs)

    def _on_agent_turn_end(self, fields: dict[str, Any]) -> None:
        status_str = str(fields.get("status") or "ok")
        otel_status = (
            Status(StatusCode.OK)
            if status_str in ("ok", "text_complete")
            else Status(StatusCode.ERROR, status_str)
        )
        end_attrs = {
            "socratiq.agent.iterations": _to_int(fields.get("iterations")) or 0,
            "socratiq.agent.total_tool_calls": _to_int(fields.get("total_tool_calls")) or 0,
            "socratiq.agent.response_chars": _to_int(fields.get("response_chars")) or 0,
            "socratiq.agent.status": status_str,
        }
        self._close_span(phase_key="mentor.turn", attrs=end_attrs, status=otel_status)
        elapsed = _to_float(fields.get("elapsed_ms"))
        if elapsed is not None:
            self._m.turn_duration.record(elapsed, attributes={"status": status_str})
        iters = _to_int(fields.get("iterations"))
        if iters is not None:
            self._m.turn_iterations.record(iters, attributes={"status": status_str})

    def _on_agent_loop_iter(self, fields: dict[str, Any]) -> None:
        iteration = _to_int(fields.get("iteration")) or 0
        elapsed = _to_float(fields.get("elapsed_ms")) or 0.0
        attrs = {
            "socratiq.agent.iteration": iteration,
            "socratiq.agent.text_chars": _to_int(fields.get("text_chars")) or 0,
            "socratiq.agent.reasoning_chars": _to_int(fields.get("reasoning_chars")) or 0,
            "socratiq.agent.tool_calls": _to_int(fields.get("tool_calls")) or 0,
            "socratiq.agent.provider": str(fields.get("provider") or "unknown"),
        }
        self._retro_span(f"mentor.loop.iter[{iteration}]", elapsed, attrs=attrs)

    def _on_agent_tool_result(self, fields: dict[str, Any]) -> None:
        tool_name = str(fields.get("tool_name") or "unknown")
        status_str = str(fields.get("status") or "ok")
        elapsed = _to_float(fields.get("elapsed_ms")) or 0.0
        attrs = {
            "socratiq.agent.tool_name": tool_name,
            "socratiq.agent.tool_use_id": str(fields.get("tool_use_id") or ""),
            "socratiq.agent.iteration": _to_int(fields.get("iteration")) or 0,
            "socratiq.agent.result_chars": _to_int(fields.get("result_chars")) or 0,
            "socratiq.agent.status": status_str,
        }
        otel_status = (
            Status(StatusCode.OK) if status_str == "ok" else Status(StatusCode.ERROR, status_str)
        )
        self._retro_span(
            f"mentor.tool.{tool_name}",
            elapsed,
            attrs=attrs,
            status=otel_status,
        )
        self._m.tool_duration.record(
            elapsed,
            attributes={"tool_name": tool_name, "status": status_str},
        )

    def _on_section_planner_plan_finalized(self, fields: dict[str, Any]) -> None:
        tier = str(fields.get("tier_used") or "unknown")
        short_circuit = bool(fields.get("short_circuit"))
        has_error = bool(fields.get("error"))
        bucket_count = _to_int(fields.get("bucket_count")) or 0
        elapsed = _to_float(fields.get("elapsed_ms")) or 0.0
        attrs = {
            "socratiq.section_planner.tier_used": tier,
            "socratiq.section_planner.bucket_count": bucket_count,
            "socratiq.section_planner.short_circuit": short_circuit,
            "socratiq.section_planner.buckets_split_for_size": _to_int(
                fields.get("buckets_split_for_size")
            )
            or 0,
            "socratiq.section_planner.llm_input_tokens": _to_int(
                fields.get("llm_input_tokens")
            )
            or 0,
            "socratiq.section_planner.llm_output_tokens": _to_int(
                fields.get("llm_output_tokens")
            )
            or 0,
        }
        if has_error:
            attrs["socratiq.section_planner.error"] = str(fields.get("error"))[:200]
        status = Status(StatusCode.ERROR, str(fields.get("error"))[:200]) if has_error else None
        self._retro_span(
            "section_planner.plan", elapsed, attrs=attrs, status=status
        )
        self._m.section_planner_total.add(
            1,
            attributes={
                "tier_used": tier,
                "short_circuit": str(short_circuit).lower(),
                "has_error": str(has_error).lower(),
            },
        )
        self._m.section_planner_bucket_count.record(
            bucket_count, attributes={"tier_used": tier}
        )

    def _on_course_generation_finalized(self, fields: dict[str, Any]) -> None:
        status_str = str(fields.get("status") or "ok")
        elapsed = _to_float(fields.get("elapsed_ms")) or 0.0
        lesson_ok = _to_int(fields.get("lesson_ok")) or 0
        lesson_failed = _to_int(fields.get("lesson_failed")) or 0
        lab_ok = _to_int(fields.get("lab_ok")) or 0
        lab_skipped = _to_int(fields.get("lab_skipped")) or 0
        lab_failed = _to_int(fields.get("lab_failed")) or 0
        attrs = {
            "socratiq.course_generation.status": status_str,
            "socratiq.course_generation.source_count": _to_int(
                fields.get("source_count")
            )
            or 0,
            "socratiq.course_generation.section_count": _to_int(
                fields.get("section_count")
            )
            or 0,
            "socratiq.course_generation.lesson_ok": lesson_ok,
            "socratiq.course_generation.lesson_failed": lesson_failed,
            "socratiq.course_generation.lab_ok": lab_ok,
            "socratiq.course_generation.lab_skipped": lab_skipped,
            "socratiq.course_generation.lab_failed": lab_failed,
        }
        if fields.get("course_id"):
            # high cardinality — span only, not metric
            attrs["socratiq.course_id"] = str(fields["course_id"])
        otel_status = (
            Status(StatusCode.OK) if status_str == "ok" else Status(StatusCode.ERROR, status_str)
        )
        self._retro_span(
            "course_generation.finalize", elapsed, attrs=attrs, status=otel_status
        )
        self._m.course_gen_duration.record(elapsed, attributes={"status": status_str})
        if lesson_ok:
            self._m.lesson_outcome.add(lesson_ok, attributes={"status": "ok"})
        if lesson_failed:
            self._m.lesson_outcome.add(lesson_failed, attributes={"status": "failed"})
        if lab_ok:
            self._m.lab_outcome.add(lab_ok, attributes={"status": "ok"})
        if lab_skipped:
            self._m.lab_outcome.add(lab_skipped, attributes={"status": "skipped"})
        if lab_failed:
            self._m.lab_outcome.add(lab_failed, attributes={"status": "failed"})


# --- helpers -------------------------------------------------------------


def _phase_key(kind: str, phase: str) -> str:
    """Build the lookup key for the active-span map. Namespaced by kind so
    a future event family can't accidentally collide with a runtime phase
    string of the same name."""
    return f"{kind}:{phase}"


def _socratiq_attrs(fields: dict[str, Any]) -> dict[str, Any]:
    """Coerce arbitrary emit fields into ``socratiq.*`` span attributes."""
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if k in _DROPPED_FIELDS:
            continue
        if v is None:
            continue
        if isinstance(v, (str, bool, int, float)):
            out[f"socratiq.{k}"] = v
        else:
            out[f"socratiq.{k}"] = str(v)
    return out


def _phase_start_attrs(fields: dict[str, Any]) -> dict[str, Any]:
    """``phase_start``-specific attributes (lifted to OTel where possible)."""
    out = _socratiq_attrs(fields)
    out["socratiq.agent.phase"] = str(fields.get("phase") or "")
    if "message_count" in fields:
        out["socratiq.agent.message_count"] = _to_int(fields["message_count"]) or 0
    return out


def _phase_end_attrs(fields: dict[str, Any]) -> dict[str, Any]:
    """``phase_end``-specific attributes — token usage promoted to gen_ai.*."""
    return {
        "socratiq.agent.status": str(fields.get("status") or "ok"),
        "socratiq.agent.attempts": _to_int(fields.get("attempts")) or 0,
        "socratiq.agent.fallback_depth": _to_int(fields.get("fallback_depth")) or 0,
        "gen_ai.usage.input_tokens": _to_int(fields.get("input_tokens")) or 0,
        "gen_ai.usage.output_tokens": _to_int(fields.get("output_tokens")) or 0,
        "gen_ai.request.model": str(fields.get("provider_used") or "unknown"),
    }


def _to_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


_HANDLERS = {
    "phase_start": OtelTracer._on_phase_start,
    "phase_end": OtelTracer._on_phase_end,
    "provider_call": OtelTracer._on_provider_call,
    "provider_fallback": OtelTracer._on_provider_fallback,
    "provider_resolve_failed": OtelTracer._on_provider_resolve_failed,
    "validation_failed": OtelTracer._on_validation_failed,
    "validation_retry": OtelTracer._on_validation_retry,
    "agent_turn_start": OtelTracer._on_agent_turn_start,
    "agent_turn_end": OtelTracer._on_agent_turn_end,
    "agent_loop_iter": OtelTracer._on_agent_loop_iter,
    "agent_tool_result": OtelTracer._on_agent_tool_result,
    "section_planner.plan_finalized": OtelTracer._on_section_planner_plan_finalized,
    "course_generation.course_finalized": OtelTracer._on_course_generation_finalized,
}


__all__ = ["OtelTracer"]
