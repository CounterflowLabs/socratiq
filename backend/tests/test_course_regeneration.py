"""Tests for the course regeneration feature."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.db.models.content_chunk import ContentChunk
from app.db.models.course import Course, CourseSource
from app.db.models.source import Source


def _seed_source(db_session, demo_user, status: str = "ready") -> Source:
    source = Source(
        type="markdown",
        url=None,
        title="Source for regen",
        raw_content="content text",
        status=status,
        created_by=demo_user.id,
        metadata_={},
    )
    db_session.add(source)
    return source


async def _seed_course_with_source(db_session, demo_user) -> tuple[Course, Source]:
    source = _seed_source(db_session, demo_user)
    await db_session.flush()

    db_session.add(ContentChunk(source_id=source.id, text="chunk one", metadata_={}))
    course = Course(
        title="Existing Course",
        description="Existing desc.",
        created_by=demo_user.id,
    )
    db_session.add(course)
    await db_session.flush()

    db_session.add(CourseSource(course_id=course.id, source_id=source.id))
    await db_session.flush()
    return course, source


@pytest.mark.asyncio
async def test_regenerate_endpoint_404_when_course_missing(
    client: AsyncClient, demo_user
):
    res = await client.post(
        "/api/v1/courses/00000000-0000-0000-0000-000000000000/regenerate",
        json={"directive": "x"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_regenerate_endpoint_400_when_no_sources(
    client: AsyncClient, db_session, demo_user
):
    course = Course(title="Empty", description="", created_by=demo_user.id)
    db_session.add(course)
    await db_session.flush()

    res = await client.post(
        f"/api/v1/courses/{course.id}/regenerate",
        json={"directive": ""},
    )
    assert res.status_code == 400
    assert "no linked sources" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_regenerate_endpoint_400_when_source_not_ready(
    client: AsyncClient, db_session, demo_user
):
    source = _seed_source(db_session, demo_user, status="processing")
    course = Course(title="Pending", description="", created_by=demo_user.id)
    db_session.add(course)
    await db_session.flush()
    db_session.add(CourseSource(course_id=course.id, source_id=source.id))
    await db_session.flush()

    res = await client.post(
        f"/api/v1/courses/{course.id}/regenerate",
        json={"directive": ""},
    )
    assert res.status_code == 400
    assert "not ready" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_regenerate_endpoint_202_enqueues_task(
    client: AsyncClient, db_session, demo_user
):
    course, _source = await _seed_course_with_source(db_session, demo_user)

    with patch(
        "app.api.routes.courses.enqueue", new_callable=AsyncMock
    ) as mock_enqueue:
        mock_enqueue.return_value = "celery-task-1"
        res = await client.post(
            f"/api/v1/courses/{course.id}/regenerate",
            json={"directive": "Make lessons concise"},
        )

    assert res.status_code == 202
    body = res.json()
    assert body["task_id"] == "celery-task-1"
    assert body["parent_course_id"] == str(course.id)
    mock_enqueue.assert_awaited_once()
    args = mock_enqueue.call_args.args
    assert args[0] == "regenerate_course"
    assert args[1] == str(course.id)
    assert args[2] == "Make lessons concise"


@pytest.mark.asyncio
async def test_get_course_response_includes_version_index(
    client: AsyncClient, db_session, demo_user
):
    course, _ = await _seed_course_with_source(db_session, demo_user)
    res = await client.get(f"/api/v1/courses/{course.id}")
    assert res.status_code == 200
    body = res.json()
    assert body["version_index"] == 1
    assert body["parent_id"] is None
    assert body["active_regeneration_task_id"] is None


@pytest.mark.asyncio
async def test_regenerate_endpoint_returns_existing_active_task(
    client: AsyncClient, db_session, demo_user
):
    """Re-clicking Regenerate while a task is running returns the same task id."""
    course, _ = await _seed_course_with_source(db_session, demo_user)

    with patch(
        "app.api.routes.courses.enqueue", new_callable=AsyncMock
    ) as mock_enqueue:
        mock_enqueue.return_value = "celery-task-running"
        res = await client.post(
            f"/api/v1/courses/{course.id}/regenerate",
            json={"directive": "first"},
        )
    assert res.status_code == 202
    mock_enqueue.assert_awaited_once()

    with patch(
        "app.api.routes.courses.enqueue", new_callable=AsyncMock
    ) as enqueue2, patch(
        "app.api.routes.courses.get_job_state", new_callable=AsyncMock
    ) as mock_state:
        mock_state.return_value = "running"
        res2 = await client.post(
            f"/api/v1/courses/{course.id}/regenerate",
            json={"directive": "second"},
        )
    assert res2.status_code == 202
    assert res2.json()["task_id"] == "celery-task-running"
    enqueue2.assert_not_awaited()


@pytest.mark.asyncio
async def test_regenerate_endpoint_starts_new_task_when_previous_finalized(
    client: AsyncClient, db_session, demo_user
):
    """After the previous regen finalized, a new POST creates a fresh task."""
    course, _ = await _seed_course_with_source(db_session, demo_user)
    course.active_regeneration_task_id = "celery-task-old"
    await db_session.flush()

    with patch(
        "app.api.routes.courses.enqueue", new_callable=AsyncMock
    ) as mock_enqueue, patch(
        "app.api.routes.courses.get_job_state", new_callable=AsyncMock
    ) as mock_state:
        mock_enqueue.return_value = "celery-task-new"
        mock_state.return_value = "success"  # previous task finalized
        res = await client.post(
            f"/api/v1/courses/{course.id}/regenerate",
            json={"directive": "retry"},
        )
    assert res.status_code == 202
    assert res.json()["task_id"] == "celery-task-new"
    mock_enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_clear_regeneration_endpoint(
    client: AsyncClient, db_session, demo_user
):
    course, _ = await _seed_course_with_source(db_session, demo_user)
    course.active_regeneration_task_id = "celery-task-x"
    await db_session.flush()

    res = await client.delete(f"/api/v1/courses/{course.id}/regeneration")
    assert res.status_code == 204

    detail = await client.get(f"/api/v1/courses/{course.id}")
    assert detail.json()["active_regeneration_task_id"] is None


@pytest.mark.asyncio
async def test_get_course_response_walks_parent_chain(
    client: AsyncClient, db_session, demo_user
):
    course_v1, source = await _seed_course_with_source(db_session, demo_user)

    course_v2 = Course(
        title="v2",
        description="",
        created_by=demo_user.id,
        parent_id=course_v1.id,
        regeneration_directive="be concise",
    )
    db_session.add(course_v2)
    await db_session.flush()
    db_session.add(CourseSource(course_id=course_v2.id, source_id=source.id))
    await db_session.flush()

    res = await client.get(f"/api/v1/courses/{course_v2.id}")
    body = res.json()
    assert body["version_index"] == 2
    assert body["parent_id"] == str(course_v1.id)
    assert body["regeneration_directive"] == "be concise"
