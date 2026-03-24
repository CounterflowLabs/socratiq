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
