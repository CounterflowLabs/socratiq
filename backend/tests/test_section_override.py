"""Tests for SectionOverride — merge / split manual overrides."""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models.content_chunk import ContentChunk
from app.db.models.course import Course, Section
from app.db.models.exercise import Exercise
from app.db.models.learning_record import LearningRecord
from app.db.models.section_progress import SectionProgress
from app.db.models.source import Source
from app.db.models.user import User
from app.services.section_override import (
    CrossSourceMerge,
    NoAdjacentSection,
    SectionNotFound,
    SectionNotOwned,
    SplitPositionInvalid,
    merge_with_next,
    split_section,
)


# --- fixtures -------------------------------------------------------------


@pytest.fixture
async def owner(db_session):
    """A user that owns the test course."""
    u = User(id=uuid.uuid4(), email=f"o-{uuid.uuid4()}@x.test", name="Owner")
    db_session.add(u)
    await db_session.flush()
    return u


@pytest.fixture
async def other_user(db_session):
    """A separate user who does NOT own the course."""
    u = User(id=uuid.uuid4(), email=f"o-{uuid.uuid4()}@x.test", name="Stranger")
    db_session.add(u)
    await db_session.flush()
    return u


async def _make_course_with_sections(
    db_session,
    owner_id: uuid.UUID,
    chunks_per_section: list[int],
    source_ids: list[uuid.UUID] | None = None,
) -> tuple[Course, list[Section], list[list[ContentChunk]]]:
    """Build a course with N sections each holding the requested chunk count.

    Returns (course, sections_in_order, [chunks_per_section_in_order]).
    If ``source_ids`` is supplied it must have len == len(chunks_per_section);
    otherwise a single shared source is created for all sections.
    """
    if source_ids is None:
        src = Source(type="bilibili", url="https://x", title="T", status="ready")
        db_session.add(src)
        await db_session.flush()
        source_ids = [src.id] * len(chunks_per_section)
    else:
        for sid in set(source_ids):
            src = Source(
                id=sid, type="bilibili", url="https://x", title="T", status="ready",
            )
            db_session.add(src)
        await db_session.flush()

    course = Course(title="T", description="", created_by=owner_id)
    db_session.add(course)
    await db_session.flush()

    sections: list[Section] = []
    chunks: list[list[ContentChunk]] = []
    for idx, n_chunks in enumerate(chunks_per_section):
        sec = Section(
            course_id=course.id,
            title=f"S{idx}",
            order_index=idx,
            source_id=source_ids[idx],
            content={"key_terms": [f"kw{idx}"], "has_code": False},
            difficulty=1,
        )
        db_session.add(sec)
        await db_session.flush()
        sections.append(sec)
        sec_chunks = []
        # Postgres ``now()`` returns the transaction-start time, so chunks
        # created in the same test transaction would share ``created_at`` and
        # become unsortable by it. Set ``created_at`` explicitly so order
        # tests are deterministic.
        # The ``created_at`` column is TIMESTAMP WITHOUT TIME ZONE, so use a
        # naive datetime here.
        base_time = datetime(2026, 1, 1) + timedelta(seconds=idx * 1000)
        for j in range(n_chunks):
            c = ContentChunk(
                source_id=source_ids[idx],
                section_id=sec.id,
                text=f"chunk-{idx}-{j}",
                metadata_={
                    "start_time": idx * 100 + j * 10,
                    "end_time": idx * 100 + (j + 1) * 10,
                },
                created_at=base_time + timedelta(seconds=j),
            )
            db_session.add(c)
            await db_session.flush()
            sec_chunks.append(c)
        chunks.append(sec_chunks)

    return course, sections, chunks


# --- merge ----------------------------------------------------------------


