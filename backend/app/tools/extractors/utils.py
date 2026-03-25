"""Shared utilities for content extractors."""
from app.tools.extractors.base import RawContentChunk

def group_segments(
    segments: list[dict], source_type: str, media_url: str, window_seconds: int = 60,
) -> list[RawContentChunk]:
    """Group timed subtitle/transcript segments into time-windowed chunks.
    Handles YouTube (text/start/duration), Bilibili (content/from/to), Whisper (text/start/end).
    """
    if not segments:
        return []
    normalized = []
    for seg in segments:
        text = (seg.get("text") or seg.get("content", "")).strip()
        if not text:
            continue
        start = seg.get("start") if "start" in seg else seg.get("from", 0.0)
        end = seg.get("end") or seg.get("to") or (start + seg.get("duration", 0.0))
        normalized.append({"text": text, "start": float(start), "end": float(end)})
    if not normalized:
        return []
    chunks: list[RawContentChunk] = []
    current_texts: list[str] = []
    window_start = normalized[0]["start"]
    for seg in normalized:
        if seg["start"] - window_start >= window_seconds and current_texts:
            chunks.append(RawContentChunk(
                source_type=source_type, raw_text="\n".join(current_texts),
                metadata={"start_time": window_start, "end_time": seg["start"]}, media_url=media_url,
            ))
            current_texts = []
            window_start = seg["start"]
        current_texts.append(seg["text"])
    if current_texts:
        chunks.append(RawContentChunk(
            source_type=source_type, raw_text="\n".join(current_texts),
            metadata={"start_time": window_start, "end_time": normalized[-1]["end"]}, media_url=media_url,
        ))
    return chunks
