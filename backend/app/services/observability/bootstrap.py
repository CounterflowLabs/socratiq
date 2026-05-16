"""init_otel — opt-in OpenTelemetry bootstrap.

Call once at process startup (FastAPI ``app/main.py`` and Celery
``app/worker/celery_app.py``). No-op when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is
unset, so dev and tests keep the default ``LoggingTracer`` from
``app.services.llm.runtime``.

Ordering constraint
-------------------

``AgentRuntime.__init__`` snapshots the process-wide default tracer into
``self._tracer``. Same for ``MentorAgent``. ``init_otel()`` must run BEFORE
the first service constructs an AgentRuntime — in practice this means
calling it at module-load time in both entrypoints (top of ``main.py`` and
``celery_app.py``), well before any route handler or Celery task creates a
``SectionPlanner`` / ``ContentAnalyzer`` / ``LessonGenerator`` /
``LabGenerator`` / ``MentorAgent`` instance.
"""

from __future__ import annotations

import logging
import os
from typing import Final

logger = logging.getLogger(__name__)

# Module-level flag — keeps init_otel() idempotent across hot-reload (uvicorn
# --reload re-imports modules) and across the FastAPI + Celery startup path
# inside a single process (e.g. a developer running both in the same shell).
_INSTALLED: bool = False

_ENV_ENDPOINT: Final[str] = "OTEL_EXPORTER_OTLP_ENDPOINT"


def init_otel(*, service_name: str | None = None) -> None:
    """Install OTel TracerProvider + MeterProvider, swap default tracer.

    Args:
        service_name: Optional explicit service name. Falls back to the
            ``OTEL_SERVICE_NAME`` env var, then to ``socratiq-backend``.
            Use ``socratiq-worker`` from celery_app.py to keep the two
            entrypoints distinguishable in Tempo / Grafana.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    endpoint = os.getenv(_ENV_ENDPOINT, "").strip()
    if not endpoint:
        logger.debug("otel.init skipped: %s unset", _ENV_ENDPOINT)
        return

    try:
        _install(service_name=service_name or os.getenv("OTEL_SERVICE_NAME") or "socratiq-backend")
    except Exception:  # noqa: BLE001
        # Tracing is observability — never crash the app because the
        # exporter / SDK init failed.
        logger.exception("otel.init failed; falling back to LoggingTracer")
        return

    _INSTALLED = True
    logger.info("otel.init endpoint=%s service=%s", endpoint, service_name or "socratiq-backend")


def _install(*, service_name: str) -> None:
    """The actual SDK wiring — separated for catchable exception scope.

    Imports happen lazily so the OTel packages are only loaded in the
    branch where they're actually used. This keeps `from app.services.
    observability.bootstrap import init_otel` cheap even when the env var
    is unset.
    """
    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": _read_version(),
            "deployment.environment": os.getenv("ENVIRONMENT", "dev"),
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(),
                export_interval_millis=15_000,  # 15s — matches typical Prom scrape
            )
        ],
    )
    metrics.set_meter_provider(meter_provider)

    _install_auto_instrumentations()

    # Swap the runtime's default tracer LAST — only after the SDK is fully
    # configured. Otherwise a stray emit during startup could land on a
    # half-built provider.
    from app.services.llm.runtime import set_default_tracer
    from app.services.observability.otel_tracer import OtelTracer

    set_default_tracer(OtelTracer())


def _install_auto_instrumentations() -> None:
    """Best-effort auto-instrumentation.

    Each instrumentation is wrapped individually so a single missing /
    incompatible package doesn't disable the rest. The instrumentation
    libraries are listed in pyproject.toml; we don't gate on import errors
    here, just on installer exceptions.
    """
    # FastAPI — instrumented per-app in main.py (needs the app instance).
    # Done there to keep this module FastAPI-agnostic (Celery doesn't have one).

    # asyncpg — driver-level instrumentation; safe to call once globally.
    try:
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor

        AsyncPGInstrumentor().instrument()
    except Exception:  # noqa: BLE001
        logger.exception("otel.init: asyncpg instrumentation failed")

    # Celery — must run before workers register tasks; we'll re-import this
    # from celery_app.py too, but the call is idempotent.
    try:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor

        CeleryInstrumentor().instrument()
    except Exception:  # noqa: BLE001
        logger.exception("otel.init: celery instrumentation failed")

    # httpx — covers outbound LLM HTTP traffic (Anthropic, OpenAI-compat).
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception:  # noqa: BLE001
        logger.exception("otel.init: httpx instrumentation failed")


def instrument_fastapi(app) -> None:  # noqa: ANN001 — FastAPI type avoided to keep this module light
    """Per-app FastAPI instrumentation. Safe to call when OTel is uninstalled —
    falls back to no-op if the instrumentor import or apply fails.

    Call from ``app/main.py`` AFTER ``init_otel()`` and AFTER routes are
    added (instrumentation reads ``app.routes`` to build URL templates).
    """
    if not _INSTALLED:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception:  # noqa: BLE001
        logger.exception("otel.init: fastapi instrumentation failed")


def _read_version() -> str:
    """Best-effort service.version. Avoid hard-coding; pyproject is the truth."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("socratiq-backend")
    except PackageNotFoundError:
        return "0.0.0"
    except Exception:  # noqa: BLE001
        return "0.0.0"


__all__ = ["init_otel", "instrument_fastapi"]
