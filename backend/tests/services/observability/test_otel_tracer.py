"""Unit tests for ``OtelTracer`` — span tree shape, metric emission, async safety."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.services.observability.otel_tracer import OtelTracer


# --- fixtures --------------------------------------------------------------


@pytest.fixture(scope="module")
def otel_providers() -> tuple[InMemorySpanExporter, InMemoryMetricReader]:
    """Install in-memory providers once per module.

    OTel-Python ``set_tracer_provider`` is logically one-shot, so we set it
    here and accumulate spans across tests; the per-test fixture below
    clears the exporter so each test sees a clean slate.
    """
    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)
    return span_exporter, metric_reader


@pytest.fixture
def tracer(otel_providers: tuple[InMemorySpanExporter, InMemoryMetricReader]) -> OtelTracer:
    span_exporter, _ = otel_providers
    span_exporter.clear()
    return OtelTracer()


# --- helpers ---------------------------------------------------------------


def _spans_named(exporter: InMemorySpanExporter, name: str):
    return [s for s in exporter.get_finished_spans() if s.name == name]


def _metric_points(reader: InMemoryMetricReader, name: str) -> list[Any]:
    data = reader.get_metrics_data()
    if data is None:
        return []
    out: list[Any] = []
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name == name:
                    out.extend(metric.data.data_points)
    return out


# --- phase span pair -------------------------------------------------------


class TestPhaseSpanPair:
    def test_phase_start_end_produces_one_span(
        self,
        tracer: OtelTracer,
        otel_providers,
    ) -> None:
        span_exporter, _ = otel_providers
        tracer.emit("phase_start", phase="t.unit", message_count=2)
        tracer.emit(
            "phase_end",
            phase="t.unit",
            status="ok",
            elapsed_ms=12.5,
            provider_used="claude-x",
            attempts=1,
            input_tokens=10,
            output_tokens=5,
        )
        spans = _spans_named(span_exporter, "t.unit")
        assert len(spans) == 1
        attrs = dict(spans[0].attributes or {})
        assert attrs["gen_ai.usage.input_tokens"] == 10
        assert attrs["gen_ai.usage.output_tokens"] == 5
        assert attrs["gen_ai.request.model"] == "claude-x"
        assert attrs["socratiq.agent.status"] == "ok"

    def test_phase_duration_histogram_records_sample(
        self,
        tracer: OtelTracer,
        otel_providers,
    ) -> None:
        _, metric_reader = otel_providers
        tracer.emit("phase_start", phase="t.metric")
        tracer.emit(
            "phase_end",
            phase="t.metric",
            status="ok",
            elapsed_ms=42.0,
            provider_used="claude-y",
        )
        points = _metric_points(metric_reader, "socratiq.agent.phase.duration_ms")
        # Histogram dataclass exposes ``sum`` and ``count`` per bucket-attribute
        matching = [p for p in points if dict(p.attributes).get("phase") == "t.metric"]
        assert matching, "phase=t.metric sample missing from histogram"
        assert matching[-1].count >= 1
        assert matching[-1].sum >= 42.0

    def test_phase_end_without_start_does_not_crash(self, tracer: OtelTracer) -> None:
        # Logs a warning but never raises — tracing must not break the request.
        tracer.emit("phase_end", phase="t.orphan", status="ok", elapsed_ms=1.0)


# --- provider_call retroactive span ----------------------------------------


class TestProviderCallSpan:
    def test_provider_call_is_child_of_phase_span(
        self,
        tracer: OtelTracer,
        otel_providers,
    ) -> None:
        span_exporter, _ = otel_providers
        tracer.emit("phase_start", phase="t.parent")
        tracer.emit(
            "provider_call",
            phase="t.parent",
            provider="claude-x",
            fallback_depth=0,
            attempt=1,
            input_tokens=8,
            output_tokens=3,
            elapsed_ms=20.0,
            response_chars=120,
        )
        tracer.emit("phase_end", phase="t.parent", status="ok", elapsed_ms=25.0)

        parent_spans = _spans_named(span_exporter, "t.parent")
        child_spans = _spans_named(span_exporter, "provider_call")
        assert len(parent_spans) == 1 and len(child_spans) == 1
        # parent_span_id of child matches parent's span_id
        assert child_spans[0].parent.span_id == parent_spans[0].context.span_id  # type: ignore[union-attr]

    def test_provider_tokens_counter_split_by_direction(
        self,
        tracer: OtelTracer,
        otel_providers,
    ) -> None:
        _, metric_reader = otel_providers
        tracer.emit("phase_start", phase="t.tok")
        tracer.emit(
            "provider_call",
            phase="t.tok",
            provider="claude-x",
            input_tokens=100,
            output_tokens=50,
            elapsed_ms=5.0,
        )
        tracer.emit("phase_end", phase="t.tok", status="ok", elapsed_ms=6.0)

        points = _metric_points(metric_reader, "socratiq.agent.provider.tokens")
        by_direction = {dict(p.attributes).get("direction"): p.value for p in points}
        assert by_direction.get("in") == 100
        assert by_direction.get("out") == 50


# --- events on current span ------------------------------------------------


class TestSpanEvents:
    def test_validation_failed_adds_event_and_counter(
        self,
        tracer: OtelTracer,
        otel_providers,
    ) -> None:
        span_exporter, metric_reader = otel_providers
        tracer.emit("phase_start", phase="t.val")
        tracer.emit(
            "validation_failed",
            phase="t.val",
            attempt=1,
            reason="bad_json",
            hint="emit JSON only",
        )
        tracer.emit("phase_end", phase="t.val", status="ok", elapsed_ms=1.0)

        spans = _spans_named(span_exporter, "t.val")
        events = [e.name for e in spans[0].events]
        assert "validation_failed" in events
        # counter incremented
        points = _metric_points(metric_reader, "socratiq.agent.validation.failed_total")
        assert any(dict(p.attributes).get("phase") == "t.val" for p in points)

    def test_provider_fallback_event_and_counter(
        self,
        tracer: OtelTracer,
        otel_providers,
    ) -> None:
        span_exporter, metric_reader = otel_providers
        tracer.emit("phase_start", phase="t.fb")
        tracer.emit(
            "provider_fallback",
            phase="t.fb",
            from_provider="claude-x",
            from_depth=0,
            error="LLMError: boom",
        )
        tracer.emit("phase_end", phase="t.fb", status="ok", elapsed_ms=1.0)

        spans = _spans_named(span_exporter, "t.fb")
        assert "provider_fallback" in [e.name for e in spans[0].events]
        points = _metric_points(metric_reader, "socratiq.agent.provider.fallback_total")
        assert any(dict(p.attributes).get("from_provider") == "claude-x" for p in points)


# --- mentor turn / loop / tool nesting -------------------------------------


class TestMentorSpans:
    def test_full_mentor_turn_produces_nested_tree(
        self,
        tracer: OtelTracer,
        otel_providers,
    ) -> None:
        span_exporter, metric_reader = otel_providers
        tracer.emit(
            "agent_turn_start",
            phase="mentor",
            user_id="u1",
            course_id="c1",
            provider="claude-x",
            tool_count=3,
            history_messages=2,
        )
        tracer.emit(
            "agent_loop_iter",
            phase="mentor",
            iteration=1,
            provider="claude-x",
            text_chars=200,
            reasoning_chars=10,
            tool_calls=1,
            elapsed_ms=500.0,
        )
        tracer.emit(
            "agent_tool_result",
            phase="mentor.tool",
            iteration=1,
            tool_name="search_knowledge",
            tool_use_id="tu_1",
            status="ok",
            result_chars=140,
            elapsed_ms=80.0,
        )
        tracer.emit(
            "agent_turn_end",
            phase="mentor",
            status="text_complete",
            iterations=1,
            total_tool_calls=1,
            response_chars=200,
            elapsed_ms=700.0,
        )

        turn_spans = _spans_named(span_exporter, "mentor.turn")
        iter_spans = _spans_named(span_exporter, "mentor.loop.iter[1]")
        tool_spans = _spans_named(span_exporter, "mentor.tool.search_knowledge")
        assert len(turn_spans) == 1
        assert len(iter_spans) == 1
        assert len(tool_spans) == 1
        # mentor.turn is the root; loop.iter is its child
        assert iter_spans[0].parent.span_id == turn_spans[0].context.span_id  # type: ignore[union-attr]

        turn_dur = _metric_points(metric_reader, "socratiq.agent.turn.duration_ms")
        assert any(dict(p.attributes).get("status") == "text_complete" for p in turn_dur)
        tool_dur = _metric_points(metric_reader, "socratiq.agent.tool.duration_ms")
        assert any(dict(p.attributes).get("tool_name") == "search_knowledge" for p in tool_dur)


# --- section_planner.plan_finalized ---------------------------------------


class TestSectionPlannerFinalized:
    def test_emits_span_and_metrics_with_tier_label(
        self,
        tracer: OtelTracer,
        otel_providers,
    ) -> None:
        span_exporter, metric_reader = otel_providers
        tracer.emit(
            "section_planner.plan_finalized",
            phase="section_planner.plan",
            tier_used="windowed",
            bucket_count=6,
            short_circuit=False,
            buckets_split_for_size=1,
            llm_input_tokens=4000,
            llm_output_tokens=400,
            elapsed_ms=2500.0,
            error=None,
        )
        spans = _spans_named(span_exporter, "section_planner.plan")
        assert len(spans) == 1
        attrs = dict(spans[0].attributes or {})
        assert attrs["socratiq.section_planner.tier_used"] == "windowed"
        assert attrs["socratiq.section_planner.bucket_count"] == 6

        plan_total = _metric_points(metric_reader, "socratiq.section_planner.plan_total")
        assert any(dict(p.attributes).get("tier_used") == "windowed" for p in plan_total)
        bucket_hist = _metric_points(
            metric_reader, "socratiq.section_planner.bucket_count"
        )
        assert any(dict(p.attributes).get("tier_used") == "windowed" for p in bucket_hist)

    def test_fallback_tier_visible_via_metric(
        self,
        tracer: OtelTracer,
        otel_providers,
    ) -> None:
        # Layer 3/4 don't go through runtime.call, so this event is the
        # only signal that degradation happened. Verify it makes it through.
        _, metric_reader = otel_providers
        tracer.emit(
            "section_planner.plan_finalized",
            phase="section_planner.plan",
            tier_used="fallback",
            bucket_count=8,
            short_circuit=False,
            error="llm_error:LLMProviderError",
            elapsed_ms=10.0,
        )
        points = _metric_points(metric_reader, "socratiq.section_planner.plan_total")
        fallback = [p for p in points if dict(p.attributes).get("tier_used") == "fallback"]
        assert fallback, "fallback tier missing from plan_total counter"
        assert dict(fallback[0].attributes).get("has_error") == "true"


# --- course_generation.course_finalized -----------------------------------


class TestCourseGenerationFinalized:
    def test_emits_span_and_outcome_counters(
        self,
        tracer: OtelTracer,
        otel_providers,
    ) -> None:
        span_exporter, metric_reader = otel_providers
        tracer.emit(
            "course_generation.course_finalized",
            phase="course_generation.finalize",
            course_id="course-1",
            source_count=2,
            section_count=12,
            lesson_ok=10,
            lesson_failed=2,
            lab_ok=4,
            lab_skipped=6,
            lab_failed=0,
            elapsed_ms=180_000.0,
            status="partial",
        )
        spans = _spans_named(span_exporter, "course_generation.finalize")
        assert len(spans) == 1
        attrs = dict(spans[0].attributes or {})
        assert attrs["socratiq.course_id"] == "course-1"
        assert attrs["socratiq.course_generation.section_count"] == 12

        outcome = _metric_points(metric_reader, "socratiq.course_generation.lesson.outcome_total")
        by_status = {dict(p.attributes).get("status"): p.value for p in outcome}
        assert by_status.get("ok") == 10
        assert by_status.get("failed") == 2


# --- async-context propagation --------------------------------------------


class TestAsyncContext:
    async def test_parallel_phases_in_gather_are_independent_siblings(
        self,
        tracer: OtelTracer,
        otel_providers,
    ) -> None:
        span_exporter, _ = otel_providers

        async def _windowed(idx: int) -> None:
            phase = f"section_planner.layer2.window[{idx}/3]"
            tracer.emit("phase_start", phase=phase)
            await asyncio.sleep(0)
            tracer.emit("phase_end", phase=phase, status="ok", elapsed_ms=1.0)

        await asyncio.gather(_windowed(1), _windowed(2), _windowed(3))

        names = sorted(s.name for s in span_exporter.get_finished_spans() if s.name.startswith("section_planner.layer2"))
        assert names == [
            "section_planner.layer2.window[1/3]",
            "section_planner.layer2.window[2/3]",
            "section_planner.layer2.window[3/3]",
        ]


# --- unknown events fall through ------------------------------------------


class TestUnknownEvent:
    def test_unknown_event_under_active_span_is_recorded_as_span_event(
        self,
        tracer: OtelTracer,
        otel_providers,
    ) -> None:
        span_exporter, _ = otel_providers
        tracer.emit("phase_start", phase="t.future")
        # Pretend the runtime added a new event we don't have a handler for.
        tracer.emit("hypothetical_future_event", phase="t.future", whatever=1)
        tracer.emit("phase_end", phase="t.future", status="ok", elapsed_ms=1.0)

        spans = _spans_named(span_exporter, "t.future")
        names = [e.name for e in spans[0].events]
        assert "hypothetical_future_event" in names
