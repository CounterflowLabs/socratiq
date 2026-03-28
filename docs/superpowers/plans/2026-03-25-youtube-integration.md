# YouTube Integration + Unified ASR Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add YouTube as a content source with Whisper ASR fallback, and upgrade Bilibili extractor to share the same fallback.

**Architecture:** Extract shared segment grouping logic into `utils.py`, create a `WhisperService` in `asr.py` (supports API + local mode), build `YouTubeExtractor` using `youtube-transcript-api` + yt-dlp, and refactor `BilibiliExtractor` to use the shared modules. Wire into existing ingestion pipeline and add YouTube tab to frontend.

**Tech Stack:** youtube-transcript-api, yt-dlp, openai SDK (Whisper API), openai-whisper (optional local)

---

### Task 1: Extract shared segment grouping utility

**Files:**
- Create: `backend/app/tools/extractors/utils.py`
- Test: `backend/tests/tools/extractors/test_utils.py`

- [ ] **Step 1: Create test directory structure**

```bash
cd /Users/tulip/Documents/Claude/Projects/LLMs/socratiq/backend
mkdir -p tests/tools/extractors
touch tests/tools/__init__.py tests/tools/extractors/__init__.py
```

- [ ] **Step 2: Write failing tests for group_segments**

File: `tests/tools/extractors/test_utils.py`

```python
"""Tests for shared segment grouping utility."""

import pytest
from app.tools.extractors.utils import group_segments


class TestGroupSegments:
    def test_youtube_format(self):
        """YouTube segments: {"text", "start", "duration"}"""
        segments = [
            {"text": "Hello world", "start": 0.0, "duration": 2.5},
            {"text": "This is a test", "start": 2.5, "duration": 3.0},
            {"text": "Next window", "start": 65.0, "duration": 2.0},
        ]
        chunks = group_segments(segments, "youtube", "https://youtube.com/watch?v=x", window_seconds=60)
        assert len(chunks) == 2
        assert "Hello world" in chunks[0].raw_text
        assert "This is a test" in chunks[0].raw_text
        assert "Next window" in chunks[1].raw_text
        assert chunks[0].metadata["start_time"] == 0.0
        assert chunks[0].source_type == "youtube"

    def test_bilibili_format(self):
        """Bilibili segments: {"content", "from", "to"}"""
        segments = [
            {"content": "你好", "from": 0.0, "to": 2.0},
            {"content": "世界", "from": 2.0, "to": 4.0},
        ]
        chunks = group_segments(segments, "bilibili", "https://bilibili.com/video/BV1x", window_seconds=60)
        assert len(chunks) == 1
        assert "你好" in chunks[0].raw_text
        assert "世界" in chunks[0].raw_text

    def test_whisper_format(self):
        """Whisper segments: {"text", "start", "end"}"""
        segments = [
            {"text": "Transcribed text", "start": 0.0, "end": 5.0},
            {"text": "More text", "start": 5.0, "end": 10.0},
        ]
        chunks = group_segments(segments, "youtube", "https://youtube.com/watch?v=x")
        assert len(chunks) == 1
        assert "Transcribed text" in chunks[0].raw_text

    def test_empty_segments(self):
        chunks = group_segments([], "youtube", "https://youtube.com/watch?v=x")
        assert chunks == []

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
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/tools/extractors/test_utils.py -v
```
Expected: FAIL (module not found)

- [ ] **Step 4: Implement group_segments**

File: `backend/app/tools/extractors/utils.py`

