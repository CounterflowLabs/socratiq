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

    @staticmethod
    def _resolve_asset_plan(metadata: dict) -> dict:
        """Return an asset plan, preserving legacy inline labs when needed."""
        asset_plan = metadata.get("asset_plan")
        if asset_plan:
            return asset_plan
        if metadata.get("labs_by_page"):
            return {"lab_mode": "inline"}
        return {"lab_mode": "none"}

    async def generate(
        self,
        db: AsyncSession,
        source_ids: list[UUID],
        title: str | None = None,
        user_id: UUID | None = None,
        skip_ready_check: bool = False,
    ) -> Course:
        """Generate a course from one or more ingested sources.

        Args:
            db: Database session.
            source_ids: List of Source UUIDs (must all be status='ready').
            title: Optional course title.
            user_id: Optional user UUID.
            skip_ready_check: Allows internal pipelines to assemble a course
                before the source is marked fully ready for external callers.

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
            if not skip_ready_check and source.status != "ready":
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

        # 6. Create Sections from chunks — group by page_index if present
        # Collect per-source lesson/lab data
        source_lesson_map: dict[UUID, dict] = {}
        source_lab_map: dict[UUID, dict] = {}
        source_asset_plan_map: dict[UUID, dict] = {}
        source_graph_map: dict[UUID, dict] = {}
        for source in sources:
            smeta = source.metadata_ or {}
            source_asset_plan_map[source.id] = self._resolve_asset_plan(smeta)
            source_graph_map[source.id] = smeta.get("graph_by_page", {})
            source_lesson_map[source.id] = smeta.get("lesson_by_page", {})
            source_lab_map[source.id] = smeta.get("labs_by_page", {})

        # Determine whether any chunks carry page_index metadata
        has_page_index = any(
            (c.metadata_ or {}).get("page_index") is not None for c in chunks
        )

        if has_page_index:
            # Group chunks by (source_id, page_index) and create one section per page group
            from collections import defaultdict
            page_groups: dict[tuple, list[ContentChunkModel]] = defaultdict(list)
            for chunk in chunks:
                metadata = chunk.metadata_ or {}
                page_idx = metadata.get("page_index", 0)
                page_groups[(chunk.source_id, page_idx)].append(chunk)

            section_order = 0
            for (source_id, page_idx), group_chunks in sorted(
                page_groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])
            ):
                first_meta = group_chunks[0].metadata_ or {}
                section_title = (
                    first_meta.get("page_title")
                    or first_meta.get("topic")
                    or f"Section {section_order + 1}"
                )

                # Use lesson content from source metadata if available
                lesson_data = source_lesson_map.get(source_id, {}).get(str(page_idx), {})
                asset_plan = source_asset_plan_map.get(source_id, {"lab_mode": "none"})
                graph_card = source_graph_map.get(source_id, {}).get(str(page_idx))
                section_content = {
                    "summary": lesson_data.get("summary") or first_meta.get("summary", ""),
                    "key_terms": lesson_data.get("sections", [{}])[0].get(
                        "key_concepts", first_meta.get("key_terms", [])
                    ) if lesson_data.get("sections") else first_meta.get("key_terms", []),
                    "has_code": any((c.metadata_ or {}).get("has_code") for c in group_chunks),
                    "lab_mode": asset_plan.get("lab_mode", "none"),
                    "graph_card": graph_card,
                    **({"lesson": lesson_data} if lesson_data else {}),
                }

                section = Section(
                    course_id=course.id,
                    title=section_title,
                    order_index=section_order,
                    source_id=source_id,
                    source_start=self._format_source_ref(first_meta, "start"),
                    source_end=self._format_source_ref(
                        (group_chunks[-1].metadata_ or {}), "end"
                    ),
                    content=section_content,
                    difficulty=first_meta.get("difficulty", 1),
                )
                db.add(section)
                await db.flush()
                for chunk in group_chunks:
                    chunk.section_id = section.id

                # Create Lab row if lab data is available for this page
                lab_data = source_lab_map.get(source_id, {}).get(str(page_idx))
                if asset_plan.get("lab_mode") == "inline" and lab_data:
                    await self._create_lab(db, section.id, lab_data)

                section_order += 1
        else:
            # No page grouping: one section per chunk (original behaviour)
            for i, chunk in enumerate(chunks):
                metadata = chunk.metadata_ or {}
                section_title = metadata.get("topic", f"Section {i + 1}")

                lesson_data = source_lesson_map.get(chunk.source_id, {}).get("0", {})
                asset_plan = source_asset_plan_map.get(chunk.source_id, {"lab_mode": "none"})
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
                        "lab_mode": asset_plan.get("lab_mode", "none"),
                        "graph_card": source_graph_map.get(chunk.source_id, {}).get("0"),
                        **({"lesson": lesson_data} if lesson_data else {}),
                    },
                    difficulty=metadata.get("difficulty", 1),
                )
                db.add(section)
                await db.flush()
                chunk.section_id = section.id

            # Create a single lab per source if available (use page 0)
            created_lab_sources: set[UUID] = set()
            for chunk in chunks:
                src_id = chunk.source_id
                if src_id in created_lab_sources:
                    continue
                lab_data = source_lab_map.get(src_id, {}).get("0")
                asset_plan = source_asset_plan_map.get(src_id, {"lab_mode": "none"})
                if asset_plan.get("lab_mode") == "inline" and lab_data and chunk.section_id:
                    await self._create_lab(db, chunk.section_id, lab_data)
                    created_lab_sources.add(src_id)

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
    async def _create_lab(db: AsyncSession, section_id: UUID, lab_data: dict) -> None:
        """Create a Lab ORM row for a section from generated lab data.

        Args:
            db: Database session.
            section_id: The section this lab belongs to.
            lab_data: Dict returned by LabGenerator.generate().
        """
        from app.db.models.lab import Lab

        lab = Lab(
            section_id=section_id,
            title=lab_data.get("title", "Coding Exercise"),
            description=lab_data.get("description", ""),
            language=lab_data.get("language", "python"),
            starter_code=lab_data.get("starter_code", {}),
            test_code=lab_data.get("test_code", {}),
            solution_code=lab_data.get("solution_code", {}),
            run_instructions=lab_data.get("run_instructions", ""),
            confidence=float(lab_data.get("confidence", 0.5)),
        )
        db.add(lab)
        await db.flush()
        logger.info(f"Created lab '{lab.title}' for section {section_id}")

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
