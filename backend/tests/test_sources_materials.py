import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.db.models.course import Course, CourseSource
from app.db.models.source import Source
from app.db.models.source_task import SourceTask


@pytest.mark.asyncio
async def test_create_source_persists_processing_task(client, db_session):
    with patch("app.api.routes.sources.ingest_source") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "fake-task-001"
        mock_task.delay.return_value = mock_result

        res = await client.post("/api/v1/sources", data={
            "url": "https://www.youtube.com/watch?v=kCc8FmEb1nY",
        })

    assert res.status_code == 201
    source_id = uuid.UUID(res.json()["id"])
    tasks = (
        await db_session.execute(
            select(SourceTask).where(SourceTask.source_id == source_id)
        )
    ).scalars().all()

    assert len(tasks) == 1
    assert tasks[0].task_type == "source_processing"
    assert tasks[0].status == "pending"
    assert tasks[0].celery_task_id == "fake-task-001"


@pytest.mark.asyncio
async def test_create_clone_source_persists_processing_task(client, db_session, demo_user):
    donor = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=donor",
        title="Donor source",
        status="ready",
        content_key="shared-key",
        created_by=demo_user.id,
    )
    db_session.add(donor)
    await db_session.flush()

    with patch("app.api.routes.sources.extract_content_key", return_value="shared-key"):
        with patch("app.api.routes.sources.clone_source") as mock_task:
            mock_result = MagicMock()
            mock_result.id = "fake-clone-task-001"
            mock_task.delay.return_value = mock_result

            res = await client.post("/api/v1/sources", data={
                "url": "https://www.youtube.com/watch?v=kCc8FmEb1nY",
            })

    assert res.status_code == 201
    source_id = uuid.UUID(res.json()["id"])
    tasks = (
        await db_session.execute(
            select(SourceTask).where(SourceTask.source_id == source_id)
        )
    ).scalars().all()

    assert len(tasks) == 1
    assert tasks[0].task_type == "source_processing"
    assert tasks[0].status == "pending"
    assert tasks[0].celery_task_id == "fake-clone-task-001"


@pytest.mark.asyncio
async def test_get_source_returns_latest_processing_and_course_task_summaries(
    client, db_session, demo_user
):
    source = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=test",
        title="Summaries source",
        status="ready",
        celery_task_id="course-task-1",
        created_by=demo_user.id,
    )
    db_session.add(source)
    await db_session.flush()

    db_session.add(
        SourceTask(
            source_id=source.id,
            task_type="source_processing",
            status="success",
            stage="ready",
            celery_task_id="processing-task-1",
        )
    )
    db_session.add(
        SourceTask(
            source_id=source.id,
            task_type="course_generation",
            status="failure",
            stage="error",
            error_summary="broker unavailable",
            celery_task_id="course-task-1",
        )
    )
    await db_session.commit()

    res = await client.get(f"/api/v1/sources/{source.id}")

    assert res.status_code == 200
    data = res.json()
    assert data["task_id"] == "course-task-1"
    assert data["latest_processing_task"] == {
        "task_type": "source_processing",
        "status": "success",
        "stage": "ready",
        "error_summary": None,
        "celery_task_id": "processing-task-1",
    }
    assert data["latest_course_task"] == {
        "task_type": "course_generation",
        "status": "failure",
        "stage": "error",
        "error_summary": "broker unavailable",
        "celery_task_id": "course-task-1",
    }


@pytest.mark.asyncio
async def test_list_sources_returns_task_and_course_summaries(
    client, db_session, demo_user
):
    source = Source(
        type="pdf",
        title="Transformer Notes",
        status="ready",
        created_by=demo_user.id,
        metadata_={"original_filename": "transformer.pdf"},
    )
    db_session.add(source)
    await db_session.flush()

    db_session.add_all([
        SourceTask(
            source_id=source.id,
            task_type="source_processing",
            status="success",
            stage="ready",
        ),
        SourceTask(
            source_id=source.id,
            task_type="course_generation",
            status="running",
            stage="assembling_course",
        ),
    ])
    await db_session.flush()

    res = await client.get("/api/v1/sources?status=processing&query=Transformer&sort=actionable")
    assert res.status_code == 200
    item = res.json()["items"][0]
    assert item["latest_processing_task"]["status"] == "success"
    assert item["latest_course_task"]["stage"] == "assembling_course"
    assert item["course_count"] == 0


@pytest.mark.asyncio
async def test_list_sources_query_matches_original_filename(
    client, db_session, demo_user
):
    matching = Source(
        type="pdf",
        title="Lecture Notes",
        status="ready",
        created_by=demo_user.id,
        metadata_={"original_filename": "transformer.pdf"},
    )
    other = Source(
        type="pdf",
        title="Unrelated Notes",
        status="ready",
        created_by=demo_user.id,
        metadata_={"original_filename": "optimizer.pdf"},
    )
    db_session.add_all([matching, other])
    await db_session.flush()

    res = await client.get("/api/v1/sources?query=transformer")
    assert res.status_code == 200
    items = res.json()["items"]
    assert [item["id"] for item in items] == [str(matching.id)]


