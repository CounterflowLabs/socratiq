from types import SimpleNamespace
from unittest.mock import AsyncMock
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select

from app.db.models.content_chunk import ContentChunk
from app.db.models.course import Section
from app.db.models.source import Source
from app.db.models.source_task import SourceTask
from app.services.source_tasks import (
    dispatch_course_generation,
    finish_source_processing_and_enqueue_course,
    recover_course_generation_dispatch_failure,
)
from app.services.course_generator import CourseGenerator
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


@pytest.mark.asyncio
async def test_dispatch_course_generation_uses_preallocated_task_id(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_enqueue(name, *args, job_id=None, **kwargs):
        captured.update(
            {"name": name, "args": args, "job_id": job_id, "kwargs": kwargs}
        )
        return job_id

    monkeypatch.setattr("app.worker.queue.enqueue", fake_enqueue)

    await dispatch_course_generation(
        payload={"source_id": "source-1"},
        task_id="course-1",
        user_id="user-1",
    )

    assert captured == {
        "name": "generate_course",
        "args": ({"source_id": "source-1"},),
        "job_id": "course-1",
        "kwargs": {"user_id": "user-1"},
    }


@pytest.mark.asyncio
async def test_course_generator_reports_section_progress(
    monkeypatch, db_session, demo_user
):
    source = Source(
        type="bilibili",
        url="https://www.bilibili.com/video/BV-progress",
        title="Progress Source",
        status="ready",
        metadata_={},
        created_by=demo_user.id,
    )
    db_session.add(source)
    await db_session.flush()
    db_session.add_all(
        [
            ContentChunk(
                source_id=source.id,
                text="input layer transcript",
                metadata_={"topic": "输入层"},
            ),
            ContentChunk(
                source_id=source.id,
                text="hidden layer transcript",
                metadata_={"topic": "隐藏层"},
            ),
        ]
    )
    await db_session.flush()

    class FakeLesson:
        def __init__(self, title: str):
            self._title = title

        def model_dump(self):
            return {
                "title": self._title,
                "summary": "summary",
                "sections": [],
                "blocks": [],
            }

    class FakeLessonGenerator:
        def __init__(self, *_args, **_kwargs):
            pass

        async def generate(self, *, video_title, **_kwargs):
            return FakeLesson(str(video_title))

    class FakeLabGenerator:
        def __init__(self, *_args, **_kwargs):
            pass

    from app.services import course_generator as course_generator_module

    monkeypatch.setattr(
        course_generator_module,
        "LessonGenerator",
        FakeLessonGenerator,
    )
    monkeypatch.setattr(course_generator_module, "LabGenerator", FakeLabGenerator)

    provider = SimpleNamespace(
        chat=AsyncMock(
            return_value=SimpleNamespace(
                content=[SimpleNamespace(type="text", text="description")]
            )
        ),
        model_id=lambda: "test-model",
    )
    router = SimpleNamespace(get_provider=AsyncMock(return_value=provider))
    updates: list[tuple[UUID, dict]] = []

    async def report_progress(source_id, progress):
        updates.append((source_id, progress))

    await CourseGenerator(router).generate(
        db=db_session,
        source_ids=[source.id],
        target_language="zh-CN",
        user_id=demo_user.id,
        skip_ready_check=True,
        section_progress_callback=report_progress,
    )

    assert updates
    assert all(source_id == source.id for source_id, _ in updates)
    final_progress = updates[-1][1]
    assert final_progress["total"] == 2
    assert final_progress["completed"] == 2
    assert [item["status"] for item in final_progress["items"]] == [
        "success",
        "success",
    ]
    assert {item["title"] for item in final_progress["items"]} == {"输入层", "隐藏层"}


@pytest.mark.asyncio
async def test_course_generator_sorts_bucket_chunks_by_source_time(
    monkeypatch, db_session, demo_user
):
    source = Source(
        type="bilibili",
        url="https://www.bilibili.com/video/BV-time",
        title="Timed Source",
        status="ready",
        metadata_={},
        created_by=demo_user.id,
    )
    db_session.add(source)
    await db_session.flush()
    db_session.add_all(
        [
            ContentChunk(
                source_id=source.id,
                text="sigmoid transcript",
                metadata_={
                    "topic": "Sigmoid",
                    "start_time": 612.0,
                    "end_time": 673.0,
                    "section_bucket": 1,
                    "section_bucket_topic": "Weights and activation",
                    "concepts": ["activation_function"],
                },
            ),
            ContentChunk(
                source_id=source.id,
                text="edge transcript",
                metadata_={
                    "topic": "Edges",
                    "start_time": 490.0,
                    "end_time": 552.0,
                    "section_bucket": 1,
                    "section_bucket_topic": "Weights and activation",
                    "concepts": ["weighted_sum"],
                },
            ),
            ContentChunk(
                source_id=source.id,
                text="matrix transcript",
                metadata_={
                    "topic": "Matrix",
                    "start_time": 794.0,
                    "end_time": 856.0,
                    "section_bucket": 2,
                    "section_bucket_topic": "Matrix view",
                    "concepts": ["matrix_vector_multiplication"],
                },
            ),
        ]
    )
    await db_session.flush()

    captured: list[dict] = []

    class FakeLesson:
        def __init__(self, title: str):
            self._title = title

        def model_dump(self):
            return {
                "title": self._title,
                "summary": "summary",
                "sections": [],
                "blocks": [
                    {"type": "recap", "title": "r", "body": "summary"},
                ],
            }

    class FakeLessonGenerator:
        def __init__(self, *_args, **_kwargs):
            pass

        async def generate(self, *, video_title, **kwargs):
            captured.append({"video_title": video_title, **kwargs})
            return FakeLesson(str(video_title))

    class FakeLabGenerator:
        def __init__(self, *_args, **_kwargs):
            pass

    from app.services import course_generator as course_generator_module

    monkeypatch.setattr(
        course_generator_module,
        "LessonGenerator",
        FakeLessonGenerator,
    )
    monkeypatch.setattr(course_generator_module, "LabGenerator", FakeLabGenerator)

    provider = SimpleNamespace(
        chat=AsyncMock(
            return_value=SimpleNamespace(
                content=[SimpleNamespace(type="text", text="description")]
            )
        ),
        model_id=lambda: "test-model",
    )
    router = SimpleNamespace(get_provider=AsyncMock(return_value=provider))

    course = await CourseGenerator(router).generate(
        db=db_session,
        source_ids=[source.id],
        target_language="zh-CN",
        user_id=demo_user.id,
        skip_ready_check=True,
    )

    sections = (
        await db_session.execute(
            select(Section).where(Section.course_id == course.id).order_by(Section.order_index)
        )
    ).scalars().all()

    assert [(s.source_start, s.source_end) for s in sections] == [
        ("490s", "673s"),
        ("794s", "856s"),
    ]
    first_call_chunks = captured[0]["source_chunks"]
    assert [chunk.start_sec for chunk in first_call_chunks] == [490.0, 612.0]
    assert captured[0]["next_section_title"] == "Matrix view"
    assert captured[1]["previous_section_title"] == "Weights and activation"
    assert captured[0]["research_cards"]
    assert sections[0].content["research_cards"][0]["source_title"] == (
        "KAN: Kolmogorov-Arnold Networks"
    )


@pytest.mark.asyncio
async def test_generate_course_ignores_legacy_goal_kwarg(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_generate_course_async(
        task, source_id, user_id, resources, event_bus=None
    ):
        captured.update(
            {
                "source_id": source_id,
                "user_id": user_id,
                "resources": resources,
            }
        )
        return {"status": "ready"}

    monkeypatch.setattr(
        course_generation,
        "_generate_course_async",
        fake_generate_course_async,
    )

    ctx = {"resources": "RES", "job_id": "job-1"}
    result = await course_generation.generate_course(
        ctx,
        {"source_id": "source-1"},
        user_id="user-1",
        goal="legacy-goal",
    )

    assert result == {"status": "ready"}
    assert captured == {
        "source_id": "source-1",
        "user_id": "user-1",
        "resources": "RES",
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
        ),
        model_id=lambda: "test-model",
    )
    fake_resources = SimpleNamespace(
        settings=SimpleNamespace(),
        engine=FakeEngine(),
        session_factory=FakeSessionFactory(db_session),
        model_router=SimpleNamespace(
            get_provider=AsyncMock(return_value=fake_provider)
        ),
    )

    task_updates: list[tuple[str, dict]] = []

    class FakeTask:
        def update_state(self, state, meta=None):
            task_updates.append((state, meta or {}))

    result = await course_generation._generate_course_async(
        FakeTask(),
        str(source.id),
        str(demo_user.id),
        fake_resources,
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
    assert "goal" not in result
    assert task_row.status == "success"
    assert task_row.stage == "ready"
    assert task_row.metadata_["course_id"] == result["course_id"]
    assert any(meta.get("stage") == "assembling_course" for _, meta in task_updates)


@pytest.mark.asyncio
async def test_generate_course_skip_branch_marks_current_task_success(
    monkeypatch, db_session, demo_user
):
    """Regression: redelivered course_generation that hits the idempotency
    skip must still mark its own preallocated SourceTask row as success.

    Before the fix, the loser of a concurrent-ingest race left its row
    pending forever and /sources/{id}/progress reported "课程生成中".
    """
    source = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=test-skip",
        title="Skip Branch Source",
        status="ready",
        metadata_={},
        created_by=demo_user.id,
    )
    db_session.add(source)
    await db_session.flush()

    # The first run produced the course and marked its row success.
    existing_course_id = "00000000-0000-0000-0000-0000000000aa"
    from datetime import datetime, timedelta

    first_row = SourceTask(
        source_id=source.id,
        task_type="course_generation",
        status="success",
        stage="ready",
        celery_task_id="course-first-run",
        metadata_={"course_id": existing_course_id},
    )
    first_row.created_at = datetime(2026, 1, 1, 12, 0, 0)
    # The second (concurrent) run preallocated a pending row — this is the
    # one we expect the skip branch to fix up. Force the timestamp so it
    # genuinely sorts after the success row (server_default=now() ties when
    # two rows insert in the same transaction).
    second_row = SourceTask(
        source_id=source.id,
        task_type="course_generation",
        status="pending",
        stage="pending",
        celery_task_id="course-second-run",
    )
    second_row.created_at = datetime(2026, 1, 1, 12, 0, 0) + timedelta(seconds=5)
    db_session.add_all([first_row, second_row])
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

    fake_resources = SimpleNamespace(
        settings=SimpleNamespace(),
        engine=FakeEngine(),
        session_factory=FakeSessionFactory(db_session),
        model_router=SimpleNamespace(get_provider=AsyncMock()),
    )

    # _generate_course_async is called directly with fake_resources below, so
    # no worker-resources factory patching is needed (ARQ passes resources via
    # the job ctx in production).

    class FakeTask:
        def update_state(self, *_args, **_kwargs):
            return None

    result = await course_generation._generate_course_async(
        FakeTask(),
        str(source.id),
        str(demo_user.id),
        fake_resources,
    )

    assert result == {
        "source_id": str(source.id),
        "course_id": existing_course_id,
        "status": "ready",
        "skipped": True,
    }

    # The latest-by-created_at row (the second-run preallocated row) must
    # now be success with course_id pointing at the existing course.
    latest = (
        await db_session.execute(
            select(SourceTask)
            .where(
                SourceTask.source_id == source.id,
                SourceTask.task_type == "course_generation",
            )
            .order_by(SourceTask.created_at.desc())
            .limit(1)
        )
    ).scalar_one()
    assert latest.celery_task_id == "course-second-run"
    assert latest.status == "success"
    assert latest.stage == "ready"
    assert latest.metadata_["course_id"] == existing_course_id


@pytest.mark.asyncio
async def test_generate_course_legacy_metadata_without_asset_plan_still_creates_labs(
    monkeypatch, db_session, demo_user
):
    source = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=legacy",
        title="Legacy Course Source",
        status="ready",
        metadata_={
            "lesson_by_page": {
                "0": {
                    "title": "Legacy Page",
                    "summary": "legacy lesson summary",
                    "sections": [
                        {
                            "code_snippets": [],
                            "key_concepts": ["legacy-testing"],
                        }
                    ],
                    "blocks": [],
                }
            },
            "labs_by_page": {
                "0": {
                    "title": "Legacy Lab",
                    "description": "Still create this lab",
                    "language": "python",
                    "starter_code": {"files": []},
                    "test_code": {"files": []},
                    "solution_code": {"files": []},
                    "run_instructions": "pytest",
                    "confidence": 0.8,
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
            text="legacy chunk text",
            metadata_={"page_index": 0, "page_title": "Legacy Page"},
        )
    )
    db_session.add(
        SourceTask(
            source_id=source.id,
            task_type="course_generation",
            status="pending",
            celery_task_id="course-task-legacy",
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
                content=[SimpleNamespace(type="text", text="Legacy course description.")]
            )
        ),
        model_id=lambda: "test-model",
    )
    fake_resources = SimpleNamespace(
        settings=SimpleNamespace(),
        engine=FakeEngine(),
        session_factory=FakeSessionFactory(db_session),
        model_router=SimpleNamespace(
            get_provider=AsyncMock(return_value=fake_provider)
        ),
    )

    # _generate_course_async is called directly with fake_resources below, so
    # no worker-resources factory patching is needed (ARQ passes resources via
    # the job ctx in production).

    class FakeTask:
        def update_state(self, *_args, **_kwargs):
            return None

    result = await course_generation._generate_course_async(
        FakeTask(),
        str(source.id),
        str(demo_user.id),
        fake_resources,
    )

    task_row = (
        await db_session.execute(
            select(SourceTask).where(
                SourceTask.source_id == source.id,
                SourceTask.task_type == "course_generation",
            )
        )
    ).scalar_one()

    from app.db.models.course import Section
    from app.db.models.lab import Lab

    course_id = UUID(task_row.metadata_["course_id"])
    course_sections = (
        await db_session.execute(
            select(Section).where(Section.course_id == course_id)
        )
    ).scalars().all()
    course_labs = (
        await db_session.execute(
            select(Lab)
            .join(Section, Lab.section_id == Section.id)
            .where(Section.course_id == course_id)
        )
    ).scalars().all()

    assert result["status"] == "ready"
    assert result["labs_created"] == 1
    assert len(course_sections) == 1
    assert len(course_labs) == 1
    assert course_sections[0].content["lab_mode"] == "inline"
