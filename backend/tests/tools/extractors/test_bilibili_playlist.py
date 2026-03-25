"""Tests for Bilibili playlist (合集) multi-page extraction."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.tools.extractors.bilibili import BilibiliExtractor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_subtitle_data(texts: list[str]) -> dict:
    """Build a minimal Bilibili subtitle JSON body."""
    body = [
        {"content": t, "from": float(i * 10), "to": float(i * 10 + 9)}
        for i, t in enumerate(texts)
    ]
    return {"body": body}


def _make_info(pages: list[dict], title: str = "Test Video") -> dict:
    """Build a minimal bilibili_api get_info() response."""
    return {
        "title": title,
        "duration": len(pages) * 300,
        "pages": pages,
        "owner": {"name": "TestAuthor"},
        "cid": pages[0]["cid"] if pages else 12345,
    }


SINGLE_PAGE = [{"cid": 1001, "part": "intro"}]
THREE_PAGES = [
    {"cid": 2001, "part": "Part 1 - Basics"},
    {"cid": 2002, "part": "Part 2 - Advanced"},
    {"cid": 2003, "part": "Part 3 - Summary"},
]
TWO_PAGES = [
    {"cid": 3001, "part": "Chapter 1"},
    {"cid": 3002, "part": "Chapter 2"},
]


def _mock_subtitle_response(texts: list[str]):
    """Return an AsyncMock get_subtitle that yields a subtitle list."""
    subtitle_data = _make_subtitle_data(texts)
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=subtitle_data)

    get_subtitle_return = {"subtitles": [{"lan": "zh-CN", "subtitle_url": "//example.com/sub.json"}]}
    return get_subtitle_return, mock_resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBilibiliPlaylist:

    @pytest.mark.asyncio
    async def test_single_page_still_works(self):
        """Single-page video should work as before (no page_index in chunks)."""
        ext = BilibiliExtractor()
        sub_info, mock_http_resp = _mock_subtitle_response(["Hello world", "Bilibili test"])

        mock_video = AsyncMock()
        mock_video.get_info = AsyncMock(return_value=_make_info(SINGLE_PAGE, "Single Page Video"))
        mock_video.get_subtitle = AsyncMock(return_value=sub_info)

        with patch("app.tools.extractors.bilibili.video.Video", return_value=mock_video):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = AsyncMock(return_value=mock_http_resp)
                mock_client_cls.return_value = mock_client

                result = await ext.extract("https://www.bilibili.com/video/BV1xx411c7XW")

        assert result.title == "Single Page Video"
        assert len(result.chunks) >= 1
        assert result.metadata["platform"] == "bilibili"
        assert result.metadata["is_playlist"] is False
        assert result.metadata["page_count"] == 1
        # Single-page: legacy page key should be present
        assert result.metadata["page"] == 0
        # Chunks should NOT have page_index for single-page videos
        for chunk in result.chunks:
            assert "page_index" not in chunk.metadata

    @pytest.mark.asyncio
    async def test_multi_page_extracts_all(self):
        """Multi-page video should extract all pages and tag chunks."""
        ext = BilibiliExtractor()

        sub_info, mock_http_resp = _mock_subtitle_response(["Content line"])

        mock_video = AsyncMock()
        mock_video.get_info = AsyncMock(return_value=_make_info(THREE_PAGES, "Three Part Series"))
        mock_video.get_subtitle = AsyncMock(return_value=sub_info)

        with patch("app.tools.extractors.bilibili.video.Video", return_value=mock_video):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = AsyncMock(return_value=mock_http_resp)
                mock_client_cls.return_value = mock_client

                result = await ext.extract("https://www.bilibili.com/video/BV1xx411c7XW")

        # get_subtitle should have been called once per page
        assert mock_video.get_subtitle.call_count == 3

        # All chunks should have page_index and page_title
        page_indices_seen = set()
        for chunk in result.chunks:
            assert "page_index" in chunk.metadata, f"Chunk missing page_index: {chunk.metadata}"
            assert "page_title" in chunk.metadata, f"Chunk missing page_title: {chunk.metadata}"
            page_indices_seen.add(chunk.metadata["page_index"])

        # Should have chunks from all 3 pages
        assert page_indices_seen == {0, 1, 2}

        # page_title values should match page "part" names
        page_titles = {c.metadata["page_index"]: c.metadata["page_title"] for c in result.chunks}
        assert page_titles[0] == "Part 1 - Basics"
        assert page_titles[1] == "Part 2 - Advanced"
        assert page_titles[2] == "Part 3 - Summary"

    @pytest.mark.asyncio
    async def test_playlist_metadata(self):
        """Playlist ExtractionResult metadata should have is_playlist=True, page_count, pages list."""
        ext = BilibiliExtractor()
        sub_info, mock_http_resp = _mock_subtitle_response(["Line A", "Line B"])

        mock_video = AsyncMock()
        mock_video.get_info = AsyncMock(return_value=_make_info(TWO_PAGES, "Two-Chapter Course"))
        mock_video.get_subtitle = AsyncMock(return_value=sub_info)

        with patch("app.tools.extractors.bilibili.video.Video", return_value=mock_video):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = AsyncMock(return_value=mock_http_resp)
                mock_client_cls.return_value = mock_client

                result = await ext.extract("https://www.bilibili.com/video/BV1xx411c7XW")

        meta = result.metadata
        assert meta["is_playlist"] is True
        assert meta["page_count"] == 2
        assert isinstance(meta["pages"], list)
        assert len(meta["pages"]) == 2

        page_0 = meta["pages"][0]
        assert page_0["index"] == 0
        assert page_0["title"] == "Chapter 1"
        assert page_0["cid"] == 3001

        page_1 = meta["pages"][1]
        assert page_1["index"] == 1
        assert page_1["title"] == "Chapter 2"
        assert page_1["cid"] == 3002

    @pytest.mark.asyncio
    async def test_explicit_page_kwarg_limits_to_single_page(self):
        """Passing page= kwarg on a multi-page video should only extract that page."""
        ext = BilibiliExtractor()
        sub_info, mock_http_resp = _mock_subtitle_response(["Page one content"])

        mock_video = AsyncMock()
        mock_video.get_info = AsyncMock(return_value=_make_info(THREE_PAGES))
        mock_video.get_subtitle = AsyncMock(return_value=sub_info)

        with patch("app.tools.extractors.bilibili.video.Video", return_value=mock_video):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = AsyncMock(return_value=mock_http_resp)
                mock_client_cls.return_value = mock_client

                result = await ext.extract(
                    "https://www.bilibili.com/video/BV1xx411c7XW", page=1
                )

        # Only one page extracted
        assert mock_video.get_subtitle.call_count == 1
        assert result.metadata["page"] == 1
        assert result.metadata["cid"] == 2002

    @pytest.mark.asyncio
    async def test_whisper_fallback_on_playlist_page(self):
        """When a playlist page has no subtitles, Whisper should be used for that page."""
        ext = BilibiliExtractor(whisper_mode="api")

        mock_video = AsyncMock()
        mock_video.get_info = AsyncMock(return_value=_make_info(TWO_PAGES, "ASR Video"))
        # No subtitles on any page
        mock_video.get_subtitle = AsyncMock(return_value={"subtitles": []})

        with patch("app.tools.extractors.bilibili.video.Video", return_value=mock_video):
            with patch("app.tools.extractors.asr.WhisperService") as MockWhisper:
                mock_ws = AsyncMock()
                mock_ws.transcribe = AsyncMock(
                    return_value=[{"text": "Whisper text", "start": 0.0, "end": 5.0}]
                )
                MockWhisper.return_value = mock_ws

                result = await ext.extract("https://www.bilibili.com/video/BV1xx411c7XW")

        # Whisper called once per page (2 pages)
        assert mock_ws.transcribe.call_count == 2
        assert result.metadata["subtitle_source"] == "whisper"
        assert result.metadata["is_playlist"] is True
