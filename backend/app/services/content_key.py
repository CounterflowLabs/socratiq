"""Content key extraction for source deduplication."""

import hashlib
import re


def extract_content_key(
    source_type: str,
    url: str | None = None,
    file_content: bytes | None = None,
) -> str | None:
    """Extract a unique content key for deduplication.

    Returns a string like "bilibili:BV1gZ4y1F7hS", "youtube:kCc8FmEb1nY",
    or "pdf:a1b2c3d4..." — or None if extraction fails.
    """
    if source_type == "bilibili" and url:
        match = re.search(r"(BV[a-zA-Z0-9]{10})", url)
        return f"bilibili:{match.group(1)}" if match else None

    elif source_type == "youtube" and url:
        match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
        return f"youtube:{match.group(1)}" if match else None

    elif source_type == "pdf" and file_content:
        md5 = hashlib.md5(file_content).hexdigest()
        return f"pdf:{md5}"

    return None


def content_key_hash(key: str) -> str:
    """Short hash of a content_key for use in Redis channel names."""
    return hashlib.sha256(key.encode()).hexdigest()[:16]
