"""Course generation service.

Owns all teaching-asset generation: lessons, labs, and the concept graph.
``ingest_source`` only produces the content fingerprint
(chunks + concepts + embeddings + analysis); the per-page LLM work that
turns that fingerprint into a learnable course lives here.

Lessons are written into ``Section.content``, labs into the ``Lab`` table.
The legacy ``source.metadata_["lesson_by_page"]`` etc. are still read as a
fallback when a course is assembled from a pre-Tier-2 source.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models.content_chunk import ContentChunk as ContentChunkModel
from app.db.models.course import Course, CourseSource, Section
from app.db.models.source import Source
from app.models.lesson import CodeSnippet
from app.prompt_template import load_prompt
from app.services.lab_generator import LabGenerator
from app.services.lesson_generator import LessonGenerator
from app.services.llm.base import UnifiedMessage
from app.services.llm.router import ModelRouter, TaskType

logger = logging.getLogger(__name__)

_DESCRIPTION_PROMPT = load_prompt(Path(__file__).parent / "prompts" / "course_description.md")


class CourseGenerator:
    """Generates structured courses from analyzed sources."""

    def __init__(self, model_router: ModelRouter):
        self._router = model_router

    async def generate(
        self,
        db: AsyncSession,
        source_ids: list[UUID],
        target_language: str,
        title: str | None = None,
        user_id: UUID | None = None,
        skip_ready_check: bool = False,
        user_directive: str = "",
    ) -> Course:
        """Generate a course from one or more ingested sources."""
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
        chunks_by_source: dict[UUID, list[ContentChunkModel]] = {}
        all_chunks: list[ContentChunkModel] = []
        for source in sources:
            result = await db.execute(
                select(ContentChunkModel)
                .where(ContentChunkModel.source_id == source.id)
                .order_by(ContentChunkModel.created_at)
            )
            rows = result.scalars().all()
            chunks_by_source[source.id] = rows
            all_chunks.extend(rows)

        # 6. Generate teaching assets per source (lesson + lab + graph per page)
        provider = await self._router.get_provider(TaskType.CONTENT_ANALYSIS)
        lesson_gen = LessonGenerator(provider)
        lab_gen = LabGenerator(provider)
        settings = get_settings()
        sem = asyncio.Semaphore(getattr(settings, "llm_max_concurrency", 4))

        per_source_assets: dict[UUID, _SourceAssets] = {}
        for source in sources:
            assets = await self._generate_assets_for_source(
                source=source,
                chunks=chunks_by_source[source.id],
                lesson_gen=lesson_gen,
                lab_gen=lab_gen,
                sem=sem,
                target_language=target_language,
                user_directive=user_directive,
            )
            per_source_assets[source.id] = assets

        # 7. Create Sections (one per (source, page) group)
        await self._build_sections(
            db=db,
            course=course,
            sources=sources,
            chunks_by_source=chunks_by_source,
            per_source_assets=per_source_assets,
        )

        # 8. Generate course description via LLM
        course.description = await self._generate_description(
            course_title=title,
            section_count=len(all_chunks),
            sources=sources,
            target_language=target_language,
        )

        await db.flush()
        logger.info(
            "Generated course '%s' (%d sources, %d chunks)",
            title,
            len(sources),
            len(all_chunks),
        )
        return course

    async def _generate_assets_for_source(
        self,
        *,
        source: Source,
        chunks: list[ContentChunkModel],
        lesson_gen: LessonGenerator,
        lab_gen: LabGenerator,
        sem: asyncio.Semaphore,
        target_language: str,
        user_directive: str,
    ) -> "_SourceAssets":
        """Plan + generate lessons/labs/graphs for one source, in parallel per page."""
        smeta = source.metadata_ or {}

        # Legacy data path: pre-Tier-2 sources still carry lesson/lab in metadata.
        # Use them as-is to avoid re-paying LLM cost.
        if smeta.get("lesson_by_page"):
            return _SourceAssets.from_legacy_metadata(smeta)

        # Group chunks by page_index
        page_groups: dict[int, list[ContentChunkModel]] = defaultdict(list)
        for chunk in chunks:
            cmeta = chunk.metadata_ or {}
            page_idx = cmeta.get("page_index", 0)
            page_groups[page_idx].append(chunk)

        asset_plan = smeta.get("asset_plan") or {"lab_mode": "none"}
        lab_mode = asset_plan.get("lab_mode", "none")

        # Run lesson generation in parallel across pages
        async def _gen_one_lesson(page_idx: int, page_chunks: list[ContentChunkModel]):
            async with sem:
                first_meta = page_chunks[0].metadata_ or {}
                page_title = (
                    first_meta.get("page_title") or source.title or "Untitled"
                )
                lesson = await lesson_gen.generate(
                    subtitle_chunks=[c.text for c in page_chunks],
                    video_title=page_title,
                    target_language=target_language,
                    user_directive=user_directive,
                )
                return page_idx, lesson

        sorted_pages = sorted(page_groups.keys())
        lesson_results = await asyncio.gather(
            *(_gen_one_lesson(p, page_groups[p]) for p in sorted_pages)
        )
        lesson_by_page: dict[int, dict] = {
            p: lesson.model_dump() for p, lesson in lesson_results
        }

        # Build graph cards from lesson concept_relation blocks
        suggested_prereqs = smeta.get("suggested_prerequisites", [])
        graph_by_page: dict[int, dict] = {}
        for page_idx, lesson_dict in lesson_by_page.items():
            key_concepts: list[str] = []
            for block in lesson_dict.get("blocks", []):
                if block.get("type") == "concept_relation":
                    for c in block.get("concepts", []):
                        label = c.get("label") if isinstance(c, dict) else None
                        if label:
                            key_concepts.append(label)
            deduped = list(dict.fromkeys(key_concepts))
            graph_by_page[page_idx] = {
                "current": deduped[:2],
                "prerequisites": suggested_prereqs[:3],
                "unlocks": deduped[2:5],
                "section_anchor": page_idx,
            }

        # Run lab generation in parallel where lab_mode == "inline"
        labs_by_page: dict[int, dict | None] = {}
        if lab_mode == "inline":
            async def _gen_one_lab(page_idx: int, lesson_dict: dict):
                async with sem:
                    snippets = [
                        CodeSnippet(
                            language=block.get("language") or "python",
                            code=block.get("code") or "",
                            context=block.get("body") or "",
                        )
                        for block in lesson_dict.get("blocks", [])
                        if block.get("type") == "code_example" and block.get("code")
                    ]
                    if not snippets:
                        return page_idx, None
                    lang_counts: dict[str, int] = {}
                    for s in snippets:
                        lang_counts[s.language] = lang_counts.get(s.language, 0) + 1
                    language = max(lang_counts, key=lang_counts.__getitem__)
                    lab = await lab_gen.generate(
                        code_snippets=snippets,
                        lesson_context=lesson_dict.get("summary", ""),
                        language=language,
                        target_language=target_language,
                        user_directive=user_directive,
                    )
                    return page_idx, lab

            lab_results = await asyncio.gather(
                *(_gen_one_lab(p, lesson_by_page[p]) for p in sorted_pages)
            )
            for page_idx, lab in lab_results:
                if lab is not None:
                    labs_by_page[page_idx] = lab

        return _SourceAssets(
            lesson_by_page=lesson_by_page,
            graph_by_page=graph_by_page,
            labs_by_page=labs_by_page,
            lab_mode=lab_mode,
        )

    async def _build_sections(
        self,
        *,
        db: AsyncSession,
        course: Course,
        sources: list[Source],
        chunks_by_source: dict[UUID, list[ContentChunkModel]],
        per_source_assets: dict[UUID, "_SourceAssets"],
    ) -> None:
        """Create Section + Lab rows from generated assets."""
        from app.db.models.lab import Lab

        all_chunks = [c for cs in chunks_by_source.values() for c in cs]
        has_page_index = any(
            (c.metadata_ or {}).get("page_index") is not None for c in all_chunks
        )

        if has_page_index:
            page_groups: dict[tuple[UUID, int], list[ContentChunkModel]] = defaultdict(list)
            for chunk in all_chunks:
                page_idx = (chunk.metadata_ or {}).get("page_index", 0)
                page_groups[(chunk.source_id, page_idx)].append(chunk)

            section_order = 0
            for (source_id, page_idx), group_chunks in sorted(
                page_groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])
            ):
                first_meta = group_chunks[0].metadata_ or {}
                assets = per_source_assets.get(source_id) or _SourceAssets.empty()
                lesson = assets.lesson_for(page_idx)
                graph = assets.graph_for(page_idx)
                lab_data = assets.lab_for(page_idx)

                section_title = (
                    (lesson or {}).get("title")
                    or first_meta.get("page_title")
                    or first_meta.get("topic")
                    or f"Section {section_order + 1}"
                )

                section_content = {
                    "summary": (lesson or {}).get("summary") or first_meta.get("summary", ""),
                    "key_terms": first_meta.get("key_terms", []),
                    "has_code": any((c.metadata_ or {}).get("has_code") for c in group_chunks),
                    "lab_mode": assets.lab_mode,
                    "graph_card": graph,
                }
                if lesson:
                    section_content["lesson"] = lesson

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

                if assets.lab_mode == "inline" and lab_data:
                    await self._create_lab(db, section.id, lab_data)

                section_order += 1
        else:
            # No page grouping: one section per chunk
            for i, chunk in enumerate(all_chunks):
                metadata = chunk.metadata_ or {}
                source_id = chunk.source_id
                assets = per_source_assets.get(source_id) or _SourceAssets.empty()
                lesson = assets.lesson_for(0)
                graph = assets.graph_for(0)

                section_title = (
                    (lesson or {}).get("title")
                    or metadata.get("topic")
                    or f"Section {i + 1}"
                )
                section_content = {
                    "summary": (lesson or {}).get("summary") or metadata.get("summary", ""),
                    "key_terms": metadata.get("key_terms", []),
                    "has_code": metadata.get("has_code", False),
                    "lab_mode": assets.lab_mode,
                    "graph_card": graph,
                }
                if lesson:
                    section_content["lesson"] = lesson

                section = Section(
                    course_id=course.id,
                    title=section_title,
                    order_index=i,
                    source_id=source_id,
                    source_start=self._format_source_ref(metadata, "start"),
                    source_end=self._format_source_ref(metadata, "end"),
                    content=section_content,
                    difficulty=metadata.get("difficulty", 1),
                )
                db.add(section)
                await db.flush()
                chunk.section_id = section.id

            # One lab per source if available, attached to the first section.
            attached_to: set[UUID] = set()
            for chunk in all_chunks:
                src_id = chunk.source_id
                if src_id in attached_to:
                    continue
                assets = per_source_assets.get(src_id) or _SourceAssets.empty()
                lab_data = assets.lab_for(0)
                if assets.lab_mode == "inline" and lab_data and chunk.section_id:
                    await self._create_lab(db, chunk.section_id, lab_data)
                    attached_to.add(src_id)

        await db.flush()

    @staticmethod
    async def _create_lab(db: AsyncSession, section_id: UUID, lab_data: dict) -> None:
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
        logger.info("Created lab '%s' for section %s", lab.title, section_id)

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
        self,
        course_title: str,
        section_count: int,
        sources: list[Source],
        target_language: str,
    ) -> str:
        try:
            provider = await self._router.get_provider(TaskType.CONTENT_ANALYSIS)
            source_info = ", ".join(s.title or s.url or "unknown" for s in sources)
            messages = [
                UnifiedMessage(
                    role="user",
                    content=_DESCRIPTION_PROMPT.render(
                        course_title=course_title,
                        section_count=section_count,
                        source_info=source_info,
                        target_language=target_language,
                    ),
                ),
            ]
            response = await provider.chat(messages, max_tokens=256, temperature=0.5)
            return "".join(b.text or "" for b in response.content if b.type == "text").strip()
        except Exception:
            logger.warning("Failed to generate course description, using fallback")
            return f"A course based on {len(sources)} source(s) with {section_count} sections."


class _SourceAssets:
    """Aggregated lesson/lab/graph dicts keyed by page index."""

    def __init__(
        self,
        *,
        lesson_by_page: dict[int, dict],
        graph_by_page: dict[int, dict],
        labs_by_page: dict[int, dict | None],
        lab_mode: str,
    ) -> None:
        self.lesson_by_page = lesson_by_page
        self.graph_by_page = graph_by_page
        self.labs_by_page = labs_by_page
        self.lab_mode = lab_mode

    @classmethod
    def empty(cls) -> "_SourceAssets":
        return cls(
            lesson_by_page={},
            graph_by_page={},
            labs_by_page={},
            lab_mode="none",
        )

    @classmethod
    def from_legacy_metadata(cls, smeta: dict) -> "_SourceAssets":
        """Build from pre-Tier-2 source.metadata_."""
        def _intkeys(d: dict | None) -> dict:
            if not d:
                return {}
            return {int(k) if str(k).isdigit() else k: v for k, v in d.items()}

        labs_by_page = _intkeys(smeta.get("labs_by_page"))
        asset_plan = smeta.get("asset_plan") or {}
        # Legacy sources sometimes have labs_by_page but no asset_plan; if the
        # legacy data carries any non-null lab dict, infer lab_mode=inline.
        legacy_inline = any(v for v in labs_by_page.values())
        lab_mode = asset_plan.get("lab_mode") or ("inline" if legacy_inline else "none")
        return cls(
            lesson_by_page=_intkeys(smeta.get("lesson_by_page")),
            graph_by_page=_intkeys(smeta.get("graph_by_page")),
            labs_by_page=labs_by_page,
            lab_mode=lab_mode,
        )

    def lesson_for(self, page_idx: int) -> dict | None:
        return self.lesson_by_page.get(page_idx) or self.lesson_by_page.get(str(page_idx))

    def graph_for(self, page_idx: int) -> dict | None:
        return self.graph_by_page.get(page_idx) or self.graph_by_page.get(str(page_idx))

    def lab_for(self, page_idx: int) -> dict | None:
        return self.labs_by_page.get(page_idx) or self.labs_by_page.get(str(page_idx))
