"""Tests for content_key extraction."""

import pytest
from app.services.content_key import extract_content_key


class TestExtractContentKey:
    # --- Bilibili ---
    def test_bilibili_standard_url(self):
        assert extract_content_key("bilibili", url="https://www.bilibili.com/video/BV1gZ4y1F7hS") == "bilibili:BV1gZ4y1F7hS"

    def test_bilibili_short_url(self):
        assert extract_content_key("bilibili", url="https://b23.tv/BV1gZ4y1F7hS") == "bilibili:BV1gZ4y1F7hS"

    def test_bilibili_with_query_params(self):
        assert extract_content_key("bilibili", url="https://www.bilibili.com/video/BV1gZ4y1F7hS?p=1&t=30") == "bilibili:BV1gZ4y1F7hS"

    def test_bilibili_invalid_url(self):
        assert extract_content_key("bilibili", url="https://www.bilibili.com/some/other/page") is None

    # --- YouTube ---
    def test_youtube_standard_url(self):
        assert extract_content_key("youtube", url="https://www.youtube.com/watch?v=kCc8FmEb1nY") == "youtube:kCc8FmEb1nY"

    def test_youtube_short_url(self):
        assert extract_content_key("youtube", url="https://youtu.be/kCc8FmEb1nY") == "youtube:kCc8FmEb1nY"

    def test_youtube_with_extra_params(self):
        assert extract_content_key("youtube", url="https://www.youtube.com/watch?v=kCc8FmEb1nY&list=PLxxx&t=120") == "youtube:kCc8FmEb1nY"

    def test_youtube_invalid_url(self):
        assert extract_content_key("youtube", url="https://www.youtube.com/channel/UCxxx") is None

    # --- PDF ---
    def test_pdf_md5(self):
        content = b"hello world pdf content"
        result = extract_content_key("pdf", file_content=content)
        assert result is not None
        assert result.startswith("pdf:")
        assert len(result) == 4 + 32  # "pdf:" + 32-char md5 hex

    def test_pdf_same_content_same_key(self):
        content = b"identical content"
        key1 = extract_content_key("pdf", file_content=content)
        key2 = extract_content_key("pdf", file_content=content)
        assert key1 == key2

    def test_pdf_different_content_different_key(self):
        key1 = extract_content_key("pdf", file_content=b"content A")
        key2 = extract_content_key("pdf", file_content=b"content B")
        assert key1 != key2

    # --- Edge cases ---
    def test_unknown_type(self):
        assert extract_content_key("markdown", url="https://example.com") is None

    def test_no_url_no_file(self):
        assert extract_content_key("bilibili") is None

    # --- content_key_hash ---
    def test_content_key_hash(self):
        from app.services.content_key import content_key_hash
        h = content_key_hash("bilibili:BV1gZ4y1F7hS")
        assert isinstance(h, str)
        assert len(h) == 16