class TestMerge:
    @pytest.mark.asyncio
    async def test_merge_two_adjacent_sections_succeeds(self, db_session, owner):
        course, sections, chunks = await _make_course_with_sections(
            db_session, owner.id, chunks_per_section=[2, 3, 1]
        )

        result = await merge_with_next(
            db_session, section_id=sections[0].id, user_id=owner.id
        )

        assert result.surviving_section_id == sections[0].id
        assert result.removed_section_id == sections[1].id
        assert result.chunks_reassigned == 3

        # Trailing section deleted.
        gone = await db_session.execute(
            select(Section).where(Section.id == sections[1].id)
        )
        assert gone.scalar_one_or_none() is None

        # Chunks from section 1 now belong to section 0.
        moved = await db_session.execute(
            select(ContentChunk.section_id).where(
                ContentChunk.id.in_([c.id for c in chunks[1]])
            )
        )
        for sid in moved.scalars():
            assert sid == sections[0].id

        # The originally-third section's order_index dropped from 2 to 1.
        renumbered = await db_session.execute(
            select(Section).where(Section.id == sections[2].id)
        )
        third = renumbered.scalar_one()
        assert third.order_index == 1

    @pytest.mark.asyncio
    async def test_merge_unions_key_terms_and_has_code(self, db_session, owner):
        course, sections, _ = await _make_course_with_sections(
            db_session, owner.id, chunks_per_section=[1, 1]
        )
        sections[0].content = {"key_terms": ["alpha", "beta"], "has_code": False}
        sections[1].content = {"key_terms": ["beta", "gamma"], "has_code": True}
        await db_session.flush()

        await merge_with_next(
            db_session, section_id=sections[0].id, user_id=owner.id
        )

        # Refresh section 0
        refreshed = await db_session.execute(
            select(Section).where(Section.id == sections[0].id)
        )
        merged = refreshed.scalar_one()
        assert merged.content["has_code"] is True
        # Order preserved, duplicates collapsed
        assert merged.content["key_terms"] == ["alpha", "beta", "gamma"]

    @pytest.mark.asyncio
    async def test_merge_last_section_raises(self, db_session, owner):
        course, sections, _ = await _make_course_with_sections(
            db_session, owner.id, chunks_per_section=[1, 1]
        )
        with pytest.raises(NoAdjacentSection):
            await merge_with_next(
                db_session, section_id=sections[-1].id, user_id=owner.id
            )

    @pytest.mark.asyncio
    async def test_merge_across_sources_raises(self, db_session, owner):
        a = uuid.uuid4()
        b = uuid.uuid4()
        _, sections, _ = await _make_course_with_sections(
            db_session,
            owner.id,
            chunks_per_section=[1, 1],
            source_ids=[a, b],
        )
        with pytest.raises(CrossSourceMerge):
            await merge_with_next(
                db_session, section_id=sections[0].id, user_id=owner.id
            )

    @pytest.mark.asyncio
    async def test_merge_unauthorized_raises(
        self, db_session, owner, other_user
    ):
        _, sections, _ = await _make_course_with_sections(
            db_session, owner.id, chunks_per_section=[1, 1]
        )
        with pytest.raises(SectionNotOwned):
            await merge_with_next(
                db_session, section_id=sections[0].id, user_id=other_user.id
            )

    @pytest.mark.asyncio
    async def test_merge_missing_section_raises(self, db_session, owner):
        with pytest.raises(SectionNotFound):
            await merge_with_next(
                db_session, section_id=uuid.uuid4(), user_id=owner.id
            )

    @pytest.mark.asyncio
    async def test_merge_cleans_referencing_rows(self, db_session, owner):
        """next_section's exercises/progress/learning_records must not block delete.

        Without this cleanup the section delete trips a FK violation as soon as
        the user has read the lesson or generated exercises on the trailing
        section. See section_override.merge_with_next.
        """
        _, sections, _ = await _make_course_with_sections(
            db_session, owner.id, chunks_per_section=[1, 1]
        )
        # Exercise on next_section — should be deleted.
        ex = Exercise(
            section_id=sections[1].id,
            type="mcq",
            question="q",
            difficulty=1,
        )
        # SectionProgress on next_section — should be deleted.
        prog = SectionProgress(
            user_id=owner.id, section_id=sections[1].id, lesson_read=True
        )
        # LearningRecord on next_section — should be reassigned to surviving.
        rec = LearningRecord(
            user_id=owner.id,
            section_id=sections[1].id,
            type="lesson_view",
            data={},
        )
        db_session.add_all([ex, prog, rec])
        await db_session.flush()

        await merge_with_next(
            db_session, section_id=sections[0].id, user_id=owner.id
        )

        # Exercise gone.
        ex_check = await db_session.execute(
            select(Exercise).where(Exercise.id == ex.id)
        )
        assert ex_check.scalar_one_or_none() is None

        # SectionProgress gone.
        prog_check = await db_session.execute(
            select(SectionProgress).where(SectionProgress.id == prog.id)
        )
        assert prog_check.scalar_one_or_none() is None

        # LearningRecord reassigned to surviving section, not deleted.
        rec_check = await db_session.execute(
            select(LearningRecord).where(LearningRecord.id == rec.id)
        )
        rec_row = rec_check.scalar_one()
        assert rec_row.section_id == sections[0].id


# --- split ----------------------------------------------------------------


