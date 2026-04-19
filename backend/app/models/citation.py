"""Citation schema for source attribution in mentor responses."""

from pydantic import BaseModel


class Citation(BaseModel):
    """A reference to a specific chunk in source material."""

    chunk_id: str
    source_id: str | None = None
    source_title: str | None = None
    source_type: str | None = None
    source_url: str | None = None
    text: str
    start_time: float | None = None
    end_time: float | None = None
    page_start: int | None = None
