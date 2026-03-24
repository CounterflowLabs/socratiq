"""Course generation service — creates Course + Sections from analyzed sources."""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.content_chunk import ContentChunk as ContentChunkModel
from app.db.models.course import Course, CourseSource, Section
from app.db.models.source import Source
from app.services.llm.base import UnifiedMessage
from app.services.llm.router import ModelRouter, TaskType

logger = logging.getLogger(__name__)


class CourseGenerator:
    """Generates structured courses from analyzed sources."""

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
            title: Optional course title.
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
        await db.flush()

        # 4. Link sources
        for source in sources:
            db.add(CourseSource(course_id=course.id, source_id=source.id))

        # 5. Load content chunks for these sources
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
        self, course_title: str, section_count: int, sources: list[Source],
    ) -> str:
        try:
            provider = await self._router.get_provider(TaskType.CONTENT_ANALYSIS)
            source_info = ", ".join(s.title or s.url or "unknown" for s in sources)
            messages = [
                UnifiedMessage(
                    role="user",
                    content=(
                        f'Write a 2-3 sentence course description for a course titled '
                        f'"{course_title}" with {section_count} sections. '
                        f'Source material: {source_info}. '
                        f'Be concise and informative. Respond with ONLY the description text.'
                    ),
                ),
            ]
            response = await provider.chat(messages, max_tokens=256, temperature=0.5)
            return "".join(b.text or "" for b in response.content if b.type == "text").strip()
        except Exception:
            logger.warning("Failed to generate course description, using fallback")
            return f"A course based on {len(sources)} source(s) with {section_count} sections."
