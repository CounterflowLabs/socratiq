# YouTube Integration + Unified ASR Fallback Design

**Date**: 2026-03-25
**Status**: Approved
**Scope**: YouTube extractor + Whisper ASR fallback (shared by YouTube & Bilibili) + frontend YouTube tab

---

## 1. Overview

Add YouTube as a third content source alongside Bilibili and PDF. Simultaneously upgrade Bilibili extractor to share the same ASR fallback when subtitles are unavailable.

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Subtitle language | Auto-detect (youtube-transcript-api default) | Phase 2 加翻译功能 |
| No subtitle fallback | yt-dlp 下载音频 + Whisper ASR | 用户体验优先，不因无字幕拒绝服务 |
| Whisper mode | 可配置 API / 本地 | API 快但收费，本地免费但慢 |
| 视频元数据 | yt-dlp --dump-json | 已是必要依赖，零额外成本 |
| 元数据存储 | sources.metadata_ JSONB（统一字段结构） | 现阶段不建独立表 |

---

## 2. Architecture

```
YouTube/Bilibili URL
    ↓
sources.py: _detect_source_type → "youtube" | "bilibili"
    ↓
Celery: ingest_source → _create_extractor(source)
    ↓
YouTubeExtractor / BilibiliExtractor
    ├── 平台 API 获取元数据
    ├── 字幕提取（平台原生）
    │   └── 失败 → WhisperService.transcribe(url)
    │              ├── yt-dlp 下载音频（支持 YouTube + Bilibili）
    │              └── Whisper 转写（API 或本地）
    └── group_segments() 公共分块（~60s 窗口）
    ↓
ExtractionResult → （后续管线不变）
```

---

## 3. New Files

### 3.1 `backend/app/tools/extractors/youtube.py`

```python
class YouTubeExtractor(ContentExtractor):
    """Extract subtitles from YouTube videos."""

    def __init__(self, whisper_mode: str = "api", whisper_model: str = "base"):
        self._whisper_mode = whisper_mode
        self._whisper_model = whisper_model

    def supported_source_type(self) -> str:
        return "youtube"

    async def extract(self, source: str, **kwargs) -> ExtractionResult:
        video_id = self._parse_video_id(source)

        # 1. Metadata via yt-dlp
        metadata = await self._fetch_metadata(video_id)

        # 2. Subtitles: youtube-transcript-api first, Whisper fallback
        try:
            segments = await self._fetch_transcript(video_id)
            subtitle_source = "transcript_api"
        except Exception:
            segments = await self._whisper_fallback(source)
            subtitle_source = "whisper"

        # 3. Group into ~60s chunks
        chunks = group_segments(
            segments=segments,
            source_type="youtube",
            media_url=f"https://www.youtube.com/watch?v={video_id}",
            window_seconds=60,
        )

        return ExtractionResult(
            title=metadata["title"],
            chunks=chunks,
            metadata={
                "platform": "youtube",
                "video_id": video_id,
                "title": metadata["title"],
                "author": metadata.get("uploader", ""),
                "duration": metadata.get("duration", 0),
                "subtitle_source": subtitle_source,
                "subtitle_language": metadata.get("language", ""),
                "media_url": f"https://www.youtube.com/watch?v={video_id}",
            },
        )
```

**URL parsing** supports:
- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://youtube.com/watch?v=VIDEO_ID&t=120`

**Metadata** via `yt-dlp --dump-json --no-download URL`:
- title, uploader, duration, language, thumbnail, description

**Transcript** via `youtube_transcript_api.YouTubeTranscriptApi.get_transcript(video_id)`:
- Returns `[{"text": "...", "start": 0.0, "duration": 2.5}, ...]`
- Auto-detect language (no preference specified)

### 3.2 `backend/app/tools/extractors/asr.py`

