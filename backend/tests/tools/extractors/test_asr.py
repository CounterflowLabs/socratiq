"""Tests for Whisper ASR service."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from app.tools.extractors.asr import WhisperService

class TestWhisperDownloadAudio:
    @pytest.mark.asyncio
    async def test_download_calls_ytdlp(self):
        service = WhisperService(mode="api")
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            with patch("pathlib.Path.exists", return_value=True):
                await service._download_audio("https://youtube.com/watch?v=test")
                mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_failure_raises(self):
        service = WhisperService(mode="api")
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Download failed"))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(RuntimeError, match="yt-dlp"):
                await service._download_audio("https://youtube.com/watch?v=bad")

class TestWhisperTranscribeAPI:
    @pytest.mark.asyncio
    async def test_api_mode(self):
        service = WhisperService(mode="api")
        mock_response = MagicMock()
        mock_response.segments = [
            MagicMock(text="Hello world", start=0.0, end=2.5),
            MagicMock(text="Second segment", start=2.5, end=5.0),
        ]
        with patch.object(service, "_download_audio", return_value=Path("/tmp/test.wav")):
            with patch("openai.AsyncOpenAI") as MockClient:
                mock_client = AsyncMock()
                mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)
                MockClient.return_value = mock_client
                with patch("pathlib.Path.unlink"):
                    segments = await service.transcribe("https://youtube.com/watch?v=test")
        assert len(segments) == 2
        assert segments[0]["text"] == "Hello world"
        assert segments[0]["start"] == 0.0

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
