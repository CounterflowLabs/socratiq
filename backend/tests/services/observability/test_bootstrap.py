"""Unit tests for ``bootstrap.init_otel`` — env gating and idempotency."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.llm.runtime import LoggingTracer, get_default_tracer
from app.services.observability import bootstrap


@pytest.fixture(autouse=True)
def reset_installed_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with bootstrap considered uninstalled.

    The module-level flag persists across tests in the same process; we
    flip it back so behavior is deterministic regardless of ordering.
    """
    monkeypatch.setattr(bootstrap, "_INSTALLED", False)


class TestEnvGating:
    def test_unset_env_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        # Reset the runtime default to a fresh LoggingTracer instance so the
        # post-condition is easy to assert.
        from app.services.llm.runtime import set_default_tracer

        sentinel = LoggingTracer("test.sentinel")
        set_default_tracer(sentinel)

        bootstrap.init_otel()

        assert get_default_tracer() is sentinel
        assert bootstrap._INSTALLED is False

    def test_empty_env_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        bootstrap.init_otel()
        assert bootstrap._INSTALLED is False

    def test_whitespace_only_env_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "   ")
        bootstrap.init_otel()
        assert bootstrap._INSTALLED is False


class TestSuccessfulInstall:
    def test_endpoint_set_calls_install_and_marks_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        with patch.object(bootstrap, "_install") as mock_install:
            bootstrap.init_otel(service_name="test-svc")
        mock_install.assert_called_once()
        assert mock_install.call_args.kwargs["service_name"] == "test-svc"
        assert bootstrap._INSTALLED is True

    def test_service_name_falls_back_to_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        monkeypatch.setenv("OTEL_SERVICE_NAME", "from-env")
        with patch.object(bootstrap, "_install") as mock_install:
            bootstrap.init_otel()
        assert mock_install.call_args.kwargs["service_name"] == "from-env"

    def test_service_name_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
        with patch.object(bootstrap, "_install") as mock_install:
            bootstrap.init_otel()
        assert mock_install.call_args.kwargs["service_name"] == "socratiq-backend"


class TestIdempotency:
    def test_repeat_init_only_installs_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        with patch.object(bootstrap, "_install") as mock_install:
            bootstrap.init_otel()
            bootstrap.init_otel()
            bootstrap.init_otel()
        assert mock_install.call_count == 1


class TestGracefulFailure:
    def test_install_exception_logs_and_keeps_default_tracer(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        from app.services.llm.runtime import set_default_tracer

        sentinel = LoggingTracer("test.sentinel.fail")
        set_default_tracer(sentinel)

        def _boom(**kwargs):
            raise RuntimeError("SDK init blew up")

        with patch.object(bootstrap, "_install", side_effect=_boom):
            bootstrap.init_otel()

        assert bootstrap._INSTALLED is False
        assert get_default_tracer() is sentinel
        assert any(
            "otel.init failed" in record.message for record in caplog.records
        )


class TestInstrumentFastApi:
    def test_no_install_means_instrument_fastapi_is_noop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # When init_otel hasn't run, instrument_fastapi must not touch the app.
        monkeypatch.setattr(bootstrap, "_INSTALLED", False)

        class _FakeApp:
            pass

        # Should not raise and should not import the instrumentor.
        bootstrap.instrument_fastapi(_FakeApp())
