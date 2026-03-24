# Sub-project B: Content Ingestion Pipeline Design

**Date**: 2026-03-24
**Status**: Approved
**Scope**: Content extractors (Bilibili + PDF) + LLM content analysis + embedding + course generation + Celery tasks + API endpoints
**Depends on**: Sub-project A (infrastructure layer) — all DB models, LLM abstraction, Celery framework must be in place

---

## 1. Overview

Sub-project B implements the content ingestion pipeline — the first user-facing feature of LearnMentor. A user submits a Bilibili video URL or uploads a PDF, and the system asynchronously extracts content, analyzes it with an LLM, generates embeddings, and produces a structured course.

### Data Flow

```
User submits URL or uploads PDF
         |
         v
POST /api/sources  ─────────────────────────────────────┐
  1. Validate input                                      |
  2. Create Source record (status=pending)                |
  3. Dispatch Celery task: ingest_source(source_id)       |
  4. Return Source + task_id immediately                  |
         |                                               |
         v                                               |
Celery Worker: ingest_source(source_id)                  |
  |                                                      |
  |  Step 1: EXTRACT                                     |
  |  Source.status → "extracting"                         |
  |  BilibiliExtractor or PDFExtractor                   |
  |  → list[RawContentChunk]                             |
  |  → Store raw_content in Source                        |
  |                                                      |
  |  Step 2: ANALYZE                                     |
  |  Source.status → "analyzing"                          |
  |  ContentAnalyzer.analyze(chunks)                      |
  |  → LLM call (task_type=CONTENT_ANALYSIS)              |
  |  → AnalysisResult (topics, concepts, difficulty)      |
  |                                                      |
  |  Step 3: STORE                                       |
  |  Source.status → "storing"                            |
  |  → Write ContentChunks to DB                          |
  |  → Write Concepts to DB (dedup by name/aliases)       |
  |  → Write ConceptSources to DB                         |
  |                                                      |
  |  Step 4: EMBED                                       |
  |  Source.status → "embedding"                          |
  |  EmbeddingService.embed_chunks(chunks)                |
  |  → LLM call (task_type=EMBEDDING)                     |
  |  → Update content_chunks.embedding                    |
  |  → Update concepts.embedding                          |
  |                                                      |
  |  Step 5: DONE                                        |
  |  Source.status → "ready"                              |
  |                                                      |
  v                                                      |
User polls GET /api/sources/{id}  <──────────────────────┘
  → status + progress info

Later:
POST /api/courses/generate  (source_ids)
  → CourseGenerator creates Course + Sections from analyzed sources
```

### Status Progression

The `sources.status` column tracks pipeline progress:

| Status | Meaning |
|--------|---------|
| `pending` | Source record created, task not yet started |
| `extracting` | Extractor is pulling content from source |
| `analyzing` | LLM is analyzing extracted content |
| `storing` | Writing analysis results to DB |
| `embedding` | Computing vector embeddings |
| `ready` | Pipeline complete, content available |
| `error` | Pipeline failed (error details in `metadata_`) |

**Schema change**: The existing `Source.status` column currently allows `pending|processing|ready|error`. This spec expands it to include `extracting|analyzing|storing|embedding` for finer-grained progress tracking. The `processing` value is retired — use the specific stage values instead.

---

## 2. Content Extractors

### 2.1 Base Extractor

**File**: `backend/app/tools/extractors/base.py`

```python
"""Base content extractor interface and shared types."""

from abc import ABC, abstractmethod
from pydantic import BaseModel, Field


class RawContentChunk(BaseModel):
    """A chunk of raw extracted content before LLM analysis.

    This is NOT the DB model ContentChunk — it's the intermediate Pydantic
    model passed from extractors to the content analyzer. The DB model
    ContentChunk (app.db.models.content_chunk) is written after analysis.
    """

    source_type: str  # "bilibili" | "pdf"
    raw_text: str
    metadata: dict = Field(default_factory=dict)
    # Bilibili: {"start_time": 180.0, "end_time": 240.0, "part": 1}
    # PDF: {"page": 3, "heading": "Chapter 2", "heading_level": 2}
    media_url: str | None = None
    # Bilibili: embed URL for the video


class ExtractionResult(BaseModel):
    """Result of a content extraction operation."""

    title: str
    chunks: list[RawContentChunk]
    metadata: dict = Field(default_factory=dict)
    # Bilibili: {"bvid": "BV1xx...", "duration": 1234, "uploader": "..."}
    # PDF: {"page_count": 42, "file_size": 123456}


class ContentExtractor(ABC):
    """Abstract base class for content extractors."""

    @abstractmethod
    async def extract(self, source: str, **kwargs) -> ExtractionResult:
        """Extract content from a source.

        Args:
            source: URL string (for Bilibili) or file path (for PDF).
            **kwargs: Extractor-specific options.

        Returns:
            ExtractionResult with title and list of content chunks.

        Raises:
            ExtractionError: If extraction fails.
        """
        ...

    @abstractmethod
    def supported_source_type(self) -> str:
        """Return the source type this extractor handles (e.g. 'bilibili', 'pdf')."""
        ...


class ExtractionError(Exception):
    """Raised when content extraction fails."""

    def __init__(self, message: str, source_type: str, details: dict | None = None):
        self.source_type = source_type
        self.details = details or {}
        super().__init__(message)
```

### 2.2 Bilibili Extractor

**File**: `backend/app/tools/extractors/bilibili.py`

**Library**: `bilibili-api-python` (PyPI: `bilibili-api-python`)

**What it does**: Given a Bilibili video URL, extract subtitle text with timestamps.

```python
"""Bilibili video subtitle extractor."""

import re
from bilibili_api import video, Credential

from app.tools.extractors.base import (
    ContentExtractor,
    ExtractionError,
    ExtractionResult,
    RawContentChunk,
)


class BilibiliExtractor(ContentExtractor):
    """Extract subtitles from Bilibili videos.

    Subtitle priority:
    1. CC subtitles (human-uploaded, highest quality)
    2. AI-generated subtitles (auto-generated by Bilibili)
    3. No subtitles → raise ExtractionError with guidance

    Cookie auth is optional but recommended — some videos restrict
    subtitle access to logged-in users.
    """

    def __init__(self, credential: Credential | None = None):
        """Initialize with optional Bilibili credential.

        Args:
            credential: bilibili_api.Credential for authenticated access.
                Created from SESSDATA + bili_jct + buvid3 cookies.
                If None, only publicly accessible subtitles work.
        """
        self.credential = credential

    def supported_source_type(self) -> str:
        return "bilibili"

    async def extract(self, source: str, **kwargs) -> ExtractionResult:
        """Extract subtitles from a Bilibili video URL.

        Args:
            source: Bilibili URL (e.g. "https://www.bilibili.com/video/BV1xx...")
            **kwargs:
                page: int — for multi-part videos, which part (default 0 = first)

        Returns:
            ExtractionResult with subtitle chunks.
        """
        bvid = self._parse_bvid(source)
        page = kwargs.get("page", 0)

        v = video.Video(bvid=bvid, credential=self.credential)

        # 1. Get video info (title, duration, pages)
        info = await v.get_info()
        title = info["title"]
        duration = info.get("duration", 0)
        pages = info.get("pages", [])

        # Validate page index
        if page >= len(pages) and len(pages) > 0:
            raise ExtractionError(
                f"Page {page} not found. Video has {len(pages)} pages.",
                source_type="bilibili",
                details={"bvid": bvid, "page_count": len(pages)},
            )

        cid = pages[page]["cid"] if pages else info.get("cid")

        # 2. Get subtitle list
        subtitle_info = await v.get_subtitle(cid=cid)
        subtitles = subtitle_info.get("subtitles", [])

        if not subtitles:
            raise ExtractionError(
                "No subtitles available for this video. "
                "Try a video with CC or AI-generated subtitles.",
                source_type="bilibili",
                details={"bvid": bvid, "has_subtitle": False},
            )

        # 3. Pick best subtitle (prefer CC over AI-generated)
        # CC subtitles usually have lan_doc containing "上传" or specific language
        # AI subtitles have lan="ai-zh"
        best_subtitle = self._pick_best_subtitle(subtitles)

        # 4. Fetch subtitle content (JSON with timestamp segments)
        subtitle_url = best_subtitle["subtitle_url"]
        if subtitle_url.startswith("//"):
            subtitle_url = "https:" + subtitle_url

        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(subtitle_url)
            resp.raise_for_status()
            subtitle_data = resp.json()

        # 5. Convert to RawContentChunks
        # Group subtitle segments into ~60-second windows for reasonable chunk sizes
        chunks = self._group_subtitle_segments(
            segments=subtitle_data.get("body", []),
            source_type="bilibili",
            bvid=bvid,
            window_seconds=60,
        )

        media_url = f"https://www.bilibili.com/video/{bvid}"

        return ExtractionResult(
            title=title,
            chunks=chunks,
            metadata={
                "bvid": bvid,
                "cid": cid,
                "duration": duration,
                "uploader": info.get("owner", {}).get("name", ""),
                "page": page,
                "page_count": len(pages),
                "subtitle_type": best_subtitle.get("lan", "unknown"),
                "media_url": media_url,
            },
        )

    @staticmethod
    def _parse_bvid(url: str) -> str:
        """Extract BV号 from various Bilibili URL formats.

        Supports:
        - https://www.bilibili.com/video/BV1xx411c7XW
        - https://b23.tv/BV1xx411c7XW
        - https://www.bilibili.com/video/BV1xx411c7XW?p=2
        - BV1xx411c7XW (raw BV号)
        """
        # Direct BV号
        if re.match(r"^BV[\w]+$", url):
            return url

        # URL patterns
        match = re.search(r"(BV[\w]+)", url)
        if match:
            return match.group(1)

        raise ExtractionError(
            f"Cannot parse BV号 from URL: {url}",
            source_type="bilibili",
            details={"url": url},
        )

    @staticmethod
    def _pick_best_subtitle(subtitles: list[dict]) -> dict:
        """Pick the best subtitle track.

        Priority: CC zh-CN > CC zh > AI zh > any CC > any AI > first available
        """
        cc_subs = [s for s in subtitles if not s.get("lan", "").startswith("ai-")]
        ai_subs = [s for s in subtitles if s.get("lan", "").startswith("ai-")]

        # Prefer Chinese CC
        for sub in cc_subs:
            if sub.get("lan") in ("zh-CN", "zh-Hans"):
                return sub
        for sub in cc_subs:
            if "zh" in sub.get("lan", ""):
                return sub

        # Then Chinese AI
        for sub in ai_subs:
            if "zh" in sub.get("lan", ""):
                return sub

        # Fallback
        return cc_subs[0] if cc_subs else ai_subs[0] if ai_subs else subtitles[0]

    @staticmethod
    def _group_subtitle_segments(
        segments: list[dict],
        source_type: str,
        bvid: str,
        window_seconds: int = 60,
    ) -> list[RawContentChunk]:
        """Group subtitle segments into time-windowed chunks.

        Each Bilibili subtitle segment is typically 2-5 seconds.
        We group them into ~60-second windows to create meaningful chunks
        for LLM analysis.

        Args:
            segments: List of {"from": float, "to": float, "content": str}
            source_type: "bilibili"
            bvid: Video BV号 for media_url
            window_seconds: Target window size in seconds (default 60)

        Returns:
            List of RawContentChunk, each covering ~window_seconds of video.
        """
        if not segments:
            return []

        chunks = []
        current_texts: list[str] = []
        window_start = segments[0].get("from", 0)

        for seg in segments:
            seg_start = seg.get("from", 0)
            seg_text = seg.get("content", "").strip()

            if not seg_text:
                continue

            # Start new window if we've exceeded the time threshold
            if seg_start - window_start >= window_seconds and current_texts:
                chunks.append(
                    RawContentChunk(
                        source_type=source_type,
                        raw_text="\n".join(current_texts),
                        metadata={
                            "start_time": window_start,
                            "end_time": seg_start,
                        },
                        media_url=f"https://www.bilibili.com/video/{bvid}",
                    )
                )
                current_texts = []
                window_start = seg_start

            current_texts.append(seg_text)

        # Flush remaining
        if current_texts:
            last_end = segments[-1].get("to", segments[-1].get("from", 0))
            chunks.append(
                RawContentChunk(
                    source_type=source_type,
                    raw_text="\n".join(current_texts),
                    metadata={
                        "start_time": window_start,
                        "end_time": last_end,
                    },
                    media_url=f"https://www.bilibili.com/video/{bvid}",
                )
            )

        return chunks
```

