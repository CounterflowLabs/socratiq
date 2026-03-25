"""Tests for YouTube extractor."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.tools.extractors.youtube import YouTubeExtractor
from app.tools.extractors.base import ExtractionError

class TestParseVideoId:
    def test_standard_url(self):
        ext = YouTubeExtractor()
        assert ext._parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self):
        ext = YouTubeExtractor()
        assert ext._parse_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_url_with_params(self):
        ext = YouTubeExtractor()
        assert ext._parse_video_id("https://youtube.com/watch?v=abc123defgh&t=120") == "abc123defgh"

    def test_invalid_url_raises(self):
        ext = YouTubeExtractor()
        with pytest.raises(ExtractionError):
            ext._parse_video_id("https://example.com/not-youtube")

class TestFetchMetadata:
    @pytest.mark.asyncio
    async def test_metadata_via_ytdlp(self):
        ext = YouTubeExtractor()
        import json
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(
            json.dumps({"title": "Test Video", "uploader": "Test Author", "duration": 600, "language": "en"}).encode(), b""
        ))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            meta = await ext._fetch_metadata("dQw4w9WgXcQ")
        assert meta["title"] == "Test Video"
        assert meta["duration"] == 600

class TestExtract:
    @pytest.mark.asyncio
    async def test_with_transcript(self):
        ext = YouTubeExtractor()
        with patch.object(ext, "_fetch_metadata", return_value={
            "title": "Test", "uploader": "Author", "duration": 120, "language": "en",
        }):
            with patch.object(ext, "_fetch_transcript", return_value=[
                {"text": "Hello", "start": 0.0, "duration": 2.0},
                {"text": "World", "start": 2.0, "duration": 2.0},
            ]):
                result = await ext.extract("https://youtube.com/watch?v=test1234567")
        assert result.title == "Test"
        assert len(result.chunks) >= 1
        assert result.metadata["platform"] == "youtube"
        assert result.metadata["subtitle_source"] == "transcript_api"

    @pytest.mark.asyncio
    async def test_whisper_fallback(self):
        ext = YouTubeExtractor(whisper_mode="api")
        with patch.object(ext, "_fetch_metadata", return_value={
            "title": "No Subs", "uploader": "A", "duration": 60, "language": "en",
        }):
            with patch.object(ext, "_fetch_transcript", side_effect=Exception("No transcript")):
                with patch("app.tools.extractors.youtube.WhisperService") as MockWhisper:
                    mock_ws = AsyncMock()
                    mock_ws.transcribe = AsyncMock(return_value=[
                        {"text": "Whisper text", "start": 0.0, "end": 5.0},
                    ])
                    MockWhisper.return_value = mock_ws
                    result = await ext.extract("https://youtube.com/watch?v=test1234567")
        assert result.metadata["subtitle_source"] == "whisper"
        assert len(result.chunks) >= 1