@pytest.mark.asyncio
async def test_list_sources_filters_statuses_source_centrically(
    client, db_session, demo_user
):
    processing = Source(
        type="youtube",
        title="Processing Source",
        status="pending",
        created_by=demo_user.id,
    )
    failure = Source(
        type="pdf",
        title="Failure Source",
        status="ready",
        created_by=demo_user.id,
    )
    ready = Source(
        type="markdown",
        title="Ready Source",
        status="ready",
        created_by=demo_user.id,
    )
    db_session.add_all([processing, failure, ready])
    await db_session.flush()

    db_session.add_all([
        SourceTask(
            source_id=processing.id,
            task_type="source_processing",
            status="running",
            stage="extracting",
        ),
        SourceTask(
            source_id=failure.id,
            task_type="source_processing",
            status="success",
            stage="ready",
        ),
        SourceTask(
            source_id=failure.id,
            task_type="course_generation",
            status="failure",
            stage="error",
            error_summary="course failed",
        ),
        SourceTask(
            source_id=ready.id,
            task_type="source_processing",
            status="success",
            stage="ready",
        ),
    ])
    await db_session.flush()

    failure_res = await client.get("/api/v1/sources?status=failure")
    assert failure_res.status_code == 200
    assert [item["id"] for item in failure_res.json()["items"]] == [str(failure.id)]

    processing_res = await client.get("/api/v1/sources?status=processing")
    assert processing_res.status_code == 200
    assert [item["id"] for item in processing_res.json()["items"]] == [str(processing.id)]

    ready_res = await client.get("/api/v1/sources?status=ready")
    assert ready_res.status_code == 200
    assert [item["id"] for item in ready_res.json()["items"]] == [str(ready.id)]


@pytest.mark.asyncio
async def test_list_sources_uses_course_sources_for_course_summary(
    client, db_session, demo_user
):
    source = Source(
        type="pdf",
        title="Course Summary Source",
        status="ready",
        created_by=demo_user.id,
    )
    db_session.add(source)
    await db_session.flush()

    older_course = Course(
        title="Older Course",
        description=None,
        created_by=demo_user.id,
    )
    older_course.created_at = datetime(2026, 1, 1, 10, 0, 0)
    older_course.updated_at = older_course.created_at
    newer_course = Course(
        title="Newer Course",
        description=None,
        created_by=demo_user.id,
    )
    newer_course.created_at = datetime(2026, 1, 2, 10, 0, 0)
    newer_course.updated_at = newer_course.created_at
    db_session.add_all([older_course, newer_course])
    await db_session.flush()

    db_session.add_all([
        CourseSource(course_id=older_course.id, source_id=source.id),
        CourseSource(course_id=newer_course.id, source_id=source.id),
    ])
    await db_session.flush()

    res = await client.get("/api/v1/sources")
    assert res.status_code == 200
    item = next(entry for entry in res.json()["items"] if entry["id"] == str(source.id))
    assert item["course_count"] == 2
    assert item["latest_course_id"] == str(newer_course.id)


@pytest.mark.asyncio
async def test_list_sources_sorts_actionable_before_recent(
    client, db_session, demo_user
):
    failure = Source(
        type="pdf",
        title="Failure",
        status="ready",
        created_by=demo_user.id,
    )
    processing = Source(
        type="youtube",
        title="Processing",
        status="pending",
        created_by=demo_user.id,
    )
    recent = Source(
        type="markdown",
        title="Recent",
        status="ready",
        created_by=demo_user.id,
    )
    failure.created_at = datetime(2026, 1, 1, 9, 0, 0)
    processing.created_at = datetime(2026, 1, 2, 9, 0, 0)
    recent.created_at = datetime(2026, 1, 3, 9, 0, 0)
    for source in (failure, processing, recent):
        source.updated_at = source.created_at
    db_session.add_all([failure, processing, recent])
    await db_session.flush()

    db_session.add_all([
        SourceTask(
            source_id=failure.id,
            task_type="source_processing",
            status="success",
            stage="ready",
        ),
        SourceTask(
            source_id=failure.id,
            task_type="course_generation",
            status="failure",
            stage="error",
            error_summary="course failed",
        ),
        SourceTask(
            source_id=processing.id,
            task_type="source_processing",
            status="running",
            stage="extracting",
        ),
        SourceTask(
            source_id=recent.id,
            task_type="source_processing",
            status="success",
            stage="ready",
        ),
    ])
    await db_session.flush()

    actionable_res = await client.get("/api/v1/sources?sort=actionable")
    assert actionable_res.status_code == 200
    actionable_ids = [item["id"] for item in actionable_res.json()["items"]]
    assert actionable_ids[:2] == [str(failure.id), str(processing.id)]

    recent_res = await client.get("/api/v1/sources?sort=recent")
    assert recent_res.status_code == 200
    recent_ids = [item["id"] for item in recent_res.json()["items"]]
    assert recent_ids[:3] == [str(recent.id), str(processing.id), str(failure.id)]