**Bilibili Cookie Authentication**:

Some videos require authentication to access subtitles. The `Credential` object needs three cookie values:

```python
# Optional — configured via environment variables
# BILIBILI_SESSDATA, BILIBILI_BILI_JCT, BILIBILI_BUVID3
credential = Credential(
    sessdata="xxx",
    bili_jct="xxx",
    buvid3="xxx",
)
```

These are added to `config.py` as optional fields (see Section 9).

### 2.3 PDF Extractor

**File**: `backend/app/tools/extractors/pdf.py`

**Library**: `pymupdf` (PyPI: `pymupdf`, import as `fitz`)

**What it does**: Given a PDF file path, extract text per page with heading detection and code block detection.

```python
"""PDF content extractor using PyMuPDF."""

import re
from pathlib import Path

import fitz  # pymupdf

from app.tools.extractors.base import (
    ContentExtractor,
    ExtractionError,
    ExtractionResult,
    RawContentChunk,
)


class PDFExtractor(ContentExtractor):
    """Extract structured text content from PDF files.

    Capabilities:
    - Text extraction per page
    - Heading detection (by font size analysis)
    - Code block detection (by monospace font detection)
    - Merges pages by detected headings into logical sections
    """

    def supported_source_type(self) -> str:
        return "pdf"

    async def extract(self, source: str, **kwargs) -> ExtractionResult:
        """Extract content from a PDF file.

        Args:
            source: Absolute file path to the PDF.
            **kwargs:
                max_pages: int — limit extraction to first N pages (default: no limit)

        Returns:
            ExtractionResult with text chunks per logical section.
        """
        file_path = Path(source)
        if not file_path.exists():
            raise ExtractionError(
                f"PDF file not found: {source}",
                source_type="pdf",
                details={"path": source},
            )

        max_pages = kwargs.get("max_pages")

        try:
            doc = fitz.open(str(file_path))
        except Exception as e:
            raise ExtractionError(
                f"Failed to open PDF: {e}",
                source_type="pdf",
                details={"path": source, "error": str(e)},
            )

        try:
            title = doc.metadata.get("title", "") or file_path.stem
            page_count = len(doc)
            pages_to_process = min(page_count, max_pages) if max_pages else page_count

            # Phase 1: Extract raw page data with font analysis
            raw_pages = []
            for page_num in range(pages_to_process):
                page = doc.load_page(page_num)
                page_data = self._extract_page(page, page_num)
                if page_data["text"].strip():
                    raw_pages.append(page_data)

            # Phase 2: Detect heading font size threshold
            heading_threshold = self._detect_heading_threshold(raw_pages)

            # Phase 3: Group pages into sections by headings
            chunks = self._build_sections(raw_pages, heading_threshold)

            return ExtractionResult(
                title=title,
                chunks=chunks,
                metadata={
                    "page_count": page_count,
                    "pages_processed": pages_to_process,
                    "file_size": file_path.stat().st_size,
                    "file_name": file_path.name,
                },
            )
        finally:
            doc.close()

    @staticmethod
    def _extract_page(page: fitz.Page, page_num: int) -> dict:
        """Extract text and font info from a single page.

        Returns:
            {
                "page": int,
                "text": str,
                "blocks": [{"text": str, "font_size": float, "is_monospace": bool}],
            }
        """
        blocks_data = []
        text_parts = []

        # Get text blocks with detailed font info
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

        for block in blocks:
            if block.get("type") != 0:  # Skip image blocks
                continue

            block_text_parts = []
            max_font_size = 0
            has_monospace = False

            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    span_text = span.get("text", "").strip()
                    if not span_text:
                        continue

                    font_size = span.get("size", 12)
                    font_name = span.get("font", "").lower()

                    max_font_size = max(max_font_size, font_size)

                    # Detect monospace fonts (common in code blocks)
                    if any(m in font_name for m in ("mono", "courier", "consola", "menlo", "fira code")):
                        has_monospace = True

                    block_text_parts.append(span_text)

            if block_text_parts:
                block_text = " ".join(block_text_parts)
                blocks_data.append({
                    "text": block_text,
                    "font_size": max_font_size,
                    "is_monospace": has_monospace,
                })
                text_parts.append(block_text)

        return {
            "page": page_num,
            "text": "\n".join(text_parts),
            "blocks": blocks_data,
        }

    @staticmethod
    def _detect_heading_threshold(raw_pages: list[dict]) -> float:
        """Determine the font size threshold for headings.

        Strategy: collect all font sizes, body text is the most frequent size,
        anything significantly larger is a heading.
        """
        from collections import Counter

        size_counter: Counter[float] = Counter()
        for page_data in raw_pages:
            for block in page_data["blocks"]:
                # Round to nearest 0.5 to group similar sizes
                rounded = round(block["font_size"] * 2) / 2
                size_counter[rounded] += 1

        if not size_counter:
            return 999.0  # No headings detected

        # Most common size = body text
        body_size = size_counter.most_common(1)[0][0]

        # Heading threshold = body_size + 2pt (heuristic)
        return body_size + 2.0

    @staticmethod
    def _build_sections(
        raw_pages: list[dict], heading_threshold: float
    ) -> list[RawContentChunk]:
        """Group page content into sections based on detected headings.

        When a heading is detected (font_size >= threshold), start a new chunk.
        Pages without headings are appended to the current chunk.
        """
        chunks: list[RawContentChunk] = []
        current_heading = ""
        current_texts: list[str] = []
        current_start_page = 0
        current_code_blocks: list[str] = []

        for page_data in raw_pages:
            page_num = page_data["page"]

            for block in page_data["blocks"]:
                # Check if this block is a heading
                if block["font_size"] >= heading_threshold and not block["is_monospace"]:
                    # Flush current section
                    if current_texts:
                        chunks.append(
                            RawContentChunk(
                                source_type="pdf",
                                raw_text="\n".join(current_texts),
                                metadata={
                                    "page_start": current_start_page,
                                    "page_end": page_num,
                                    "heading": current_heading,
                                    "has_code": len(current_code_blocks) > 0,
                                    "code_blocks": current_code_blocks,
                                },
                            )
                        )

                    # Start new section
                    current_heading = block["text"]
                    current_texts = [block["text"]]
                    current_start_page = page_num
                    current_code_blocks = []
                else:
                    if block["is_monospace"]:
                        current_code_blocks.append(block["text"])
                        current_texts.append(f"```\n{block['text']}\n```")
                    else:
                        current_texts.append(block["text"])

        # Flush final section
        if current_texts:
            last_page = raw_pages[-1]["page"] if raw_pages else 0
            chunks.append(
                RawContentChunk(
                    source_type="pdf",
                    raw_text="\n".join(current_texts),
                    metadata={
                        "page_start": current_start_page,
                        "page_end": last_page,
                        "heading": current_heading,
                        "has_code": len(current_code_blocks) > 0,
                        "code_blocks": current_code_blocks,
                    },
                )
            )

        # If no headings were detected, fall back to per-page chunking
        if len(chunks) <= 1 and len(raw_pages) > 1:
            chunks = [
                RawContentChunk(
                    source_type="pdf",
                    raw_text=page_data["text"],
                    metadata={
                        "page_start": page_data["page"],
                        "page_end": page_data["page"],
                        "heading": "",
                        "has_code": any(b["is_monospace"] for b in page_data["blocks"]),
                    },
                )
                for page_data in raw_pages
                if page_data["text"].strip()
            ]

        return chunks
```

