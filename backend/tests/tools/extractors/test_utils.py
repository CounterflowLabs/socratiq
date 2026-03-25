"""Tests for shared segment grouping utility."""
import pytest
from app.tools.extractors.utils import group_segments

class TestGroupSegments:
    def test_youtube_format(self):
        segments = [
            {"text": "Hello world", "start": 0.0, "duration": 2.5},
            {"text": "This is a test", "start": 2.5, "duration": 3.0},
            {"text": "Next window", "start": 65.0, "duration": 2.0},
        ]
        chunks = group_segments(segments, "youtube", "https://youtube.com/watch?v=x", window_seconds=60)
        assert len(chunks) == 2
        assert "Hello world" in chunks[0].raw_text
        assert "Next window" in chunks[1].raw_text
        assert chunks[0].metadata["start_time"] == 0.0
        assert chunks[0].source_type == "youtube"

    def test_bilibili_format(self):
        segments = [
            {"content": "你好", "from": 0.0, "to": 2.0},
            {"content": "世界", "from": 2.0, "to": 4.0},
        ]
        chunks = group_segments(segments, "bilibili", "https://bilibili.com/video/BV1x", window_seconds=60)
        assert len(chunks) == 1
        assert "你好" in chunks[0].raw_text

    def test_whisper_format(self):
        segments = [{"text": "Transcribed text", "start": 0.0, "end": 5.0}]
        chunks = group_segments(segments, "youtube", "https://youtube.com/watch?v=x")
        assert len(chunks) == 1

    def test_empty_segments(self):
        assert group_segments([], "youtube", "https://youtube.com/watch?v=x") == []

    def test_blank_segments_filtered(self):
        segments = [
            {"text": "", "start": 0.0, "duration": 1.0},
            {"text": "  ", "start": 1.0, "duration": 1.0},
            {"text": "Real text", "start": 2.0, "duration": 1.0},
        ]
        chunks = group_segments(segments, "youtube", "https://youtube.com/watch?v=x")
        assert len(chunks) == 1
        assert "Real text" in chunks[0].raw_text

    def test_media_url_set(self):
        segments = [{"text": "hi", "start": 0.0, "duration": 1.0}]
        chunks = group_segments(segments, "youtube", "https://yt.com/x")
        assert chunks[0].media_url == "https://yt.com/x"
