"""Section override service — merge / split adjacent course sections.

Manual override path from docs/design/section-planning.md Phase 4: when the
planner's bucket layout doesn't match what the user wants, they can merge
two adjacent sections OR split one into two. This is a UI-driven counterpart
to re-running ingestion at a new planner version.

Both operations preserve chunk → section coverage (every chunk that was
attached before is attached after), keep ``order_index`` contiguous within
the course, and leave lesson content untouched (stale lesson is fine; the
user can hit the per-section regenerate button afterward).

Lab rows: a section can carry at most one Lab. On merge, the surviving
section keeps its own Lab and the discarded section's Lab is deleted. On
split, the Lab stays with the original (now first) section.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.content_chunk import ContentChunk
from app.db.models.course import Course, Section
from app.db.models.exercise import Exercise
from app.db.models.lab import Lab
from app.db.models.learning_record import LearningRecord
from app.db.models.section_progress import SectionProgress

logger = logging.getLogger(__name__)


class SectionOverrideError(Exception):
    """Base class for merge/split validation failures."""


class SectionNotFound(SectionOverrideError):
    pass


class SectionNotOwned(SectionOverrideError):
    pass


class NoAdjacentSection(SectionOverrideError):
    pass


class CrossSourceMerge(SectionOverrideError):
    pass


class SplitPositionInvalid(SectionOverrideError):
    pass


@dataclass
class MergeResult:
    surviving_section_id: uuid.UUID
    removed_section_id: uuid.UUID
    chunks_reassigned: int


@dataclass
class SplitResult:
    original_section_id: uuid.UUID
    new_section_id: uuid.UUID
    chunks_in_original: int
    chunks_in_new: int


async def merge_with_next(
    db: AsyncSession,
    *,
    section_id: uuid.UUID,
    user_id: uuid.UUID,
) -> MergeResult:
    """Merge ``section_id`` with the section immediately after it.

    Reassigns the trailing section's chunks to ``section_id``, copies any
    useful content fields, removes the trailing section, and bumps the
    order_index of every section after the pair down by one.

    Raises:
        SectionNotFound: section doesn't exist
        SectionNotOwned: caller doesn't own the course
        NoAdjacentSection: section is the last in the course
        CrossSourceMerge: the two sections belong to different sources
    """
    section = await db.get(Section, section_id)
    if section is None or section.order_index is None:
        raise SectionNotFound(f"Section {section_id} not found")
    course = await db.get(Course, section.course_id)
    if course is None or course.created_by != user_id:
        raise SectionNotOwned(f"Section {section_id} not accessible")

    # Find the next section in this course by order_index.
    result = await db.execute(
        select(Section)
        .where(
            Section.course_id == section.course_id,
            Section.order_index == section.order_index + 1,
        )
        .limit(1)
    )
    next_section = result.scalar_one_or_none()
    if next_section is None:
        raise NoAdjacentSection(
            f"Section {section_id} has no following section to merge with"
        )

    if section.source_id != next_section.source_id:
        raise CrossSourceMerge(
            "Cannot merge sections from different sources"
        )

    # Reassign chunks from next_section to section.
    chunk_update = await db.execute(
        update(ContentChunk)
        .where(ContentChunk.section_id == next_section.id)
        .values(section_id=section.id)
        .returning(ContentChunk.id)
    )
    moved_ids = list(chunk_update.scalars().all())

    # Merge content metadata conservatively: union key_terms, OR has_code,
    # extend source_end to the later section's, keep first section's title
    # and lesson. The user can regenerate lesson per-section if they want a
    # fresh version that reflects the merged scope.
    merged_content = dict(section.content or {})
    next_content = dict(next_section.content or {})
    merged_content["key_terms"] = list(
        dict.fromkeys(
            (merged_content.get("key_terms") or [])
            + (next_content.get("key_terms") or [])
        )
    )
    merged_content["has_code"] = bool(
        merged_content.get("has_code") or next_content.get("has_code")
    )
    # Drop stale graph card — its anchor referred to the old section split.
    merged_content.pop("graph_card", None)
    section.content = merged_content
    section.source_end = next_section.source_end or section.source_end

    # Clean up rows that reference next_section before the section row goes
    # away (FKs are unconstrained — without these, the section delete trips a
    # constraint violation as soon as the user has read the lesson, generated
    # exercises, or recorded any learning event on the discarded section).
    #
    # Exercises and section_progress were scoped to the old bucket boundary,
    # so they're stale and dropped. LearningRecord preserves user history, so
    # we reassign those events to the surviving section instead of deleting.
    await db.execute(
        update(LearningRecord)
        .where(LearningRecord.section_id == next_section.id)
        .values(section_id=section.id)
    )
    await db.execute(
        delete(SectionProgress).where(
            SectionProgress.section_id == next_section.id
        )
    )
    await db.execute(
        delete(Exercise).where(Exercise.section_id == next_section.id)
    )
    # Delete labs on the discarded section (the surviving lab, if any, stays).
    await db.execute(
        delete(Lab).where(Lab.section_id == next_section.id)
    )
    # Delete the trailing section itself.
    await db.execute(
        delete(Section).where(Section.id == next_section.id)
    )

    # Shift order_index for every section after the merged pair.
    await db.execute(
        update(Section)
        .where(
            Section.course_id == section.course_id,
            Section.order_index > next_section.order_index,
        )
        .values(order_index=Section.order_index - 1)
    )

    await db.flush()
    logger.info(
        "Merged section %s ← section %s (%d chunks reassigned)",
        section.id, next_section.id, len(moved_ids),
    )
    return MergeResult(
        surviving_section_id=section.id,
        removed_section_id=next_section.id,
        chunks_reassigned=len(moved_ids),
    )


async def split_section(
    db: AsyncSession,
    *,
    section_id: uuid.UUID,
    user_id: uuid.UUID,
    split_at_chunk_index: int,
) -> SplitResult:
    """Split a section in two at the given chunk-index boundary.

    Chunks within the section are ordered by ``created_at`` (the same order
    used everywhere else in the codebase). The split point is the index of
    the first chunk that moves to the NEW section, so a value of 1 means
    "the original keeps the first chunk, the new section starts at the
    second". 0 and len(chunks) are invalid (no-op splits).

    Raises:
        SectionNotFound: section doesn't exist
        SectionNotOwned: caller doesn't own the course
        SplitPositionInvalid: index <= 0, index >= section chunk count, or
            section has < 2 chunks
    """
    section = await db.get(Section, section_id)
    if section is None or section.order_index is None:
        raise SectionNotFound(f"Section {section_id} not found")
    course = await db.get(Course, section.course_id)
    if course is None or course.created_by != user_id:
        raise SectionNotOwned(f"Section {section_id} not accessible")

    # Load section chunks in stable order.
    chunk_rows = await db.execute(
        select(ContentChunk)
        .where(ContentChunk.section_id == section.id)
        .order_by(ContentChunk.created_at, ContentChunk.id)
    )
    chunks = list(chunk_rows.scalars().all())
    if len(chunks) < 2:
        raise SplitPositionInvalid(
            f"Section {section_id} has < 2 chunks; nothing to split"
        )
    if split_at_chunk_index <= 0 or split_at_chunk_index >= len(chunks):
        raise SplitPositionInvalid(
            f"split_at_chunk_index={split_at_chunk_index} out of bounds "
            f"(1..{len(chunks) - 1})"
        )

    head_chunks = chunks[:split_at_chunk_index]
    tail_chunks = chunks[split_at_chunk_index:]

    # Bump order_index for every section after the split point so the new
    # section can slot in at section.order_index + 1.
    await db.execute(
        update(Section)
        .where(
            Section.course_id == section.course_id,
            Section.order_index > section.order_index,
        )
        .values(order_index=Section.order_index + 1)
    )

    # Build the new section. Title falls back to the leading tail chunk's
    # analyzer-topic; the lesson is left empty so the UI flags it for
    # regeneration. Graph card / lab stay with the head section.
    first_tail_meta = tail_chunks[0].metadata_ or {}
    new_title = (
        first_tail_meta.get("section_bucket_topic")
        or first_tail_meta.get("topic")
        or f"{section.title} (cont.)"
    )
    last_tail_meta = tail_chunks[-1].metadata_ or {}
    new_section = Section(
        course_id=section.course_id,
        title=new_title,
        order_index=section.order_index + 1,
        source_id=section.source_id,
        source_start=_format_source_ref(first_tail_meta, "start"),
        source_end=_format_source_ref(last_tail_meta, "end")
                   or section.source_end,
        content={
            "summary": first_tail_meta.get("summary", ""),
            "key_terms": first_tail_meta.get("key_terms", []),
            "has_code": any(
                (c.metadata_ or {}).get("has_code") for c in tail_chunks
            ),
            "lab_mode": (section.content or {}).get("lab_mode", "none"),
        },
        difficulty=section.difficulty,
    )
    db.add(new_section)
    await db.flush()

    # Reassign tail chunks to the new section.
    await db.execute(
        update(ContentChunk)
        .where(ContentChunk.id.in_([c.id for c in tail_chunks]))
        .values(section_id=new_section.id)
    )

    # Update head section's source_end to reflect the new (shorter) span.
    head_last_meta = head_chunks[-1].metadata_ or {}
    new_source_end = _format_source_ref(head_last_meta, "end")
    if new_source_end is not None:
        section.source_end = new_source_end
    # Strip the stale graph card; it was anchored at the old (wider) section.
    if section.content:
        new_content = dict(section.content)
        new_content.pop("graph_card", None)
        section.content = new_content

    await db.flush()
    logger.info(
        "Split section %s at chunk %d → new section %s (%d + %d chunks)",
        section.id, split_at_chunk_index, new_section.id,
        len(head_chunks), len(tail_chunks),
    )
    return SplitResult(
        original_section_id=section.id,
        new_section_id=new_section.id,
        chunks_in_original=len(head_chunks),
        chunks_in_new=len(tail_chunks),
    )


def _format_source_ref(metadata: dict, ref_type: str) -> str | None:
    """Mirror course_generator._format_source_ref so split keeps the
    existing string conventions (e.g. ``"180s"``, ``"p3"``)."""
    if "start_time" in metadata and ref_type == "start":
        return f"{metadata['start_time']:.0f}s"
    if "end_time" in metadata and ref_type == "end":
        return f"{metadata['end_time']:.0f}s"
    if "page_start" in metadata and ref_type == "start":
        return f"p{metadata['page_start']}"
    if "page_end" in metadata and ref_type == "end":
        return f"p{metadata['page_end']}"
    return None


__all__ = [
    "MergeResult",
    "SplitResult",
    "SectionOverrideError",
    "SectionNotFound",
    "SectionNotOwned",
    "NoAdjacentSection",
    "CrossSourceMerge",
    "SplitPositionInvalid",
    "merge_with_next",
    "split_section",
]