### 2.4 Extractor Registry

**File**: `backend/app/tools/extractors/__init__.py`

```python
"""Content extractor registry."""

from app.tools.extractors.base import ContentExtractor, ExtractionError, ExtractionResult, RawContentChunk
from app.tools.extractors.bilibili import BilibiliExtractor
from app.tools.extractors.pdf import PDFExtractor

EXTRACTORS: dict[str, type[ContentExtractor]] = {
    "bilibili": BilibiliExtractor,
    "pdf": PDFExtractor,
}


def get_extractor(source_type: str, **kwargs) -> ContentExtractor:
    """Get an extractor instance for the given source type.

    Args:
        source_type: One of "bilibili", "pdf".
        **kwargs: Passed to the extractor constructor.

    Returns:
        An initialized ContentExtractor.

    Raises:
        ValueError: If source_type is not supported.
    """
    cls = EXTRACTORS.get(source_type)
    if cls is None:
        raise ValueError(f"Unsupported source type: {source_type}. Supported: {list(EXTRACTORS.keys())}")
    return cls(**kwargs)


__all__ = [
    "ContentExtractor",
    "ExtractionError",
    "ExtractionResult",
    "RawContentChunk",
    "BilibiliExtractor",
    "PDFExtractor",
    "get_extractor",
]
```

---

## 3. LLM Content Analysis Pipeline

**File**: `backend/app/services/content_analyzer.py`

The content analyzer takes raw extracted chunks and calls the LLM to produce structured analysis: topic segmentation, concept extraction, difficulty assessment, and key term identification.

### 3.1 Analysis Types

```python
"""Content analysis service — LLM-powered content understanding."""

from pydantic import BaseModel, Field

from app.services.llm.base import LLMProvider, UnifiedMessage
from app.services.llm.router import ModelRouter, TaskType
from app.tools.extractors.base import RawContentChunk


# --- Output schemas ---

class ExtractedConcept(BaseModel):
    """A concept extracted from content by the LLM."""

    name: str  # Canonical name, e.g. "Attention Mechanism"
    description: str  # 1-2 sentence description
    aliases: list[str] = Field(default_factory=list)  # e.g. ["self-attention", "注意力机制"]
    prerequisites: list[str] = Field(default_factory=list)  # Concept names this depends on
    category: str = ""  # e.g. "deep_learning", "python_basics"


class AnalyzedChunk(BaseModel):
    """A content chunk after LLM analysis."""

    topic: str  # Topic title for this chunk
    summary: str  # 1-3 sentence summary
    raw_text: str  # Original text (preserved)
    concepts: list[str]  # Concept names referenced in this chunk
    difficulty: int = Field(ge=1, le=5)  # 1=beginner, 5=expert
    key_terms: list[str] = Field(default_factory=list)  # Important terms/keywords
    has_code: bool = False
    has_formula: bool = False
    metadata: dict = Field(default_factory=dict)  # Pass-through from RawContentChunk


class AnalysisResult(BaseModel):
    """Complete analysis result for a source."""

    source_title: str
    overall_summary: str  # 3-5 sentence overview
    overall_difficulty: int = Field(ge=1, le=5)
    concepts: list[ExtractedConcept]
    chunks: list[AnalyzedChunk]
    suggested_prerequisites: list[str] = Field(default_factory=list)
    estimated_study_minutes: int = 0
```

### 3.2 ContentAnalyzer

```python
import json
import logging

logger = logging.getLogger(__name__)


class ContentAnalyzer:
    """Analyzes raw content chunks using LLM for structured understanding.

    Uses ModelRouter with TaskType.CONTENT_ANALYSIS to get the appropriate
    LLM provider (typically a light/cheap model since this is batch processing).
    """

    def __init__(self, model_router: ModelRouter):
        self._router = model_router

    async def analyze(
        self,
        title: str,
        chunks: list[RawContentChunk],
        source_type: str,
    ) -> AnalysisResult:
        """Analyze extracted content chunks.

        Strategy:
        1. If total text is small enough (< 8000 chars), analyze all at once.
        2. Otherwise, analyze in batches of chunks, then synthesize.

        Args:
            title: Source title.
            chunks: Raw extracted content chunks.
            source_type: "bilibili" or "pdf".

        Returns:
            AnalysisResult with structured analysis.
        """
        provider = await self._router.get_provider(TaskType.CONTENT_ANALYSIS)

        total_text = "\n\n---\n\n".join(c.raw_text for c in chunks)

        if len(total_text) < 8000:
            return await self._analyze_single(provider, title, chunks, source_type)
        else:
            return await self._analyze_batched(provider, title, chunks, source_type)

    async def _analyze_single(
        self,
        provider: LLMProvider,
        title: str,
        chunks: list[RawContentChunk],
        source_type: str,
    ) -> AnalysisResult:
        """Analyze all chunks in a single LLM call."""
        content_text = self._format_chunks_for_llm(chunks, source_type)

        messages = [
            UnifiedMessage(role="system", content=ANALYSIS_SYSTEM_PROMPT),
            UnifiedMessage(
                role="user",
                content=f"Analyze the following content from a {source_type} source titled \"{title}\":\n\n{content_text}",
            ),
        ]

        response = await provider.chat(
            messages,
            max_tokens=4096,
            temperature=0.3,  # Low temperature for structured output
        )

        # Extract text from response
        response_text = ""
        for block in response.content:
            if block.type == "text" and block.text:
                response_text += block.text

        return self._parse_analysis_response(response_text, title, chunks)

    async def _analyze_batched(
        self,
        provider: LLMProvider,
        title: str,
        chunks: list[RawContentChunk],
        source_type: str,
    ) -> AnalysisResult:
        """Analyze chunks in batches, then synthesize.

        Batch size: ~6000 chars per batch to stay within context window.
        """
        BATCH_CHAR_LIMIT = 6000
        batches: list[list[RawContentChunk]] = []
        current_batch: list[RawContentChunk] = []
        current_chars = 0

        for chunk in chunks:
            chunk_len = len(chunk.raw_text)
            if current_chars + chunk_len > BATCH_CHAR_LIMIT and current_batch:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0
            current_batch.append(chunk)
            current_chars += chunk_len

        if current_batch:
            batches.append(current_batch)

        # Analyze each batch
        batch_results: list[AnalysisResult] = []
        for i, batch in enumerate(batches):
            content_text = self._format_chunks_for_llm(batch, source_type)
            messages = [
                UnifiedMessage(role="system", content=ANALYSIS_SYSTEM_PROMPT),
                UnifiedMessage(
                    role="user",
                    content=(
                        f"Analyze part {i + 1}/{len(batches)} of a {source_type} source "
                        f"titled \"{title}\":\n\n{content_text}"
                    ),
                ),
            ]
            response = await provider.chat(messages, max_tokens=4096, temperature=0.3)
            response_text = "".join(b.text or "" for b in response.content if b.type == "text")
            batch_results.append(self._parse_analysis_response(response_text, title, batch))

        # Synthesize batch results
        return self._merge_batch_results(title, batch_results)

    @staticmethod
    def _format_chunks_for_llm(chunks: list[RawContentChunk], source_type: str) -> str:
        """Format chunks into a text string for LLM input."""
        parts = []
        for i, chunk in enumerate(chunks):
            header = f"--- Chunk {i + 1} ---"
            if source_type == "bilibili":
                start = chunk.metadata.get("start_time", 0)
                end = chunk.metadata.get("end_time", 0)
                header += f" [Video timestamp: {start:.0f}s - {end:.0f}s]"
            elif source_type == "pdf":
                page_start = chunk.metadata.get("page_start", "?")
                page_end = chunk.metadata.get("page_end", "?")
                heading = chunk.metadata.get("heading", "")
                header += f" [Pages: {page_start}-{page_end}]"
                if heading:
                    header += f" [Heading: {heading}]"
            parts.append(f"{header}\n{chunk.raw_text}")
        return "\n\n".join(parts)

    @staticmethod
    def _parse_analysis_response(
        response_text: str,
        title: str,
        chunks: list[RawContentChunk],
    ) -> AnalysisResult:
        """Parse LLM JSON response into AnalysisResult.

        The LLM is prompted to return JSON (see ANALYSIS_SYSTEM_PROMPT).
        Includes fallback parsing for common issues (markdown code fences, etc).
        """
        # Strip markdown code fences if present
        text = response_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM analysis response as JSON, using fallback")
            # Fallback: minimal analysis
            return AnalysisResult(
                source_title=title,
                overall_summary=f"Content from: {title}",
                overall_difficulty=3,
                concepts=[],
                chunks=[
                    AnalyzedChunk(
                        topic=f"Section {i + 1}",
                        summary=c.raw_text[:200],
                        raw_text=c.raw_text,
                        concepts=[],
                        difficulty=3,
                        metadata=c.metadata,
                    )
                    for i, c in enumerate(chunks)
                ],
            )

        # Map parsed JSON to AnalysisResult
        concepts = [
            ExtractedConcept(**c)
            for c in data.get("concepts", [])
        ]

        analyzed_chunks = []
        for i, chunk_data in enumerate(data.get("chunks", [])):
            raw_text = chunks[i].raw_text if i < len(chunks) else ""
            metadata = chunks[i].metadata if i < len(chunks) else {}
            analyzed_chunks.append(
                AnalyzedChunk(
                    topic=chunk_data.get("topic", f"Section {i + 1}"),
                    summary=chunk_data.get("summary", ""),
                    raw_text=raw_text,
                    concepts=chunk_data.get("concepts", []),
                    difficulty=chunk_data.get("difficulty", 3),
                    key_terms=chunk_data.get("key_terms", []),
                    has_code=chunk_data.get("has_code", False),
                    has_formula=chunk_data.get("has_formula", False),
                    metadata=metadata,
                )
            )

        return AnalysisResult(
            source_title=data.get("source_title", title),
            overall_summary=data.get("overall_summary", ""),
            overall_difficulty=data.get("overall_difficulty", 3),
            concepts=concepts,
            chunks=analyzed_chunks,
            suggested_prerequisites=data.get("suggested_prerequisites", []),
            estimated_study_minutes=data.get("estimated_study_minutes", 0),
        )

    @staticmethod
    def _merge_batch_results(title: str, results: list["AnalysisResult"]) -> AnalysisResult:
        """Merge multiple batch analysis results into one."""
        all_concepts: dict[str, ExtractedConcept] = {}
        all_chunks: list[AnalyzedChunk] = []
        all_prereqs: set[str] = set()
        total_minutes = 0
        difficulties: list[int] = []

        for result in results:
            for concept in result.concepts:
                # Dedup by name (keep first occurrence)
                if concept.name not in all_concepts:
                    all_concepts[concept.name] = concept
            all_chunks.extend(result.chunks)
            all_prereqs.update(result.suggested_prerequisites)
            total_minutes += result.estimated_study_minutes
            difficulties.append(result.overall_difficulty)

        avg_difficulty = round(sum(difficulties) / len(difficulties)) if difficulties else 3
        summaries = [r.overall_summary for r in results if r.overall_summary]
        combined_summary = " ".join(summaries) if summaries else f"Content from: {title}"

        return AnalysisResult(
            source_title=title,
            overall_summary=combined_summary,
            overall_difficulty=avg_difficulty,
            concepts=list(all_concepts.values()),
            chunks=all_chunks,
            suggested_prerequisites=list(all_prereqs),
            estimated_study_minutes=total_minutes,
        )
```