```python
"""Shared utilities for content extractors."""

from app.tools.extractors.base import RawContentChunk


def group_segments(
    segments: list[dict],
    source_type: str,
    media_url: str,
    window_seconds: int = 60,
) -> list[RawContentChunk]:
    """Group timed subtitle/transcript segments into time-windowed chunks.

    Handles multiple input formats:
    - YouTube transcript-api: {"text": str, "start": float, "duration": float}
    - Bilibili subtitle JSON: {"content": str, "from": float, "to": float}
    - Whisper output: {"text": str, "start": float, "end": float}

    All formats are normalized to {"text", "start", "end"} before grouping.

    Args:
        segments: List of timed text segments in any supported format.
        source_type: Source identifier (e.g. "youtube", "bilibili").
        media_url: URL to the original media.
        window_seconds: Target chunk duration in seconds (default 60).

    Returns:
        List of RawContentChunk, each covering approximately window_seconds.
    """
    if not segments:
        return []

    # Normalize all formats to {"text", "start", "end"}
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

    # Group by time window
    chunks: list[RawContentChunk] = []
    current_texts: list[str] = []
    window_start = normalized[0]["start"]

    for seg in normalized:
        if seg["start"] - window_start >= window_seconds and current_texts:
            chunks.append(RawContentChunk(
                source_type=source_type,
                raw_text="\n".join(current_texts),
                metadata={"start_time": window_start, "end_time": seg["start"]},
                media_url=media_url,
            ))
            current_texts = []
            window_start = seg["start"]
        current_texts.append(seg["text"])

    # Flush remaining
    if current_texts:
        chunks.append(RawContentChunk(
            source_type=source_type,
            raw_text="\n".join(current_texts),
            metadata={"start_time": window_start, "end_time": normalized[-1]["end"]},
            media_url=media_url,
        ))

    return chunks
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/tools/extractors/test_utils.py -v
```
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/tools/extractors/utils.py backend/tests/tools/
git commit -m "feat(extractors): add shared segment grouping utility"
```

---

### Task 2: Create WhisperService (ASR fallback)

**Files:**
- Create: `backend/app/tools/extractors/asr.py`
- Test: `backend/tests/tools/extractors/test_asr.py`
- Modify: `backend/app/config.py` (add whisper settings)

- [ ] **Step 1: Add whisper config to Settings**

File: `backend/app/config.py` — add after the `upload_dir` field:

```python
    # Whisper ASR (fallback when no subtitles available)
    whisper_mode: str = "api"        # "api" = OpenAI Whisper API, "local" = local whisper model
    whisper_model: str = "base"      # local model size: tiny/base/small/medium/large
```

- [ ] **Step 2: Write failing tests for WhisperService**

File: `tests/tools/extractors/test_asr.py`

```python
"""Tests for Whisper ASR service."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.tools.extractors.asr import WhisperService


class TestWhisperDownloadAudio:
    @pytest.mark.asyncio
    async def test_download_audio_calls_ytdlp(self):
        service = WhisperService(mode="api")

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            with patch("pathlib.Path.exists", return_value=True):
                path = await service._download_audio("https://youtube.com/watch?v=test")
                # Verify yt-dlp was called
                mock_exec.assert_called_once()
                args = mock_exec.call_args[0]
                assert "yt-dlp" in args[0] or args[0] == "yt-dlp"

    @pytest.mark.asyncio
    async def test_download_audio_failure_raises(self):
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
        assert segments[0]["end"] == 2.5


class TestWhisperTranscribeLocal:
    @pytest.mark.asyncio
    async def test_local_mode(self):
        service = WhisperService(mode="local", model="base")

        mock_result = {
            "segments": [
                {"text": "Local transcription", "start": 0.0, "end": 3.0},
            ]
        }

        with patch.object(service, "_download_audio", return_value=Path("/tmp/test.wav")):
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(return_value=mock_result)
                with patch("pathlib.Path.unlink"):
                    segments = await service.transcribe("https://youtube.com/watch?v=test")

        assert len(segments) == 1
        assert segments[0]["text"] == "Local transcription"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/tools/extractors/test_asr.py -v
```

- [ ] **Step 4: Implement WhisperService**

File: `backend/app/tools/extractors/asr.py`

```python
"""Whisper ASR service — audio-to-text fallback when subtitles are unavailable.

Supports two modes:
- "api": OpenAI Whisper API (fast, $0.006/min)
- "local": Local whisper model via openai-whisper package (free, slower)

