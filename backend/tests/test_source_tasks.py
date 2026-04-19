from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.db.models.content_chunk import ContentChunk
from app.db.models.source import Source
from app.db.models.source_task import SourceTask
from app.services.source_tasks import finish_source_processing_and_enqueue_course
from app.worker.tasks import course_generation


@pytest.mark.asyncio
async def test_finish_source_processing_enqueues_course_generation_task(
    monkeypatch, db_session, demo_user
):
    source = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=test",
        title="Source Title",
        status="pending",
        created_by=demo_user.id,
    )
    db_session.add(source)
    await db_session.flush()

    processing_task = SourceTask(
        source_id=source.id,
        task_type="source_processing",
        status="running",
        celery_task_id="processing-1",
    )
    db_session.add(processing_task)
    await db_session.flush()

    monkeypatch.setattr(
        "app.services.source_tasks.generate_course_task.delay",
        lambda payload, goal=None, user_id=None: SimpleNamespace(id="course-1"),
    )

    result = await finish_source_processing_and_enqueue_course(
        db=db_session,
        source=source,
        processing_task=processing_task,
        payload={"source_id": str(source.id)},
    )

    assert result["queued_course_task_id"] == "course-1"
    tasks = (
        await db_session.execute(
            select(SourceTask).where(SourceTask.source_id == source.id)
        )
    ).scalars().all()
    assert {task.task_type for task in tasks} == {
        "source_processing",
        "course_generation",
    }


@pytest.mark.asyncio
async def test_generate_course_marks_task_success_with_course_id(
    monkeypatch, db_session, demo_user
):
    source = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=test",
        title="Generated Course Source",
        status="ready",
        metadata_={},
        created_by=demo_user.id,
    )
    db_session.add(source)
    await db_session.flush()

    db_session.add(
        ContentChunk(
            source_id=source.id,
            text="chunk text",
            metadata_={"page_index": 0, "page_title": "Page 1"},
        )
    )
    db_session.add(
        SourceTask(
            source_id=source.id,
            task_type="course_generation",
            status="pending",
            celery_task_id="course-task-1",
        )
    )
    await db_session.flush()

    class FakeAsyncContext:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeSessionFactory:
        def __init__(self, session):
            self._session = session

        def __call__(self):
            return FakeAsyncContext(self._session)

    class FakeEngine:
        async def dispose(self):
            return None

    fake_provider = SimpleNamespace(
        chat=AsyncMock(
            return_value=SimpleNamespace(
                content=[SimpleNamespace(type="text", text="Short course description.")]
            )
        )
    )
    fake_resources = SimpleNamespace(
        settings=SimpleNamespace(),
        engine=FakeEngine(),
        session_factory=FakeSessionFactory(db_session),
        model_router=SimpleNamespace(
            get_provider=AsyncMock(return_value=fake_provider)
        ),
    )

    monkeypatch.setattr(
        course_generation,
        "_create_worker_resources",
        lambda: fake_resources,
    )

    class FakeLessonContent:
        summary = "lesson summary"
        sections = [SimpleNamespace(code_snippets=[], key_concepts=["testing"])]

        def model_dump(self):
            return {
                "summary": self.summary,
                "sections": [{"code_snippets": [], "key_concepts": ["testing"]}],
            }

    class FakeLessonGenerator:
        def __init__(self, *_args, **_kwargs):
            pass

        async def generate(self, *_args, **_kwargs):
            return FakeLessonContent()

    class FakeLabGenerator:
        def __init__(self, *_args, **_kwargs):
            pass

        async def generate(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        "app.services.lesson_generator.LessonGenerator",
        FakeLessonGenerator,
    )
    monkeypatch.setattr(
        "app.services.lab_generator.LabGenerator",
        FakeLabGenerator,
    )

    task_updates: list[tuple[str, dict]] = []

    class FakeTask:
        def update_state(self, state, meta=None):
            task_updates.append((state, meta or {}))

    result = await course_generation._generate_course_async(
        FakeTask(),
        str(source.id),
        goal="overview",
        user_id=str(demo_user.id),
    )

    task_row = (
        await db_session.execute(
            select(SourceTask).where(
                SourceTask.source_id == source.id,
                SourceTask.task_type == "course_generation",
            )
        )
    ).scalar_one()

    assert result["status"] == "ready"
    assert task_row.status == "success"
    assert task_row.stage == "ready"
    assert task_row.metadata_["course_id"] == result["course_id"]
    assert any(meta.get("stage") == "assembling_course" for _, meta in task_updates)