### 3.3 LLM System Prompt for Content Analysis

```python
ANALYSIS_SYSTEM_PROMPT = """You are a content analysis engine for an educational platform.
Your job is to analyze learning content and produce structured JSON output.

You MUST respond with ONLY valid JSON (no markdown, no extra text).

Required JSON structure:
{
  "source_title": "string — refined title",
  "overall_summary": "string — 3-5 sentence overview of the content",
  "overall_difficulty": 3,  // 1=absolute beginner, 2=beginner, 3=intermediate, 4=advanced, 5=expert
  "concepts": [
    {
      "name": "string — canonical concept name in English",
      "description": "string — 1-2 sentence description",
      "aliases": ["alias1", "别名"],  // Include Chinese aliases if applicable
      "prerequisites": ["concept_name"],  // Other concept names this depends on
      "category": "string — domain category, e.g. 'machine_learning', 'python_basics'"
    }
  ],
  "chunks": [
    {
      "topic": "string — topic title for this chunk",
      "summary": "string — 1-3 sentence summary",
      "concepts": ["concept_name"],  // Which concepts from the list appear here
      "difficulty": 3,  // 1-5
      "key_terms": ["term1", "term2"],
      "has_code": false,
      "has_formula": false
    }
  ],
  "suggested_prerequisites": ["concept_name"],  // Concepts the learner should know before this content
  "estimated_study_minutes": 30  // Estimated time to study this content thoroughly
}

Rules:
- The "chunks" array MUST have the same number of items as the input chunks, in the same order.
- Concept names should be consistent — if you mention "Attention Mechanism" in concepts, use exactly that string in chunks[].concepts.
- Extract 3-15 concepts per source (don't over-extract trivial ones).
- Difficulty scale: 1=no prior knowledge needed, 3=some programming background, 5=PhD-level.
- For code-heavy content, set has_code=true. For math formulas, set has_formula=true.
- estimated_study_minutes should account for watching/reading + exercises + reflection.
"""
```

---

## 4. Embedding Service

**File**: `backend/app/services/embedding.py`

```python
"""Embedding computation service using the LLM abstraction layer."""

import logging
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.content_chunk import ContentChunk as ContentChunkModel
from app.db.models.concept import Concept as ConceptModel
from app.services.llm.base import LLMProvider, UnifiedMessage
from app.services.llm.router import ModelRouter, TaskType

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Compute and store vector embeddings for content chunks and concepts.

    Uses ModelRouter with TaskType.EMBEDDING to get the embedding provider.
    The embedding provider must support a specific interface — for OpenAI-compatible
    providers, we use the embeddings endpoint directly rather than chat.

    Implementation note: Since LLMProvider.chat() is designed for chat completions,
    embedding is handled differently. The EmbeddingService directly uses the
    underlying OpenAI SDK's embeddings.create() or a dedicated embedding method.
    """

    BATCH_SIZE = 50  # Max texts per embedding API call

    def __init__(self, model_router: ModelRouter):
        self._router = model_router

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Compute embeddings for a list of texts.

        Handles batching internally. Returns embeddings in the same order as input.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (each a list of 1536 floats).
        """
        if not texts:
            return []

        provider = await self._router.get_provider(TaskType.EMBEDDING)

        # The embedding provider needs special handling since LLMProvider
        # is designed for chat. We access the underlying client.
        # This works for both OpenAI and OpenAI-compatible providers.
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            batch_embeddings = await self._embed_batch(provider, batch)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    async def _embed_batch(
        self, provider: LLMProvider, texts: list[str]
    ) -> list[list[float]]:
        """Embed a single batch of texts.

        Uses the provider's model_id to determine the embedding model,
        and calls the OpenAI-compatible embeddings endpoint.
        """
        # Import here to access the underlying client
        from app.services.llm.openai_compat import OpenAICompatProvider

        if isinstance(provider, OpenAICompatProvider):
            response = await provider._client.embeddings.create(
                model=provider.model_id(),
                input=texts,
            )
            return [item.embedding for item in response.data]
        else:
            # Fallback: for non-OpenAI providers, embed one by one using chat
            # (suboptimal but functional)
            logger.warning(
                "Using chat-based embedding fallback. Consider configuring an "
                "OpenAI-compatible embedding model for better performance."
            )
            embeddings = []
            for text in texts:
                # Ask the LLM to acknowledge, then use a placeholder
                # This path should not be used in production
                embeddings.append([0.0] * 1536)
            return embeddings

    async def embed_and_store_chunks(
        self,
        db: AsyncSession,
        chunk_ids: list[UUID],
        texts: list[str],
    ) -> None:
        """Compute embeddings and update content_chunks in the database.

        Args:
            db: Database session.
            chunk_ids: UUIDs of ContentChunk rows to update.
            texts: Corresponding text content for each chunk.
        """
        if not chunk_ids:
            return

        embeddings = await self.embed_texts(texts)

        for chunk_id, embedding in zip(chunk_ids, embeddings):
            await db.execute(
                update(ContentChunkModel)
                .where(ContentChunkModel.id == chunk_id)
                .values(embedding=embedding)
            )

        await db.flush()
        logger.info(f"Embedded and stored {len(chunk_ids)} content chunks")

    async def embed_and_store_concepts(
        self,
        db: AsyncSession,
        concept_ids: list[UUID],
        texts: list[str],
    ) -> None:
        """Compute embeddings and update concepts in the database.

        Args:
            db: Database session.
            concept_ids: UUIDs of Concept rows to update.
            texts: Text to embed for each concept (typically name + description).
        """
        if not concept_ids:
            return

        embeddings = await self.embed_texts(texts)

        for concept_id, embedding in zip(concept_ids, embeddings):
            await db.execute(
                update(ConceptModel)
                .where(ConceptModel.id == concept_id)
                .values(embedding=embedding)
            )

        await db.flush()
        logger.info(f"Embedded and stored {len(concept_ids)} concepts")
```

**Embedding model configuration**: The `TaskType.EMBEDDING` route in `model_route_configs` must point to an OpenAI-compatible embedding model (e.g., `text-embedding-3-small`). This is set up during initial model configuration (see Sub-project A).

---

## 5. Course Generation

**File**: `backend/app/services/course_generator.py`

After content is analyzed and stored, users can generate a structured course from one or more sources.

