import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, BaseMixin


class Course(BaseMixin, Base):
    __tablename__ = "courses"

    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("courses.id"), nullable=True
    )
    regeneration_directive: Mapped[str | None] = mapped_column(Text, nullable=True)
    regeneration_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    active_regeneration_task_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )


class CourseSource(Base):
    __tablename__ = "course_sources"

    course_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("courses.id"), primary_key=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sources.id"), primary_key=True
    )


class Section(BaseMixin, Base):
    __tablename__ = "sections"

    course_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    order_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sources.id"), nullable=True
    )
    source_start: Mapped[str | None] = mapped_column(String, nullable=True)
    source_end: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
