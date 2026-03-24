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