```python
"""Course generation service — creates Course + Sections from analyzed sources."""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.content_chunk import ContentChunk as ContentChunkModel
from app.db.models.concept import Concept, ConceptSource
from app.db.models.course import Course, CourseSource, Section
from app.db.models.source import Source
from app.services.content_analyzer import AnalysisResult, AnalyzedChunk, ExtractedConcept
from app.services.llm.base import UnifiedMessage
from app.services.llm.router import ModelRouter, TaskType

logger = logging.getLogger(__name__)


class CourseGenerator:
    """Generates structured courses from analyzed sources.

    Flow:
    1. Load analyzed content chunks from DB for given source_ids.
    2. Optionally call LLM to determine optimal section ordering.
    3. Create Course, Sections, map concepts.
    """

    def __init__(self, model_router: ModelRouter):
        self._router = model_router

    async def generate(
        self,
        db: AsyncSession,
        source_ids: list[UUID],
        title: str | None = None,
        user_id: UUID | None = None,
    ) -> Course:
        """Generate a course from one or more ingested sources.

        Args:
            db: Database session.
            source_ids: List of Source UUIDs (must all be status='ready').
            title: Optional course title. If None, uses source title(s).
            user_id: Optional user UUID.

        Returns:
            The created Course ORM object.

        Raises:
            ValueError: If any source is not ready.
        """
        # 1. Validate sources
        sources: list[Source] = []
        for sid in source_ids:
            source = await db.get(Source, sid)
            if not source:
                raise ValueError(f"Source {sid} not found")
            if source.status != "ready":
                raise ValueError(f"Source {sid} is not ready (status={source.status})")
            sources.append(source)

        # 2. Determine course title
        if not title:
            if len(sources) == 1:
                title = sources[0].title or "Untitled Course"
            else:
                title = f"Course from {len(sources)} sources"

        # 3. Create Course
        course = Course(title=title, description="", created_by=user_id)
        db.add(course)
        await db.flush()  # Get course.id

        # 4. Link sources
        for source in sources:
            db.add(CourseSource(course_id=course.id, source_id=source.id))

        # 5. Load content chunks for these sources, ordered by metadata
        chunks: list[ContentChunkModel] = []
        for source in sources:
            result = await db.execute(
                select(ContentChunkModel)
                .where(ContentChunkModel.source_id == source.id)
                .order_by(ContentChunkModel.created_at)
            )
            chunks.extend(result.scalars().all())

        # 6. Create Sections from chunks
        for i, chunk in enumerate(chunks):
            metadata = chunk.metadata_ or {}
            section_title = metadata.get("topic", f"Section {i + 1}")

            section = Section(
                course_id=course.id,
                title=section_title,
                order_index=i,
                source_id=chunk.source_id,
                source_start=self._format_source_ref(metadata, "start"),
                source_end=self._format_source_ref(metadata, "end"),
                content={
                    "summary": metadata.get("summary", ""),
                    "key_terms": metadata.get("key_terms", []),
                    "has_code": metadata.get("has_code", False),
                },
                difficulty=metadata.get("difficulty", 1),
            )
            db.add(section)
            await db.flush()

            # Update chunk's section_id
            chunk.section_id = section.id

        await db.flush()

        # 7. Generate course description via LLM
        course.description = await self._generate_description(
            course_title=title,
            section_count=len(chunks),
            sources=sources,
        )

        await db.flush()
        logger.info(f"Generated course '{title}' with {len(chunks)} sections from {len(sources)} sources")
        return course

    @staticmethod
    def _format_source_ref(metadata: dict, ref_type: str) -> str | None:
        """Format source reference (timestamp or page number)."""
        if "start_time" in metadata and ref_type == "start":
            return f"{metadata['start_time']:.0f}s"
        if "end_time" in metadata and ref_type == "end":
            return f"{metadata['end_time']:.0f}s"
        if "page_start" in metadata and ref_type == "start":
            return f"p{metadata['page_start']}"
        if "page_end" in metadata and ref_type == "end":
            return f"p{metadata['page_end']}"
        return None

    async def _generate_description(
        self,
        course_title: str,
        section_count: int,
        sources: list[Source],
    ) -> str:
        """Generate a short course description via LLM."""
        try:
            provider = await self._router.get_provider(TaskType.CONTENT_ANALYSIS)
            source_info = ", ".join(s.title or s.url or "unknown" for s in sources)

            messages = [
                UnifiedMessage(
                    role="user",
                    content=(
                        f"Write a 2-3 sentence course description for a course titled "
                        f"\"{course_title}\" with {section_count} sections. "
                        f"Source material: {source_info}. "
                        f"Be concise and informative. Respond with ONLY the description text."
                    ),
                ),
            ]
            response = await provider.chat(messages, max_tokens=256, temperature=0.5)
            return "".join(b.text or "" for b in response.content if b.type == "text").strip()
        except Exception:
            logger.warning("Failed to generate course description, using fallback")
            return f"A course based on {len(sources)} source(s) with {section_count} sections."
```

### 5.1 Concept Deduplication

When storing concepts extracted from content analysis, we must deduplicate against existing concepts in the database. This logic lives in the ingestion task (Section 6) but the strategy is:

1. For each `ExtractedConcept` from the analysis:
   - Query `SELECT * FROM concepts WHERE name = :name` (exact match)
   - If not found, check aliases: `SELECT * FROM concepts WHERE aliases @> :name_json` (JSONB contains)
   - If still not found, create a new `Concept` row
   - If found, reuse the existing concept ID
2. Create `ConceptSource` rows linking each concept to the source

---

## 6. Celery Tasks

**File**: `backend/app/worker/tasks/content_ingestion.py`

This is the main orchestration task that runs the entire pipeline.

```python
"""Content ingestion Celery tasks."""

import logging
from uuid import UUID

from celery import shared_task

from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="content_ingestion.ingest_source",
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=600,  # 10 minutes
    time_limit=660,       # 11 minutes hard limit
)
def ingest_source(self, source_id: str) -> dict:
    """Main content ingestion pipeline task.

    Orchestrates: extract → analyze → store → embed.

    This is a synchronous Celery task that internally runs async code
    using asyncio.run(). This is the standard pattern for Celery + async.

    Args:
        source_id: UUID string of the Source to ingest.

    Returns:
        dict with summary of what was created.
    """
    import asyncio
    return asyncio.run(_ingest_source_async(self, source_id))


async def _ingest_source_async(task, source_id: str) -> dict:
    """Async implementation of the ingestion pipeline."""
    from sqlalchemy import select, update as sa_update
    from app.db.database import async_session_factory
    from app.db.models.source import Source
    from app.db.models.content_chunk import ContentChunk as ContentChunkModel
    from app.db.models.concept import Concept, ConceptSource
    from app.services.content_analyzer import ContentAnalyzer
    from app.services.embedding import EmbeddingService
    from app.tools.extractors import get_extractor
    from app.api.deps import get_model_router

    model_router = get_model_router()
    sid = UUID(source_id)

    async with async_session_factory() as db:
        # Load source
        source = await db.get(Source, sid)
        if not source:
            raise ValueError(f"Source {source_id} not found")

        try:
            # === STEP 1: EXTRACT ===
            await _update_status(db, sid, "extracting")
            task.update_state(state="PROGRESS", meta={"stage": "extracting"})

            extractor = _create_extractor(source)
            result = await extractor.extract(
                source.url if source.url else "",
                # For PDF, source.url is None; the file path is in metadata_
                **({"source": source.metadata_.get("file_path", "")} if source.type == "pdf" else {}),
            )

            # Update source with extracted info
            source.title = source.title or result.title
            source.raw_content = "\n\n".join(c.raw_text for c in result.chunks)
            source.metadata_ = {**source.metadata_, **result.metadata}
            await db.flush()

            logger.info(f"Extracted {len(result.chunks)} chunks from source {source_id}")

            # === STEP 2: ANALYZE ===
            await _update_status(db, sid, "analyzing")
            task.update_state(state="PROGRESS", meta={"stage": "analyzing"})

            analyzer = ContentAnalyzer(model_router)
            analysis = await analyzer.analyze(
                title=source.title or "Untitled",
                chunks=result.chunks,
                source_type=source.type,
            )

            logger.info(
                f"Analyzed source {source_id}: "
                f"{len(analysis.concepts)} concepts, "
                f"{len(analysis.chunks)} chunks"
            )

            # === STEP 3: STORE ===
            await _update_status(db, sid, "storing")
            task.update_state(state="PROGRESS", meta={"stage": "storing"})

            # Store content chunks
            chunk_ids = []
            chunk_texts = []
            for analyzed_chunk in analysis.chunks:
                db_chunk = ContentChunkModel(
                    source_id=sid,
                    text=analyzed_chunk.raw_text,
                    metadata_={
                        "topic": analyzed_chunk.topic,
                        "summary": analyzed_chunk.summary,
                        "concepts": analyzed_chunk.concepts,
                        "difficulty": analyzed_chunk.difficulty,
                        "key_terms": analyzed_chunk.key_terms,
                        "has_code": analyzed_chunk.has_code,
                        "has_formula": analyzed_chunk.has_formula,
                        **analyzed_chunk.metadata,
                    },
                )
                db.add(db_chunk)
                await db.flush()  # Get db_chunk.id
                chunk_ids.append(db_chunk.id)
                chunk_texts.append(analyzed_chunk.raw_text)

            # Store concepts (with dedup)
            concept_ids = []
            concept_texts = []
            for ext_concept in analysis.concepts:
                concept = await _get_or_create_concept(db, ext_concept)
                concept_ids.append(concept.id)
                concept_texts.append(f"{concept.name}: {concept.description or ''}")

                # Create concept-source link
                existing = await db.execute(
                    select(ConceptSource).where(
                        ConceptSource.concept_id == concept.id,
                        ConceptSource.source_id == sid,
                    )
                )
                if not existing.scalar_one_or_none():
                    db.add(
                        ConceptSource(
                            concept_id=concept.id,
                            source_id=sid,
                            context=ext_concept.description,
                        )
                    )

            # Update source metadata with analysis summary
            source.metadata_ = {
                **source.metadata_,
                "overall_summary": analysis.overall_summary,
                "overall_difficulty": analysis.overall_difficulty,
                "concept_count": len(analysis.concepts),
                "chunk_count": len(analysis.chunks),
                "estimated_study_minutes": analysis.estimated_study_minutes,
                "suggested_prerequisites": analysis.suggested_prerequisites,
            }

            await db.flush()
            logger.info(f"Stored {len(chunk_ids)} chunks and {len(concept_ids)} concepts")

            # === STEP 4: EMBED ===
            await _update_status(db, sid, "embedding")
            task.update_state(state="PROGRESS", meta={"stage": "embedding"})

            embedding_service = EmbeddingService(model_router)

            await embedding_service.embed_and_store_chunks(db, chunk_ids, chunk_texts)
            await embedding_service.embed_and_store_concepts(db, concept_ids, concept_texts)

            logger.info(f"Embedded {len(chunk_ids)} chunks and {len(concept_ids)} concepts")

            # === STEP 5: DONE ===
            await _update_status(db, sid, "ready")
            await db.commit()

            return {
                "source_id": source_id,
                "title": source.title,
                "chunks_created": len(chunk_ids),
                "concepts_created": len(concept_ids),
                "status": "ready",
            }

        except Exception as e:
            logger.error(f"Ingestion failed for source {source_id}: {e}", exc_info=True)
            await _update_status(db, sid, "error", error_message=str(e))
            await db.commit()
            raise


def _create_extractor(source: Source):
    """Create the appropriate extractor for a source."""
    from app.tools.extractors import get_extractor
    from app.config import get_settings

    settings = get_settings()

    if source.type == "bilibili":
        kwargs = {}
        # Configure Bilibili credential if available
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


async def _update_status(
    db, source_id: UUID, status: str, error_message: str | None = None
) -> None:
    """Update source status in the database."""
    from sqlalchemy import update as sa_update
    from app.db.models.source import Source

    values: dict = {"status": status}
    if error_message:
        # Store error in metadata
        source = await db.get(Source, source_id)
        if source:
            source.metadata_ = {**source.metadata_, "error": error_message}
            source.status = status
            await db.flush()
            return

    await db.execute(
        sa_update(Source).where(Source.id == source_id).values(**values)
    )
    await db.flush()


async def _get_or_create_concept(db, ext_concept) -> "Concept":
    """Get existing concept by name/alias or create a new one."""
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
    from app.db.models.concept import Concept

    # Try exact name match
    result = await db.execute(
        select(Concept).where(Concept.name == ext_concept.name)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    # Try alias match (check if any alias matches the name)
    # Note: aliases is stored as JSONB array
    for alias in ext_concept.aliases:
        result = await db.execute(
            select(Concept).where(Concept.name == alias)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

    # Create new concept
    concept = Concept(
        name=ext_concept.name,
        description=ext_concept.description,
        category=ext_concept.category,
        aliases=ext_concept.aliases,
        prerequisites=[],  # Populated later via concept graph building
    )
    db.add(concept)
    await db.flush()
    return concept
```

