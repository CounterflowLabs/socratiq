from types import SimpleNamespace
from unittest.mock import AsyncMock
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.models.content_chunk import ContentChunk
from app.db.models.source import Source
from app.db.models.source_task import SourceTask
from app.services.source_tasks import (
    dispatch_course_generation,
    finish_source_processing_and_enqueue_course,
    recover_course_generation_dispatch_failure,
)
from app.worker.tasks import course_generation


def test_source_task_metadata_followup_migration_exists():
    versions_dir = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    migration_texts = [
        path.read_text()
        for path in versions_dir.glob("*.py")
        if path.name != "c1d2e3f4a5b6_add_lifecycle_fields_to_source_tasks.py"
    ]

    assert any(
        'down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"' in text
        and '"source_tasks"' in text
        and '"metadata_"' in text
        and "op.add_column(" in text
        for text in migration_texts
    )


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
        "app.services.source_tasks.uuid4",
        lambda: "course-1",
    )

    completion = await finish_source_processing_and_enqueue_course(
        db=db_session,
        source=source,
        processing_task=processing_task,
        payload={"source_id": str(source.id)},
    )

    assert completion.result["queued_course_task_id"] == "course-1"
    assert source.celery_task_id == "course-1"
    tasks = (
        await db_session.execute(
            select(SourceTask).where(SourceTask.source_id == source.id)
        )
    ).scalars().all()
    task_by_type = {task.task_type: task for task in tasks}
    assert set(task_by_type) == {"source_processing", "course_generation"}
    assert task_by_type["course_generation"].celery_task_id == "course-1"
    assert task_by_type["course_generation"].status == "pending"


def test_dispatch_course_generation_uses_preallocated_task_id(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "app.services.source_tasks.generate_course_task.apply_async",
        lambda args=None, kwargs=None, task_id=None: captured.update(
            {"args": args, "kwargs": kwargs, "task_id": task_id}
        ),
    )

    dispatch_course_generation(
        payload={"source_id": "source-1"},
        task_id="course-1",
        goal="overview",
        user_id="user-1",
    )

    assert captured == {
        "args": [{"source_id": "source-1"}],
        "kwargs": {"goal": "overview", "user_id": "user-1"},
        "task_id": "course-1",
    }


@pytest.mark.asyncio
async def test_recover_course_generation_dispatch_failure_rolls_back_source_task_pointer(
    db_session, demo_user
):
    source = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=test",
        title="Source Title",
        status="ready",
        celery_task_id="course-1",
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
            celery_task_id="processing-1",
        )
    )
    db_session.add(
        SourceTask(
            source_id=source.id,
            task_type="course_generation",
            status="pending",
            stage="pending",
            celery_task_id="course-1",
        )
    )
    await db_session.commit()

    await recover_course_generation_dispatch_failure(
        session_factory=lambda: db_session,
        source_id=source.id,
        course_task_id="course-1",
        fallback_task_id="processing-1",
        error_message="broker unavailable",
    )

    source_row = await db_session.get(Source, source.id)
    tasks = (
        await db_session.execute(
            select(SourceTask).where(SourceTask.source_id == source.id)
        )
    ).scalars().all()
    task_by_type = {task.task_type: task for task in tasks}

    assert source_row.status == "ready"
    assert source_row.celery_task_id == "processing-1"
    assert task_by_type["course_generation"].status == "failure"
    assert task_by_type["course_generation"].stage == "error"
    assert task_by_type["course_generation"].error_summary == "broker unavailable"


@pytest.mark.asyncio
async def test_generate_course_marks_task_success_with_course_id(
    monkeypatch, db_session, demo_user
):
    source = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=test",
        title="Generated Course Source",
        status="ready",
        metadata_={
            "asset_plan": {
                "lab_mode": "inline",
                "graph_mode": "inline_and_overview",
                "study_surface": "reader",
            },
            "lesson_by_page": {
                "0": {
                    "title": "Page 1",
                    "summary": "lesson summary",
                    "sections": [
                        {
                            "code_snippets": [],
                            "key_concepts": ["testing"],
                        }
                    ],
                    "blocks": [],
                }
            },
            "graph_by_page": {
                "0": {
                    "current": ["testing"],
                    "prerequisites": ["python basics"],
                    "unlocks": ["fixtures"],
                    "section_anchor": 0,
                }
            },
            "labs_by_page": {
                "0": {
                    "title": "Testing Lab",
                    "description": "Write a test",
                    "language": "python",
                    "starter_code": {"files": []},
                    "test_code": {"files": []},
                    "solution_code": {"files": []},
                    "run_instructions": "pytest",
                    "confidence": 0.9,
                }
            },
        },
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
