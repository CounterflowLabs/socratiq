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