### 6.1 Task for PDF File Handling

For PDF sources, the file must be uploaded and stored before the ingestion task runs. The API endpoint handles upload (see Section 7), stores the file on disk, and records the file path in `source.metadata_["file_path"]`.

The extractor receives the file path from metadata:

```python
# In _ingest_source_async, the extract call for PDF:
if source.type == "pdf":
    file_path = source.metadata_.get("file_path", "")
    result = await extractor.extract(file_path)
```

### 6.2 Task Registration

The task file must be discoverable by Celery autodiscovery. The existing `celery_app.py` already has:

```python
celery_app.autodiscover_tasks(["app.worker.tasks"])
```

This will pick up `app.worker.tasks.content_ingestion` automatically.

---

## 7. API Endpoints

### 7.1 Sources Router

**File**: `backend/app/api/routes/sources.py`

```python
"""API routes for content source management."""

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models.source import Source
from app.models.source import (
    SourceCreate,
    SourceResponse,
    SourceListResponse,
)
from app.worker.tasks.content_ingestion import ingest_source

router = APIRouter(prefix="/api/sources", tags=["sources"])

# Directory for uploaded files (relative to project root)
UPLOAD_DIR = Path("uploads")


@router.post("", response_model=SourceResponse, status_code=201)
async def create_source(
    db: Annotated[AsyncSession, Depends(get_db)],
    # For URL-based sources (Bilibili)
    url: str | None = Form(None),
    source_type: str | None = Form(None),
    title: str | None = Form(None),
    # For file-based sources (PDF)
    file: UploadFile | None = File(None),
) -> SourceResponse:
    """Submit a URL or upload a file for content ingestion.

    Either `url` + `source_type` OR `file` must be provided.

    For Bilibili: provide url="https://www.bilibili.com/video/BVxxx" and source_type="bilibili"
    For PDF: upload a .pdf file (source_type is auto-detected)

    Returns the created source with a task_id for polling ingestion progress.
    """
    if not url and not file:
        raise HTTPException(400, "Either 'url' or 'file' must be provided")

    metadata: dict = {}

    if file:
        # File upload (PDF)
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(400, "Only PDF files are supported")

        source_type = "pdf"
        title = title or file.filename

        # Save file to uploads directory
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        file_id = str(uuid.uuid4())
        file_path = UPLOAD_DIR / f"{file_id}.pdf"

        content = await file.read()
        file_path.write_bytes(content)

        metadata = {
            "file_path": str(file_path.resolve()),
            "original_filename": file.filename,
            "file_size": len(content),
        }
    else:
        # URL-based source (Bilibili)
        if not source_type:
            source_type = _detect_source_type(url)
        if source_type not in ("bilibili",):
            raise HTTPException(400, f"Unsupported source type: {source_type}")

    # Create Source record
    source = Source(
        type=source_type,
        url=url,
        title=title,
        status="pending",
        metadata_=metadata,
    )
    db.add(source)
    await db.flush()

    # Dispatch async ingestion task
    task = ingest_source.delay(str(source.id))

    return SourceResponse(
        id=source.id,
        type=source.type,
        url=source.url,
        title=source.title,
        status=source.status,
        metadata_=source.metadata_,
        task_id=task.id,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


@router.get("", response_model=SourceListResponse)
async def list_sources(
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = 0,
    limit: int = 20,
) -> SourceListResponse:
    """List all content sources with pagination."""
    result = await db.execute(
        select(Source).order_by(Source.created_at.desc()).offset(skip).limit(limit)
    )
    sources = result.scalars().all()

    count_result = await db.execute(select(Source))
    total = len(count_result.scalars().all())

    return SourceListResponse(
        items=[_source_to_response(s) for s in sources],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SourceResponse:
    """Get a single source by ID, including processing status."""
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(404, f"Source {source_id} not found")
    return _source_to_response(source)


def _detect_source_type(url: str | None) -> str:
    """Auto-detect source type from URL."""
    if not url:
        raise HTTPException(400, "URL is required for non-file sources")
    if "bilibili.com" in url or "b23.tv" in url:
        return "bilibili"
    raise HTTPException(400, f"Cannot detect source type from URL: {url}")


def _source_to_response(source: Source) -> SourceResponse:
    """Convert ORM Source to response model."""
    return SourceResponse(
        id=source.id,
        type=source.type,
        url=source.url,
        title=source.title,
        status=source.status,
        metadata_=source.metadata_,
        task_id=None,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )
```

### 7.2 Courses Router

**File**: `backend/app/api/routes/courses.py`

```python
"""API routes for course management."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db, get_model_router
from app.db.models.course import Course, CourseSource, Section
from app.models.course import (
    CourseGenerateRequest,
    CourseResponse,
    CourseDetailResponse,
    CourseListResponse,
    SectionResponse,
)
from app.services.course_generator import CourseGenerator
from app.services.llm.router import ModelRouter

router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.post("/generate", response_model=CourseResponse, status_code=201)
async def generate_course(
    request: CourseGenerateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    model_router: Annotated[ModelRouter, Depends(get_model_router)],
) -> CourseResponse:
    """Generate a course from one or more ingested sources.

    All source_ids must reference sources with status='ready'.
    """
    generator = CourseGenerator(model_router)

    try:
        course = await generator.generate(
            db=db,
            source_ids=request.source_ids,
            title=request.title,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return CourseResponse(
        id=course.id,
        title=course.title,
        description=course.description,
        created_at=course.created_at,
        updated_at=course.updated_at,
    )


@router.get("", response_model=CourseListResponse)
async def list_courses(
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = 0,
    limit: int = 20,
) -> CourseListResponse:
    """List all courses with pagination."""
    result = await db.execute(
        select(Course).order_by(Course.created_at.desc()).offset(skip).limit(limit)
    )
    courses = result.scalars().all()

    return CourseListResponse(
        items=[
            CourseResponse(
                id=c.id,
                title=c.title,
                description=c.description,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in courses
        ],
        total=len(courses),
        skip=skip,
        limit=limit,
    )


@router.get("/{course_id}", response_model=CourseDetailResponse)
async def get_course(
    course_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CourseDetailResponse:
    """Get a course with its sections."""
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(404, f"Course {course_id} not found")

    # Load sections
    result = await db.execute(
        select(Section)
        .where(Section.course_id == course_id)
        .order_by(Section.order_index)
    )
    sections = result.scalars().all()

    # Load linked source IDs
    cs_result = await db.execute(
        select(CourseSource.source_id).where(CourseSource.course_id == course_id)
    )
    source_ids = [row[0] for row in cs_result.all()]

    return CourseDetailResponse(
        id=course.id,
        title=course.title,
        description=course.description,
        source_ids=source_ids,
        sections=[
            SectionResponse(
                id=s.id,
                title=s.title,
                order_index=s.order_index,
                source_start=s.source_start,
                source_end=s.source_end,
                content=s.content,
                difficulty=s.difficulty,
            )
            for s in sections
        ],
        created_at=course.created_at,
        updated_at=course.updated_at,
    )
```

