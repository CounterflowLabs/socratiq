import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.db.models.base import Base, BaseMixin


class Concept(BaseMixin, Base):
    __tablename__ = "concepts"

    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    aliases: Mapped[dict] = mapped_column(JSONB, server_default="[]")
    prerequisites: Mapped[list] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), server_default="{}"
    )
    embedding = mapped_column(Vector(1536), nullable=True)


class ConceptSource(Base):
    __tablename__ = "concept_sources"

    concept_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("concepts.id"), primary_key=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sources.id"), primary_key=True
    )
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