```python
class WhisperService:
    """Audio-to-text transcription via OpenAI Whisper (API or local)."""

    def __init__(self, mode: str = "api", model: str = "base"):
        self._mode = mode    # "api" | "local"
        self._model = model  # local model size: tiny/base/small/medium/large

    async def transcribe(self, url: str) -> list[dict]:
        """Download audio and transcribe.

        Args:
            url: Video URL (YouTube or Bilibili, yt-dlp handles both)

        Returns:
            List of {"text": str, "start": float, "end": float}
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
        """Download audio via yt-dlp (supports YouTube + Bilibili)."""
        # yt-dlp -x --audio-format wav --audio-quality 0 -o <tmpfile> <url>
        # Run as subprocess via asyncio.create_subprocess_exec

    async def _transcribe_api(self, audio_path: Path) -> list[dict]:
        """Transcribe via OpenAI Whisper API."""
        # openai.audio.transcriptions.create(
        #     model="whisper-1", file=open(audio_path, "rb"),
        #     response_format="verbose_json", timestamp_granularities=["segment"]
        # )
        # Returns segments with start/end timestamps

    async def _transcribe_local(self, audio_path: Path) -> list[dict]:
        """Transcribe via local whisper model."""
        # import whisper (or faster_whisper)
        # model = whisper.load_model(self._model)
        # result = model.transcribe(str(audio_path))
        # Run in asyncio.to_thread() to avoid blocking event loop
```

### 3.3 `backend/app/tools/extractors/utils.py`

从 `bilibili.py` 提取的公共分块逻辑：

```python
def group_segments(
    segments: list[dict],
    source_type: str,
    media_url: str,
    window_seconds: int = 60,
) -> list[RawContentChunk]:
    """Group timed subtitle segments into time-windowed chunks.

    Works with both YouTube and Bilibili segment formats:
    - YouTube: {"text": str, "start": float, "duration": float}
    - Bilibili: {"content": str, "from": float, "to": float}
    - Whisper: {"text": str, "start": float, "end": float}

    Normalizes to {"text": str, "start": float, "end": float} first.
    """
    # Normalize segment format
    normalized = []
    for seg in segments:
        text = seg.get("text") or seg.get("content", "")
        start = seg.get("start") or seg.get("from", 0)
        end = seg.get("end") or seg.get("to") or (start + seg.get("duration", 0))
        if text.strip():
            normalized.append({"text": text.strip(), "start": start, "end": end})

    # Group by time window (same logic as current bilibili.py)
    # Returns list[RawContentChunk]
```

---

## 4. Modified Files

### 4.1 `backend/app/tools/extractors/__init__.py`

```python
from app.tools.extractors.youtube import YouTubeExtractor

EXTRACTORS: dict[str, type[ContentExtractor]] = {
    "bilibili": BilibiliExtractor,
    "pdf": PDFExtractor,
    "youtube": YouTubeExtractor,  # NEW
}
```

### 4.2 `backend/app/tools/extractors/bilibili.py`

- **Replace** `_group_subtitle_segments` with call to `utils.group_segments`
- **Replace** line 76-82 `raise ExtractionError("No subtitles")` with Whisper fallback:

```python
if not subtitles:
    # Fallback: Whisper ASR
    whisper = WhisperService(
        mode=settings.whisper_mode,
        model=settings.whisper_model,
    )
    segments = await whisper.transcribe(source)
    subtitle_source = "whisper"
else:
    # ... existing subtitle fetch logic ...
    subtitle_source = best_subtitle.get("lan", "unknown")
```

- **Update** metadata to include unified fields (`platform`, `subtitle_source`)

### 4.3 `backend/app/api/routes/sources.py`

```python
def _detect_source_type(url: str | None) -> str:
    if "bilibili.com" in url or "b23.tv" in url:
        return "bilibili"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    raise HTTPException(400, f"Cannot detect source type from URL: {url}")

# Validation (line ~57):
if source_type not in ("bilibili", "youtube"):
    raise HTTPException(400, f"Unsupported source type: {source_type}")
```

### 4.4 `backend/app/worker/tasks/content_ingestion.py`

Update `_create_extractor` to handle YouTube:

```python
def _create_extractor(source):
    if source.type == "youtube":
        return get_extractor(
            "youtube",
            whisper_mode=settings.whisper_mode,
            whisper_model=settings.whisper_model,
        )
    elif source.type == "bilibili":
        kwargs = {"whisper_mode": settings.whisper_mode, "whisper_model": settings.whisper_model}
        if settings.bilibili_sessdata:
            kwargs["credential"] = Credential(...)
        return get_extractor("bilibili", **kwargs)
    elif source.type == "pdf":
        return get_extractor("pdf")
```