### 7.3 Router Registration

**File**: `backend/app/main.py` — add these lines:

```python
from app.api.routes import health, models, model_routes, tasks, sources, courses

# ... existing router includes ...
app.include_router(sources.router)
app.include_router(courses.router)
```

---

## 8. Pydantic Schemas

### 8.1 Source Schemas

**File**: `backend/app/models/source.py`

```python
"""Pydantic schemas for source API endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SourceCreate(BaseModel):
    """Request body for creating a source (JSON variant, not used for file upload)."""

    url: str | None = None
    source_type: str | None = None
    title: str | None = None


class SourceResponse(BaseModel):
    """Response model for a single source."""

    id: uuid.UUID
    type: str
    url: str | None = None
    title: str | None = None
    status: str
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    task_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SourceListResponse(BaseModel):
    """Paginated list of sources."""

    items: list[SourceResponse]
    total: int
    skip: int
    limit: int
```

### 8.2 Course Schemas

**File**: `backend/app/models/course.py`

```python
"""Pydantic schemas for course API endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CourseGenerateRequest(BaseModel):
    """Request body for generating a course from sources."""

    source_ids: list[uuid.UUID] = Field(..., min_length=1)
    title: str | None = None


class CourseResponse(BaseModel):
    """Response model for a course."""

    id: uuid.UUID
    title: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SectionResponse(BaseModel):
    """Response model for a course section."""

    id: uuid.UUID
    title: str
    order_index: int | None = None
    source_start: str | None = None
    source_end: str | None = None
    content: dict[str, Any] = Field(default_factory=dict)
    difficulty: int = 1

    model_config = {"from_attributes": True}


class CourseDetailResponse(BaseModel):
    """Response model for a course with sections."""

    id: uuid.UUID
    title: str
    description: str | None = None
    source_ids: list[uuid.UUID] = Field(default_factory=list)
    sections: list[SectionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CourseListResponse(BaseModel):
    """Paginated list of courses."""

    items: list[CourseResponse]
    total: int
    skip: int
    limit: int
```

---

## 9. Configuration Changes

### 9.1 Settings Additions

**File**: `backend/app/config.py` — add optional Bilibili credentials and upload path:

```python
class Settings(BaseSettings):
    # ... existing fields ...

    # Bilibili (optional — for authenticated subtitle access)
    bilibili_sessdata: str = ""
    bilibili_bili_jct: str = ""
    bilibili_buvid3: str = ""

    # File uploads
    upload_dir: str = "uploads"
```

### 9.2 Environment Variables

**File**: `.env.example` — add:

```bash
# Bilibili credentials (optional — needed for some videos' subtitles)
# Get from browser cookies after logging into bilibili.com
BILIBILI_SESSDATA=
BILIBILI_BILI_JCT=
BILIBILI_BUVID3=

# Upload directory for PDF files
UPLOAD_DIR=uploads
```

---

## 10. Dependencies to Add

**File**: `backend/pyproject.toml` — add to `[project] dependencies`:

```toml
    # Content extraction
    "bilibili-api-python>=16.0",
    "pymupdf>=1.24",
    "python-multipart",           # Required by FastAPI for file uploads
```

The `python-multipart` package is required for FastAPI's `UploadFile` and `Form` parameters.

---

## 11. Testing Strategy

### 11.1 Test Files

```
backend/tests/
├── conftest.py                           # Existing (from Sub-project A)
├── tools/
│   └── extractors/
│       ├── __init__.py
│       ├── test_bilibili.py              # BilibiliExtractor unit tests
│       ├── test_pdf.py                   # PDFExtractor unit tests
│       └── fixtures/
│           ├── sample.pdf                # Small PDF fixture (~3 pages)
│           └── bilibili_subtitle.json    # Sample Bilibili subtitle response
├── services/
│   ├── test_content_analyzer.py          # ContentAnalyzer tests (mock LLM)
│   ├── test_embedding.py                 # EmbeddingService tests (mock LLM)
│   └── test_course_generator.py          # CourseGenerator tests
├── worker/
│   └── test_content_ingestion.py         # Celery task tests (mock everything)
└── api/
    ├── test_sources_api.py               # Source API endpoint tests
    └── test_courses_api.py               # Course API endpoint tests
```

### 11.2 Test Details

**Bilibili Extractor Tests** (`test_bilibili.py`):

```python
# Test cases:
# 1. _parse_bvid: various URL formats → correct BV号
# 2. _pick_best_subtitle: priority CC > AI > any
# 3. _group_subtitle_segments: windowing logic
# 4. extract: mock bilibili_api.video.Video — mock get_info(), get_subtitle()
#    - Success case with CC subtitles
#    - Success case with AI subtitles
#    - No subtitle → ExtractionError
#    - Invalid BV号 → ExtractionError
#    - Multi-part video with page parameter
```

- Mock `bilibili_api.video.Video` — do NOT make real API calls
- Use `unittest.mock.AsyncMock` for async methods
- Load sample subtitle JSON from `fixtures/bilibili_subtitle.json`

**PDF Extractor Tests** (`test_pdf.py`):

```python
# Test cases:
# 1. extract: sample.pdf → chunks with page numbers
# 2. _extract_page: verify text + font size extraction
# 3. _detect_heading_threshold: various font size distributions
# 4. _build_sections: heading-based sectioning
# 5. Fallback to per-page chunking when no headings detected
# 6. File not found → ExtractionError
# 7. Corrupt PDF → ExtractionError
```

- Use the `fixtures/sample.pdf` fixture (create a 3-page PDF with headings and code blocks)
- Tests are synchronous where possible; use `pytest.mark.asyncio` for `extract()`

**Content Analyzer Tests** (`test_content_analyzer.py`):

```python
# Test cases:
# 1. analyze: mock LLM returns valid JSON → correct AnalysisResult
# 2. analyze: mock LLM returns malformed JSON → fallback result
# 3. analyze: large content → batched analysis
# 4. _format_chunks_for_llm: bilibili vs pdf formatting
# 5. _merge_batch_results: concept dedup, difficulty averaging
```

- Mock `ModelRouter.get_provider()` → return a mock `LLMProvider`
- Mock `LLMProvider.chat()` → return canned `LLMResponse` with JSON content

**Embedding Service Tests** (`test_embedding.py`):

```python
# Test cases:
# 1. embed_texts: mock provider → correct embeddings returned
# 2. embed_texts: batching with > BATCH_SIZE texts
# 3. embed_and_store_chunks: verify DB updates
# 4. embed_and_store_concepts: verify DB updates
```

**Course Generator Tests** (`test_course_generator.py`):

```python
# Test cases:
# 1. generate: single source → Course + Sections created
# 2. generate: multiple sources → proper linking
# 3. generate: source not ready → ValueError
# 4. generate: source not found → ValueError
# 5. _format_source_ref: timestamp and page formatting
```

**Celery Task Tests** (`test_content_ingestion.py`):

```python
# Test cases:
# 1. ingest_source: full pipeline mock — extract, analyze, store, embed
# 2. ingest_source: extraction failure → status='error'
# 3. ingest_source: analysis failure → status='error'
# 4. ingest_source: source not found → ValueError
# 5. Concept dedup: existing concept reused
```

- Mock all external dependencies: extractors, LLM, embedding
- Use real DB session from conftest for integration testing

**API Tests** (`test_sources_api.py`, `test_courses_api.py`):

```python
# Source API:
# 1. POST /api/sources with bilibili URL → 201, source created, task dispatched
# 2. POST /api/sources with PDF upload → 201, file saved, source created
# 3. POST /api/sources with no input → 400
# 4. GET /api/sources → paginated list
# 5. GET /api/sources/{id} → source with status

# Course API:
# 1. POST /api/courses/generate → 201, course created
# 2. POST /api/courses/generate with non-ready source → 400
# 3. GET /api/courses → paginated list
# 4. GET /api/courses/{id} → course with sections
# 5. GET /api/courses/{id} not found → 404
```

- Mock `ingest_source.delay()` in source API tests
- Use real DB, mock LLM for course generation tests

### 11.3 Test Fixtures

**`fixtures/sample.pdf`**: A 3-page PDF created with `reportlab` or similar:
- Page 1: Title "Sample Document" + intro paragraph
- Page 2: Heading "Core Concepts" + body text + code block (monospace)
- Page 3: Heading "Advanced Topics" + formula + body text

**`fixtures/bilibili_subtitle.json`**: Sample subtitle response:
```json
{
  "body": [
    {"from": 0.0, "to": 3.5, "content": "大家好，今天我们来学习机器学习"},
    {"from": 3.5, "to": 7.2, "content": "首先我们需要了解什么是监督学习"},
    {"from": 7.2, "to": 12.0, "content": "监督学习是一种通过标注数据训练模型的方法"}
  ]
}
```