class TestSplit:
    @pytest.mark.asyncio
    async def test_split_section_creates_new_with_tail_chunks(
        self, db_session, owner
    ):
        _, sections, chunks = await _make_course_with_sections(
            db_session, owner.id, chunks_per_section=[5, 2]
        )

        result = await split_section(
            db_session,
            section_id=sections[0].id,
            user_id=owner.id,
            split_at_chunk_index=2,
        )

        assert result.original_section_id == sections[0].id
        assert result.chunks_in_original == 2
        assert result.chunks_in_new == 3

        # The new section sits at order_index=1; original section 1 bumped to 2.
        new_section = await db_session.get(Section, result.new_section_id)
        assert new_section.order_index == 1
        bumped = await db_session.execute(
            select(Section).where(Section.id == sections[1].id)
        )
        assert bumped.scalar_one().order_index == 2

        # Chunks split correctly between original (first 2) and new (last 3).
        moved = await db_session.execute(
            select(ContentChunk.id, ContentChunk.section_id).where(
                ContentChunk.id.in_([c.id for c in chunks[0]])
            )
        )
        # Build {chunk_id: section_id}
        actual = {row.id: row.section_id for row in moved}
        # Original chunks[0][0], chunks[0][1] stay; chunks[0][2..4] move.
        assert actual[chunks[0][0].id] == sections[0].id
        assert actual[chunks[0][1].id] == sections[0].id
        assert actual[chunks[0][2].id] == new_section.id
        assert actual[chunks[0][3].id] == new_section.id
        assert actual[chunks[0][4].id] == new_section.id

    @pytest.mark.asyncio
    async def test_split_picks_topic_from_first_tail_chunk_metadata(
        self, db_session, owner
    ):
        _, sections, chunks = await _make_course_with_sections(
            db_session, owner.id, chunks_per_section=[3]
        )
        # Stamp a bucket topic on the first tail chunk.
        chunks[0][1].metadata_ = {
            **(chunks[0][1].metadata_ or {}),
            "section_bucket_topic": "fancy new topic",
        }
        await db_session.flush()

        result = await split_section(
            db_session,
            section_id=sections[0].id,
            user_id=owner.id,
            split_at_chunk_index=1,
        )
        new_section = await db_session.get(Section, result.new_section_id)
        assert new_section.title == "fancy new topic"

    @pytest.mark.asyncio
    async def test_split_position_out_of_bounds(self, db_session, owner):
        _, sections, _ = await _make_course_with_sections(
            db_session, owner.id, chunks_per_section=[3]
        )
        # 0 → invalid (would create empty original)
        with pytest.raises(SplitPositionInvalid):
            await split_section(
                db_session,
                section_id=sections[0].id,
                user_id=owner.id,
                split_at_chunk_index=0,
            )
        # >= len → invalid (would create empty new section)
        with pytest.raises(SplitPositionInvalid):
            await split_section(
                db_session,
                section_id=sections[0].id,
                user_id=owner.id,
                split_at_chunk_index=3,
            )

    @pytest.mark.asyncio
    async def test_split_single_chunk_section_raises(self, db_session, owner):
        _, sections, _ = await _make_course_with_sections(
            db_session, owner.id, chunks_per_section=[1]
        )
        with pytest.raises(SplitPositionInvalid):
            await split_section(
                db_session,
                section_id=sections[0].id,
                user_id=owner.id,
                split_at_chunk_index=1,
            )

    @pytest.mark.asyncio
    async def test_split_unauthorized_raises(
        self, db_session, owner, other_user
    ):
        _, sections, _ = await _make_course_with_sections(
            db_session, owner.id, chunks_per_section=[3]
        )
        with pytest.raises(SectionNotOwned):
            await split_section(
                db_session,
                section_id=sections[0].id,
                user_id=other_user.id,
                split_at_chunk_index=1,
            )


# --- API integration (route + auth) ---------------------------------------


@pytest.mark.asyncio
async def test_merge_endpoint_returns_404_for_unknown_section(client):
    resp = await client.post(
        f"/api/v1/courses/sections/{uuid.uuid4()}/merge-next"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_split_endpoint_returns_400_for_bad_index(client, db_session, demo_user):
    _, sections, _ = await _make_course_with_sections(
        db_session, demo_user.id, chunks_per_section=[2]
    )
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/courses/sections/{sections[0].id}/split",
        json={"split_at_chunk_index": 5},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_merge_endpoint_happy_path(client, db_session, demo_user):
    _, sections, _ = await _make_course_with_sections(
        db_session, demo_user.id, chunks_per_section=[2, 2]
    )
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/courses/sections/{sections[0].id}/merge-next"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["chunks_reassigned"] == 2
    assert body["surviving_section_id"] == str(sections[0].id)