### 4.5 `backend/app/config.py`

```python
# Whisper ASR
whisper_mode: str = "api"        # "api" | "local"
whisper_model: str = "base"      # local model: tiny/base/small/medium/large
```

### 4.6 `backend/pyproject.toml`

```toml
"youtube-transcript-api>=0.6.1",
"yt-dlp>=2024.1",
```

Optional dependency for local Whisper:
```toml
[project.optional-dependencies]
whisper = ["openai-whisper>=20231117"]
```

### 4.7 `frontend/src/app/import/page.tsx`

Add third tab:
```tsx
const [sourceType, setSourceType] = useState<"bilibili" | "youtube" | "pdf">("bilibili");

// Tab buttons:
<button onClick={() => setSourceType("youtube")}>
  <Play /> YouTube
</button>

// YouTube URL input:
{sourceType === "youtube" && (
  <input placeholder="https://www.youtube.com/watch?v=..." />
  <button onClick={() => setUrl("https://www.youtube.com/watch?v=kCc8FmEb1nY")}>
    试试看：Karpathy - Let's build GPT from scratch
  </button>
)}

// Loading steps for YouTube:
const loadingSteps = sourceType === "youtube"
  ? ["提取 YouTube 视频字幕", "识别核心概念与前置依赖", "评估难度等级", "准备自适应评估题"]
  : sourceType === "bilibili"
  ? ["提取 B站视频字幕", ...]
  : ["解析 PDF 文档结构", ...];
```

---

## 5. Metadata Normalization

所有视频提取器返回统一的 metadata 字段集（存入 `sources.metadata_` JSONB）：

```python
{
    "platform": "youtube" | "bilibili",
    "video_id": "dQw4w9WgXcQ" | "BV1xxx",
    "title": "...",
    "author": "...",
    "duration": 360,  # seconds
    "subtitle_source": "cc" | "auto" | "whisper",
    "subtitle_language": "en" | "zh-CN" | ...,
    "media_url": "https://...",
}
```

Bilibili 现有的 `bvid`, `cid`, `uploader` 等字段保留（向后兼容），新增统一字段。

---

## 6. Testing

### New test files

| File | Tests |
|------|-------|
| `tests/tools/extractors/test_youtube.py` | URL parsing, transcript fetch (mock), Whisper fallback (mock), segment grouping |
| `tests/tools/extractors/test_asr.py` | WhisperService API mode (mock openai), local mode (mock whisper), audio download (mock yt-dlp) |
| `tests/tools/extractors/test_utils.py` | `group_segments` with YouTube/Bilibili/Whisper formats, edge cases |
| `tests/test_smoke.py` (extend) | `POST /api/sources` with YouTube URL → 201 |

### Mock strategy

- `youtube_transcript_api` — mock `YouTubeTranscriptApi.get_transcript()`
- `yt-dlp` — mock `asyncio.create_subprocess_exec`
- `openai.audio.transcriptions` — mock for Whisper API mode
- `whisper.load_model` — mock for local mode

---

## 7. Implementation Plan

### Phase 1: Public modules (3 tasks)
1. Create `utils.py` — extract `group_segments` from bilibili.py
2. Create `asr.py` — WhisperService (API + local modes)
3. Update `config.py` — add whisper_mode, whisper_model

### Phase 2: YouTube extractor (3 tasks)
4. Create `youtube.py` — YouTubeExtractor
5. Register in `__init__.py`
6. Add `youtube-transcript-api`, `yt-dlp` to pyproject.toml

### Phase 3: Bilibili upgrade (2 tasks)
7. Refactor bilibili.py — use `group_segments`, add Whisper fallback
8. Update metadata to include unified fields

### Phase 4: API + Pipeline (2 tasks)
9. Update `sources.py` — YouTube URL detection + validation
10. Update `content_ingestion.py` — YouTube extractor creation

### Phase 5: Frontend (1 task)
11. Update `import/page.tsx` — YouTube tab

### Phase 6: Tests (2 tasks)
12. Write unit tests (youtube, asr, utils)
13. Extend smoke tests

---

## 8. Phase 2 Backlog (Not in This Spec)

- 视频字幕翻译功能（LLM 或翻译 API）
- 字幕语言偏好设置（用户级配置）