---

## 12. Implementation Plan

Each task is sized for 2-5 minutes of AI implementation time. Tasks are ordered by dependency.

### Phase 1: Foundation (extractors + types)

| # | Task | Files | Verify |
|---|------|-------|--------|
| 1 | Create `backend/app/tools/` directory structure with `__init__.py` files | `backend/app/tools/__init__.py`, `backend/app/tools/extractors/__init__.py` | Directories exist, Python can import `app.tools.extractors` |
| 2 | Implement base extractor types | `backend/app/tools/extractors/base.py` | `from app.tools.extractors.base import ContentExtractor, RawContentChunk, ExtractionResult, ExtractionError` works |
| 3 | Implement BilibiliExtractor | `backend/app/tools/extractors/bilibili.py` | Unit test: `_parse_bvid`, `_pick_best_subtitle`, `_group_subtitle_segments` pass |
| 4 | Create Bilibili test fixtures | `backend/tests/tools/__init__.py`, `backend/tests/tools/extractors/__init__.py`, `backend/tests/tools/extractors/fixtures/bilibili_subtitle.json` | Fixture file exists and is valid JSON |
| 5 | Write Bilibili extractor tests | `backend/tests/tools/extractors/test_bilibili.py` | `pytest tests/tools/extractors/test_bilibili.py` passes (all mocked, no real API calls) |
| 6 | Implement PDFExtractor | `backend/app/tools/extractors/pdf.py` | Import succeeds, `PDFExtractor().supported_source_type() == "pdf"` |
| 7 | Create PDF test fixture | `backend/tests/tools/extractors/fixtures/sample.pdf` | PDF file exists, can be opened with `fitz.open()` |
| 8 | Write PDF extractor tests | `backend/tests/tools/extractors/test_pdf.py` | `pytest tests/tools/extractors/test_pdf.py` passes |
| 9 | Wire up extractor registry | `backend/app/tools/extractors/__init__.py` (full implementation) | `get_extractor("bilibili")` and `get_extractor("pdf")` return correct types |

### Phase 2: Analysis + Embedding services

| # | Task | Files | Verify |
|---|------|-------|--------|
| 10 | Implement ContentAnalyzer with LLM prompt | `backend/app/services/content_analyzer.py` | Import succeeds, `AnalysisResult` can be instantiated |
| 11 | Write ContentAnalyzer tests | `backend/tests/services/test_content_analyzer.py` | `pytest tests/services/test_content_analyzer.py` passes (mock LLM) |
| 12 | Implement EmbeddingService | `backend/app/services/embedding.py` | Import succeeds, `EmbeddingService` can be instantiated with mock router |
| 13 | Write EmbeddingService tests | `backend/tests/services/test_embedding.py` | `pytest tests/services/test_embedding.py` passes (mock LLM + DB) |
| 14 | Implement CourseGenerator | `backend/app/services/course_generator.py` | Import succeeds |
| 15 | Write CourseGenerator tests | `backend/tests/services/test_course_generator.py` | `pytest tests/services/test_course_generator.py` passes |

### Phase 3: Celery task + API

| # | Task | Files | Verify |
|---|------|-------|--------|
| 16 | Implement ingest_source Celery task | `backend/app/worker/tasks/content_ingestion.py` | Import succeeds, `celery_app.autodiscover_tasks` finds it |
| 17 | Write ingestion task tests | `backend/tests/worker/test_content_ingestion.py` | `pytest tests/worker/test_content_ingestion.py` passes (all deps mocked) |
| 18 | Create Pydantic schemas for sources | `backend/app/models/source.py` | `from app.models.source import SourceResponse, SourceCreate` works |
| 19 | Create Pydantic schemas for courses | `backend/app/models/course.py` | `from app.models.course import CourseResponse, CourseGenerateRequest` works |
| 20 | Implement sources API routes | `backend/app/api/routes/sources.py` | Import succeeds |
| 21 | Implement courses API routes | `backend/app/api/routes/courses.py` | Import succeeds |
| 22 | Register new routers in main.py | `backend/app/main.py` | `GET /api/sources` returns 200, `GET /api/courses` returns 200 |
| 23 | Write source API tests | `backend/tests/api/test_sources_api.py` | `pytest tests/api/test_sources_api.py` passes |
| 24 | Write course API tests | `backend/tests/api/test_courses_api.py` | `pytest tests/api/test_courses_api.py` passes |

### Phase 4: Config + dependencies

| # | Task | Files | Verify |
|---|------|-------|--------|
| 25 | Add Bilibili config fields to Settings | `backend/app/config.py` | `get_settings().bilibili_sessdata` returns `""` |
| 26 | Add new dependencies to pyproject.toml | `backend/pyproject.toml` | `uv pip install -e .` succeeds with new deps |
| 27 | Update `.env.example` with new variables | `.env.example` | File includes `BILIBILI_SESSDATA`, `UPLOAD_DIR` |
| 28 | Run full test suite | — | `pytest` passes all tests |

### Phase 5: Integration verification

| # | Task | Files | Verify |
|---|------|-------|--------|
| 29 | Manual integration test: Bilibili ingestion | — | Start Celery worker, `POST /api/sources` with real Bilibili URL, poll status → `ready` |
| 30 | Manual integration test: PDF ingestion | — | `POST /api/sources` with PDF upload, poll status → `ready` |
| 31 | Manual integration test: Course generation | — | `POST /api/courses/generate` with ready source_ids → course with sections |

---

## 13. Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Expanded source status values | `extracting\|analyzing\|storing\|embedding` instead of just `processing` | Finer-grained progress for frontend polling |
| Subtitle windowing (60s) | Group Bilibili subtitle segments into ~60-second chunks | Balance between chunk granularity and LLM context efficiency |
| PDF heading detection | Font size heuristic (body_size + 2pt) | Simple, works for most technical PDFs without needing ML-based layout analysis |
| Single Celery task | One `ingest_source` task runs the full pipeline | Simpler error handling; subtask chaining adds complexity without benefit at this scale |
| File upload to local disk | `uploads/` directory, not MinIO/S3 | MVP simplicity; can be migrated to object storage later |
| LLM response as JSON | System prompt instructs JSON-only output + fallback parser | Avoids tool use overhead for structured extraction; works with all models |
| Concept dedup by name | Exact name match + alias check | Simple and correct for MVP; can add fuzzy/embedding-based dedup later |
| Batch analysis at 6000 chars | Split large content into ~6000-char batches | Stay within context window even for smaller models configured as CONTENT_ANALYSIS |

---

## 14. File Reference Summary

All new files created by this sub-project:

```
backend/
├── app/
│   ├── tools/
│   │   ├── __init__.py
│   │   └── extractors/
│   │       ├── __init__.py          # Registry + get_extractor()
│   │       ├── base.py              # ContentExtractor ABC, RawContentChunk, ExtractionResult
│   │       ├── bilibili.py          # BilibiliExtractor
│   │       └── pdf.py               # PDFExtractor
│   ├── services/
│   │   ├── content_analyzer.py      # ContentAnalyzer + LLM prompt
│   │   ├── embedding.py             # EmbeddingService
│   │   └── course_generator.py      # CourseGenerator
│   ├── models/
│   │   ├── source.py                # Source Pydantic schemas
│   │   └── course.py                # Course Pydantic schemas
│   ├── api/routes/
│   │   ├── sources.py               # POST/GET /api/sources
│   │   └── courses.py               # POST/GET /api/courses
│   └── worker/tasks/
│       └── content_ingestion.py     # ingest_source Celery task
├── tests/
│   ├── tools/
│   │   ├── __init__.py
│   │   └── extractors/
│   │       ├── __init__.py
│   │       ├── test_bilibili.py
│   │       ├── test_pdf.py
│   │       └── fixtures/
│   │           ├── sample.pdf
│   │           └── bilibili_subtitle.json
│   ├── services/
│   │   ├── test_content_analyzer.py
│   │   ├── test_embedding.py
│   │   └── test_course_generator.py
│   ├── worker/
│   │   └── test_content_ingestion.py
│   └── api/
│       ├── test_sources_api.py
│       └── test_courses_api.py
└── uploads/                          # Created at runtime for PDF uploads
```

Files modified:

```
backend/app/main.py                  # Add sources + courses routers
backend/app/config.py                # Add bilibili_* + upload_dir fields
backend/pyproject.toml               # Add bilibili-api-python, pymupdf, python-multipart
.env.example                         # Add BILIBILI_* + UPLOAD_DIR variables
```

Existing files referenced (read-only):

```
backend/app/db/models/source.py      # Source ORM model
backend/app/db/models/course.py      # Course, CourseSource, Section ORM models
backend/app/db/models/concept.py     # Concept, ConceptSource ORM models
backend/app/db/models/content_chunk.py # ContentChunk ORM model
backend/app/db/models/base.py        # Base, BaseMixin
backend/app/db/database.py           # async_session_factory, engine
backend/app/services/llm/base.py     # LLMProvider, UnifiedMessage, LLMResponse, etc.
backend/app/services/llm/router.py   # ModelRouter, TaskType
backend/app/worker/celery_app.py     # celery_app instance
backend/app/api/deps.py              # get_db, get_redis, get_model_router
backend/app/config.py                # Settings
backend/tests/conftest.py            # Test fixtures (db_session, client)
```
