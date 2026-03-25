"""YouTube video subtitle extractor with Whisper ASR fallback."""
import asyncio
import json
import logging
import re
from app.tools.extractors.base import ContentExtractor, ExtractionError, ExtractionResult
from app.tools.extractors.utils import group_segments
from app.tools.extractors.asr import WhisperService

logger = logging.getLogger(__name__)


class YouTubeExtractor(ContentExtractor):
    """Extract subtitles from YouTube videos."""

    def __init__(self, whisper_mode: str = "api", whisper_model: str = "base"):
        self._whisper_mode = whisper_mode
        self._whisper_model = whisper_model

    def supported_source_type(self) -> str:
        return "youtube"

    async def extract(self, source: str, **kwargs) -> ExtractionResult:
        video_id = self._parse_video_id(source)
        url = f"https://www.youtube.com/watch?v={video_id}"
        metadata = await self._fetch_metadata(video_id)
        title = metadata.get("title", f"YouTube video {video_id}")

        subtitle_source = "transcript_api"
        try:
            segments = await self._fetch_transcript(video_id)
            if not segments:
                raise ValueError("Empty transcript")
        except Exception as e:
            logger.info(f"No transcript for {video_id}, falling back to Whisper: {e}")
            whisper = WhisperService(mode=self._whisper_mode, model=self._whisper_model)
            segments = await whisper.transcribe(url)
            subtitle_source = "whisper"

        if not segments:
            raise ExtractionError(
                "Could not extract content from this video.",
                source_type="youtube",
                details={"video_id": video_id},
            )

        chunks = group_segments(
            segments=segments, source_type="youtube", media_url=url, window_seconds=60
        )

        return ExtractionResult(
            title=title,
            chunks=chunks,
            metadata={
                "platform": "youtube",
                "video_id": video_id,
                "title": title,
                "author": metadata.get("uploader", ""),
                "duration": metadata.get("duration", 0),
                "subtitle_source": subtitle_source,
                "subtitle_language": metadata.get("language", ""),
                "media_url": url,
            },
        )

    @staticmethod
    def _parse_video_id(url: str) -> str:
        match = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", url)
        if match:
            return match.group(1)
        match = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", url)
        if match:
            return match.group(1)
        raise ExtractionError(
            f"Cannot parse YouTube video ID from URL: {url}",
            source_type="youtube",
            details={"url": url},
        )

    @staticmethod
    async def _fetch_metadata(video_id: str) -> dict:
        url = f"https://www.youtube.com/watch?v={video_id}"
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp", "--dump-json", "--no-download", "--no-playlist", url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(f"yt-dlp metadata failed for {video_id}: {stderr.decode()[:200]}")
            return {"title": f"YouTube video {video_id}"}
        try:
            return json.loads(stdout.decode())
        except json.JSONDecodeError:
            return {"title": f"YouTube video {video_id}"}

    @staticmethod
    async def _fetch_transcript(video_id: str) -> list[dict]:
        from youtube_transcript_api import YouTubeTranscriptApi

        def _get():
            return YouTubeTranscriptApi.get_transcript(video_id)

        return await asyncio.to_thread(_get)