Both YouTube and Bilibili audio download is handled by yt-dlp.
"""

import asyncio
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class WhisperService:
    """Audio-to-text transcription via OpenAI Whisper."""

    def __init__(self, mode: str = "api", model: str = "base"):
        """Initialize WhisperService.

        Args:
            mode: "api" for OpenAI Whisper API, "local" for local model.
            model: Local model size (tiny/base/small/medium/large).
                   Ignored when mode="api".
        """
        self._mode = mode
        self._model = model

    async def transcribe(self, url: str) -> list[dict]:
        """Download audio from URL and transcribe to timed segments.

        Args:
            url: Video URL (YouTube or Bilibili — yt-dlp handles both).

        Returns:
            List of {"text": str, "start": float, "end": float}.

        Raises:
            RuntimeError: If download or transcription fails.
        """
        audio_path = await self._download_audio(url)
        try:
            if self._mode == "api":
                return await self._transcribe_api(audio_path)
            else:
                return await self._transcribe_local(audio_path)
        finally:
            audio_path.unlink(missing_ok=True)

    async def _download_audio(self, url: str) -> Path:
        """Download audio via yt-dlp.

        Args:
            url: Video URL.

        Returns:
            Path to downloaded WAV file.

        Raises:
            RuntimeError: If yt-dlp fails.
        """
        tmp_dir = tempfile.mkdtemp(prefix="socratiq_asr_")
        output_path = Path(tmp_dir) / "audio.wav"

        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "-x", "--audio-format", "wav",
            "--audio-quality", "0",
            "--no-playlist",
            "-o", str(output_path),
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(
                f"yt-dlp audio download failed (exit {proc.returncode}): "
                f"{stderr.decode()[:500]}"
            )

        # yt-dlp may add extension, find the actual file
        if not output_path.exists():
            wav_files = list(Path(tmp_dir).glob("audio.*"))
            if wav_files:
                output_path = wav_files[0]
            else:
                raise RuntimeError("yt-dlp produced no output file")

        logger.info(f"Downloaded audio: {output_path} ({output_path.stat().st_size} bytes)")
        return output_path

    async def _transcribe_api(self, audio_path: Path) -> list[dict]:
        """Transcribe via OpenAI Whisper API.

        Uses verbose_json format with segment-level timestamps.
        """
        import openai
        from app.config import get_settings

        settings = get_settings()
        client = openai.AsyncOpenAI(api_key=settings.llm_encryption_key and None)
        # Use the OpenAI API key from model configs if available,
        # otherwise rely on OPENAI_API_KEY env var (openai SDK default)

        with open(audio_path, "rb") as f:
            response = await client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )

        segments = []
        for seg in response.segments or []:
            segments.append({
                "text": seg.text.strip(),
                "start": seg.start,
                "end": seg.end,
            })

        logger.info(f"Whisper API transcribed {len(segments)} segments")
        return segments

    async def _transcribe_local(self, audio_path: Path) -> list[dict]:
        """Transcribe via local whisper model.

        Runs in a thread to avoid blocking the event loop.
        """
        def _run():
            import whisper
            model = whisper.load_model(self._model)
            result = model.transcribe(str(audio_path))
            return result

        result = await asyncio.to_thread(_run)

        segments = []
        for seg in result.get("segments", []):
            segments.append({
                "text": seg["text"].strip(),
                "start": seg["start"],
                "end": seg["end"],
            })

        logger.info(f"Local Whisper transcribed {len(segments)} segments")
        return segments
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python -m pytest tests/tools/extractors/test_asr.py -v
```
Expected: PASS (adjust mocks if needed — the openai client mock may need tweaking based on actual SDK structure)

- [ ] **Step 6: Commit**

```bash
git add backend/app/tools/extractors/asr.py backend/app/config.py backend/tests/tools/extractors/test_asr.py
git commit -m "feat(extractors): add WhisperService with API and local modes"
```

---

### Task 3: Create YouTubeExtractor

**Files:**
- Create: `backend/app/tools/extractors/youtube.py`
- Test: `backend/tests/tools/extractors/test_youtube.py`

- [ ] **Step 1: Write failing tests**

File: `tests/tools/extractors/test_youtube.py`

```python
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
        assert ext._parse_video_id("https://youtube.com/watch?v=abc123&t=120") == "abc123"

    def test_invalid_url_raises(self):
        ext = YouTubeExtractor()
        with pytest.raises(ExtractionError):
            ext._parse_video_id("https://example.com/not-youtube")


class TestFetchMetadata:
    @pytest.mark.asyncio
    async def test_metadata_via_ytdlp(self):
        ext = YouTubeExtractor()
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        import json
        mock_json = json.dumps({
            "title": "Test Video",
            "uploader": "Test Author",
            "duration": 600,
            "language": "en",
        }).encode()
        mock_proc.communicate = AsyncMock(return_value=(mock_json, b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            meta = await ext._fetch_metadata("dQw4w9WgXcQ")

        assert meta["title"] == "Test Video"
        assert meta["uploader"] == "Test Author"
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
                result = await ext.extract("https://youtube.com/watch?v=test")

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

                    result = await ext.extract("https://youtube.com/watch?v=test")

        assert result.metadata["subtitle_source"] == "whisper"
        assert len(result.chunks) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/tools/extractors/test_youtube.py -v
```

- [ ] **Step 3: Implement YouTubeExtractor**

File: `backend/app/tools/extractors/youtube.py`

```python
"""YouTube video subtitle extractor with Whisper ASR fallback."""

import asyncio
import json
import logging
import re

from app.tools.extractors.base import (
    ContentExtractor,
    ExtractionError,
    ExtractionResult,
)
from app.tools.extractors.utils import group_segments

logger = logging.getLogger(__name__)


class YouTubeExtractor(ContentExtractor):
    """Extract subtitles from YouTube videos.

    Strategy:
    1. Fetch metadata via yt-dlp --dump-json
    2. Try youtube-transcript-api for subtitles (auto language detection)
    3. If no subtitles → fall back to yt-dlp audio download + Whisper ASR
    4. Group segments into ~60s time-windowed chunks
    """

    def __init__(self, whisper_mode: str = "api", whisper_model: str = "base"):
        """Initialize YouTubeExtractor.

        Args:
            whisper_mode: "api" for OpenAI Whisper API, "local" for local model.
            whisper_model: Local model size (ignored for API mode).
        """
        self._whisper_mode = whisper_mode
        self._whisper_model = whisper_model

    def supported_source_type(self) -> str:
        return "youtube"

    async def extract(self, source: str, **kwargs) -> ExtractionResult:
        """Extract subtitles from a YouTube video URL.

        Args:
            source: YouTube URL.

        Returns:
            ExtractionResult with subtitle chunks and video metadata.
        """
        video_id = self._parse_video_id(source)
        url = f"https://www.youtube.com/watch?v={video_id}"

        # 1. Metadata
        metadata = await self._fetch_metadata(video_id)
        title = metadata.get("title", f"YouTube video {video_id}")

        # 2. Subtitles: transcript API first, Whisper fallback
        subtitle_source = "transcript_api"
        try:
            segments = await self._fetch_transcript(video_id)
            if not segments:
                raise ValueError("Empty transcript")
        except Exception as e:
            logger.info(f"No transcript for {video_id}, falling back to Whisper: {e}")
            from app.tools.extractors.asr import WhisperService
            whisper = WhisperService(mode=self._whisper_mode, model=self._whisper_model)
            segments = await whisper.transcribe(url)
            subtitle_source = "whisper"

        if not segments:
            raise ExtractionError(
                "Could not extract any content from this video.",
                source_type="youtube",
                details={"video_id": video_id},
            )

        # 3. Group into chunks
        chunks = group_segments(
            segments=segments,
            source_type="youtube",
            media_url=url,
            window_seconds=60,
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
        """Extract video ID from YouTube URL.

        Supports:
        - https://www.youtube.com/watch?v=VIDEO_ID
        - https://youtu.be/VIDEO_ID
        - https://youtube.com/watch?v=VIDEO_ID&t=120
        """
        # youtu.be short URL
        match = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", url)
        if match:
            return match.group(1)

        # youtube.com/watch?v=
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
        """Fetch video metadata via yt-dlp --dump-json."""
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
        """Fetch transcript via youtube-transcript-api.

        Returns list of {"text", "start", "duration"}.
        Raises Exception if no transcript available.
        """
        from youtube_transcript_api import YouTubeTranscriptApi

        # Run in thread since the library is synchronous
        def _get():
            return YouTubeTranscriptApi.get_transcript(video_id)

        return await asyncio.to_thread(_get)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/tools/extractors/test_youtube.py -v
```
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/extractors/youtube.py backend/tests/tools/extractors/test_youtube.py
git commit -m "feat(extractors): add YouTube extractor with Whisper fallback"
```

---

### Task 4: Refactor Bilibili extractor to use shared modules

**Files:**
- Modify: `backend/app/tools/extractors/bilibili.py`

- [ ] **Step 1: Refactor bilibili.py**

Changes:
1. Replace `_group_subtitle_segments` static method with call to `utils.group_segments`
2. Replace `raise ExtractionError("No subtitles")` with Whisper fallback
3. Add `whisper_mode` and `whisper_model` to constructor
4. Update metadata to include unified `platform` and `subtitle_source` fields

Read the full current `bilibili.py`, then apply these changes:

**Constructor** — add whisper params:
```python
def __init__(self, credential: Credential | None = None,
             whisper_mode: str = "api", whisper_model: str = "base"):
    self.credential = credential
    self._whisper_mode = whisper_mode
    self._whisper_model = whisper_model
```

**No subtitles handling** (replace lines 76-82):
```python
        if not subtitles:
            # Fallback: Whisper ASR
            logger.info(f"No subtitles for {bvid}, falling back to Whisper ASR")
            from app.tools.extractors.asr import WhisperService
            whisper = WhisperService(mode=self._whisper_mode, model=self._whisper_model)
            segments = await whisper.transcribe(source)
            subtitle_source = "whisper"

            chunks = group_segments(
                segments=segments,
                source_type="bilibili",
                media_url=f"https://www.bilibili.com/video/{bvid}",
                window_seconds=60,
            )
        else:
            # Existing subtitle fetch logic...
            best_subtitle = self._pick_best_subtitle(subtitles)
            # ... fetch subtitle JSON ...
            subtitle_source = best_subtitle.get("lan", "unknown")

            chunks = group_segments(
                segments=subtitle_data.get("body", []),
                source_type="bilibili",
                media_url=f"https://www.bilibili.com/video/{bvid}",
                window_seconds=60,
            )
```

**Imports** — add at top:
```python
import logging
from app.tools.extractors.utils import group_segments
logger = logging.getLogger(__name__)
```

**Metadata** — add unified fields:
```python
            metadata={
                "platform": "bilibili",
                "video_id": bvid,
                "bvid": bvid,  # backward compat
                "cid": cid,
                "title": title,
                "author": info.get("owner", {}).get("name", ""),
                "duration": duration,
                "subtitle_source": subtitle_source,
                "media_url": media_url,
                "page": page,
                "page_count": len(pages),
            },
```

**Remove** the `_group_subtitle_segments` static method entirely (replaced by `utils.group_segments`).

- [ ] **Step 2: Run existing tests to verify no regression**

```bash
.venv/bin/python -m pytest -v --tb=short
```
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/tools/extractors/bilibili.py
git commit -m "refactor(extractors): bilibili uses shared utils + Whisper fallback"
```

---

### Task 5: Wire into pipeline + API

**Files:**
- Modify: `backend/app/tools/extractors/__init__.py`
- Modify: `backend/app/api/routes/sources.py`
- Modify: `backend/app/worker/tasks/content_ingestion.py`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add dependencies to pyproject.toml**

Add to `[project] dependencies`:
```toml
    "youtube-transcript-api>=0.6.1",
    "yt-dlp>=2024.1",
```

Add optional dependency group:
```toml
[project.optional-dependencies]
dev = [
    # ... existing dev deps ...
]
whisper = [
    "openai-whisper>=20231117",
]
```

Run: `.venv/bin/uv sync` (or `export PATH="$HOME/.local/bin:$PATH" && uv sync`)

- [ ] **Step 2: Register YouTube extractor**

File: `backend/app/tools/extractors/__init__.py`

Add import and registry entry:
```python
from app.tools.extractors.youtube import YouTubeExtractor

EXTRACTORS: dict[str, type[ContentExtractor]] = {
    "bilibili": BilibiliExtractor,
    "pdf": PDFExtractor,
    "youtube": YouTubeExtractor,
}

# Update __all__
__all__ = [
    # ... existing ...
    "YouTubeExtractor",
]
```

- [ ] **Step 3: Update source type detection**

File: `backend/app/api/routes/sources.py`

Update `_detect_source_type`:
```python
def _detect_source_type(url: str | None) -> str:
    if not url:
        raise HTTPException(400, "URL is required for non-file sources")
    if "bilibili.com" in url or "b23.tv" in url:
        return "bilibili"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    raise HTTPException(400, f"Cannot detect source type from URL: {url}")
```

Update validation (around line 57):
```python
        if source_type not in ("bilibili", "youtube"):
            raise HTTPException(400, f"Unsupported source type: {source_type}")
```

- [ ] **Step 4: Update _create_extractor in content_ingestion.py**

File: `backend/app/worker/tasks/content_ingestion.py`

Replace lines 174-195:
```python
def _create_extractor(source):
    """Create the appropriate extractor for a source."""
    from app.tools.extractors import get_extractor
    from app.config import get_settings

    settings = get_settings()
    whisper_kwargs = {
        "whisper_mode": settings.whisper_mode,
        "whisper_model": settings.whisper_model,
    }

    if source.type == "youtube":
        return get_extractor("youtube", **whisper_kwargs)
    elif source.type == "bilibili":
        kwargs = {**whisper_kwargs}
        sessdata = getattr(settings, "bilibili_sessdata", None)
        if sessdata:
            from bilibili_api import Credential
            kwargs["credential"] = Credential(
                sessdata=settings.bilibili_sessdata,
                bili_jct=getattr(settings, "bilibili_bili_jct", ""),
                buvid3=getattr(settings, "bilibili_buvid3", ""),
            )
        return get_extractor("bilibili", **kwargs)
    elif source.type == "pdf":
        return get_extractor("pdf")
    else:
        raise ValueError(f"Unsupported source type: {source.type}")
```

- [ ] **Step 5: Run all tests**

```bash
.venv/bin/python -m pytest -v --tb=short
```
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/tools/extractors/__init__.py backend/app/api/routes/sources.py backend/app/worker/tasks/content_ingestion.py backend/pyproject.toml
git commit -m "feat: wire YouTube extractor into pipeline and API"
```

---

### Task 6: Frontend — add YouTube tab

**Files:**
- Modify: `frontend/src/app/import/page.tsx`

- [ ] **Step 1: Update import page**

Read current `frontend/src/app/import/page.tsx`. Apply these changes:

1. Add `"youtube"` to `sourceType` state type:
```tsx
const [sourceType, setSourceType] = useState<"bilibili" | "youtube" | "pdf">("bilibili");
```

2. Add YouTube tab button (between Bilibili and PDF):
```tsx
<button onClick={() => setSourceType("youtube")}
  className={cn("flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg border text-sm font-medium transition-all",
    sourceType === "youtube" ? "border-blue-500 bg-blue-50 text-blue-700" : "border-gray-200 text-gray-500 hover:border-gray-300")}>
  <Play className="w-4 h-4" /> YouTube
</button>
```

3. Add YouTube URL input section (similar to Bilibili):
```tsx
{sourceType === "youtube" && (
  <div className="mb-6">
    <label className="block text-sm font-medium text-gray-700 mb-2">视频链接</label>
    <div className="flex gap-2">
      <div className="flex-1 relative">
        <Play className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.youtube.com/watch?v=..."
          className="w-full pl-10 pr-4 py-2.5 rounded-lg border border-gray-300 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
        />
      </div>
    </div>
    <button onClick={() => setUrl("https://www.youtube.com/watch?v=kCc8FmEb1nY")} className="mt-2 text-xs text-blue-600 hover:text-blue-700">
      试试看：Karpathy - Let's build GPT from scratch
    </button>
  </div>
)}
```

4. Add YouTube loading steps:
```tsx
const loadingSteps = sourceType === "youtube"
  ? ["提取 YouTube 视频字幕", "识别核心概念与前置依赖", "评估难度等级", "准备自适应评估题"]
  : sourceType === "bilibili"
  ? ["提取 B站视频字幕", "识别核心概念与前置依赖", "评估难度等级", "准备自适应评估题"]
  : ["解析 PDF 文档结构", "提取文本与代码块", "识别核心概念与前置依赖", "准备自适应评估题"];
```

5. Update `canSubmit` to include YouTube:
```tsx
const canSubmit = goal && (sourceType === "pdf" ? pdfName : url.trim());
```

6. Update loading title:
```tsx
<h2>
  {sourceType === "youtube" ? "正在分析 YouTube 视频..."
   : sourceType === "bilibili" ? "正在分析 B站视频..."
   : "正在分析 PDF 文档..."}
</h2>
```

- [ ] **Step 2: Build and verify**

```bash
cd /Users/tulip/Documents/Claude/Projects/LLMs/socratiq/frontend && npm run build
```
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
cd /Users/tulip/Documents/Claude/Projects/LLMs/socratiq
git add frontend/src/app/import/page.tsx
git commit -m "feat(frontend): add YouTube tab to import page"
```

---

### Task 7: Extend smoke tests

**Files:**
- Modify: `backend/tests/test_smoke.py`

- [ ] **Step 1: Add YouTube source smoke test**

Add to `TestSources` class in `test_smoke.py`:

```python
    @pytest.mark.asyncio
    async def test_create_youtube_source(self, client: AsyncClient):
        with patch("app.api.routes.sources.ingest_source") as mock_task:
            mock_result = MagicMock()
            mock_result.id = "fake-yt-task"
            mock_task.delay.return_value = mock_result

            res = await client.post("/api/sources", data={
                "url": "https://www.youtube.com/watch?v=kCc8FmEb1nY",
            })
            assert res.status_code == 201
            data = res.json()
            assert data["type"] == "youtube"
            assert data["status"] == "pending"
            assert data["task_id"] == "fake-yt-task"
```

- [ ] **Step 2: Run all tests**

```bash
cd /Users/tulip/Documents/Claude/Projects/LLMs/socratiq/backend
.venv/bin/python -m pytest -v --tb=short
```
Expected: ALL PASS (previous 63 + new extractor tests + new smoke test)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_smoke.py
git commit -m "test: add YouTube source creation smoke test"
```

---

### Task 8: Final verification

- [ ] **Step 1: Run full backend test suite**

```bash
cd /Users/tulip/Documents/Claude/Projects/LLMs/socratiq/backend
.venv/bin/python -m pytest -v
```

- [ ] **Step 2: Run frontend build**

```bash
cd /Users/tulip/Documents/Claude/Projects/LLMs/socratiq/frontend
npm run build
```

- [ ] **Step 3: Run frontend tests**

```bash
cd /Users/tulip/Documents/Claude/Projects/LLMs/socratiq/frontend
npm test
```

- [ ] **Step 4: Manual smoke test (if services running)**

```bash
# Backend health
curl http://localhost:8000/health

# Create YouTube source (will fail at Celery task since no worker, but API should return 201)
curl -X POST http://localhost:8000/api/sources -F "url=https://www.youtube.com/watch?v=kCc8FmEb1nY"
```
