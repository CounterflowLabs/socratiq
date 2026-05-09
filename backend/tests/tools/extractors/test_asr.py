"""Tests for Whisper ASR service."""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.tools.extractors.asr import WhisperService


def _verbose_json(segments: list[dict]) -> dict:
    return {
        "task": "transcribe",
        "language": "english",
        "duration": 5.0,
        "text": " ".join(s["text"] for s in segments),
        "segments": segments,
    }


def _mock_transport(response_factory):
    """httpx.MockTransport that captures the last request and returns a stub."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return response_factory(request)

    return httpx.MockTransport(handler), captured


class TestWhisperDownloadAudio:
    @pytest.mark.asyncio
    async def test_download_calls_ytdlp(self):
        service = WhisperService(mode="openai_compat")
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            with patch("pathlib.Path.exists", return_value=True):
                await service._download_audio("https://youtube.com/watch?v=test")
                mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_failure_raises(self):
        service = WhisperService(mode="openai_compat")
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Download failed"))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(RuntimeError, match="yt-dlp"):
                await service._download_audio("https://youtube.com/watch?v=bad")


class TestWhisperRemoteTranscribe:
    """Cover the httpx-based remote transcribe path for both protocols."""

    @pytest.mark.asyncio
    async def test_openai_compat_posts_to_audio_transcriptions_with_bearer(self, tmp_path):
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"fake mp3")

        service = WhisperService(
            mode="openai_compat",
            api_key="sk-test",
            api_base_url="https://api.groq.com/openai/v1",
            api_model="whisper-large-v3",
        )

        body = _verbose_json([
            {"text": " Hello world", "start": 0.0, "end": 2.5},
            {"text": " Second", "start": 2.5, "end": 5.0},
        ])
        transport, captured = _mock_transport(
            lambda req: httpx.Response(200, json=body)
        )

        original_client = httpx.AsyncClient
        with patch("httpx.AsyncClient", lambda *a, **kw: original_client(transport=transport)):
            segments, cleanup = await service._transcribe_remote(audio)

        assert cleanup == []
        assert len(segments) == 2
        assert segments[0] == {"text": "Hello world", "start": 0.0, "end": 2.5}

        req = captured["request"]
        assert str(req.url) == "https://api.groq.com/openai/v1/audio/transcriptions"
        assert req.headers["authorization"] == "Bearer sk-test"
        # multipart form contains the model name
        body_bytes = req.read()
        assert b"whisper-large-v3" in body_bytes
        assert b"verbose_json" in body_bytes

    @pytest.mark.asyncio
    async def test_whispercpp_posts_to_inference_without_auth(self, tmp_path):
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"fake mp3")

        service = WhisperService(
            mode="whispercpp",
            api_base_url="http://host.docker.internal:8001",
            api_key="",  # no auth needed
        )

        body = _verbose_json([
            {"text": " Local one", "start": 0.0, "end": 1.5},
        ])
        transport, captured = _mock_transport(
            lambda req: httpx.Response(200, json=body)
        )

        original_client = httpx.AsyncClient
        with patch("httpx.AsyncClient", lambda *a, **kw: original_client(transport=transport)):
            segments, cleanup = await service._transcribe_remote(audio)

        assert cleanup == []
        assert len(segments) == 1
        assert segments[0]["text"] == "Local one"

        req = captured["request"]
        assert str(req.url) == "http://host.docker.internal:8001/inference"
        assert "authorization" not in {k.lower() for k in req.headers.keys()}

    @pytest.mark.asyncio
    async def test_legacy_api_mode_still_works(self, tmp_path):
        """Existing rows with mode='api' continue to behave as openai-compat."""
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"fake mp3")

        service = WhisperService(
            mode="api",
            api_key="sk-legacy",
            api_base_url="https://api.openai.com/v1",
            api_model="whisper-1",
        )

        transport, captured = _mock_transport(
            lambda req: httpx.Response(200, json=_verbose_json([]))
        )

        original_client = httpx.AsyncClient
        with patch("httpx.AsyncClient", lambda *a, **kw: original_client(transport=transport)):
            await service._transcribe_remote(audio)

        assert str(captured["request"].url) == "https://api.openai.com/v1/audio/transcriptions"

    @pytest.mark.asyncio
    async def test_openai_compat_without_api_key_raises(self, tmp_path):
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"fake")
        service = WhisperService(
            mode="openai_compat",
            api_key="",
            api_base_url="https://api.groq.com/openai/v1",
        )
        with pytest.raises(RuntimeError, match="API 未配置"):
            await service._transcribe_remote(audio)

    @pytest.mark.asyncio
    async def test_413_raises_friendly_error(self, tmp_path):
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"fake")
        service = WhisperService(
            mode="openai_compat",
            api_key="sk-test",
            api_base_url="https://api.groq.com/openai/v1",
        )
        transport, _ = _mock_transport(lambda req: httpx.Response(413))
        original_client = httpx.AsyncClient
        with patch("httpx.AsyncClient", lambda *a, **kw: original_client(transport=transport)):
            with pytest.raises(RuntimeError, match="过大"):
                await service._transcribe_remote(audio)


class TestWhisperTranscribeLocal:
    @pytest.mark.asyncio
    async def test_local_mode(self):
        service = WhisperService(mode="local", model="base")
        mock_result = {"segments": [{"text": "Local transcription", "start": 0.0, "end": 3.0}]}
        with patch.object(service, "_download_audio", return_value=Path("/tmp/test.wav")):
            with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=mock_result):
                with patch("pathlib.Path.unlink"):
                    segments = await service.transcribe("https://youtube.com/watch?v=test")
        assert len(segments) == 1
        assert segments[0]["text"] == "Local transcription"
