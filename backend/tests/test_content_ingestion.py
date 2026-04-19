"""Regression tests for content ingestion worker isolation."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.db.models.content_chunk import ContentChunk
from app.worker.tasks import content_ingestion
from app.worker import ref_subscriber
from app.db.models.source import Source
from app.db.models.source_task import SourceTask
from app.db.models.whisper_config import WhisperConfig
from app.services.llm.encryption import encrypt_api_key


def test_create_worker_resources_builds_dedicated_session_factory(monkeypatch):
    engine = object()
    session_factory = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        content_ingestion,
        "get_settings",
        lambda: SimpleNamespace(
            database_url="postgresql+asyncpg://test/test",
            llm_encryption_key="secret",
        ),
    )
    def fake_create_async_engine(url, **kwargs):
        captured["engine_call"] = (url, kwargs)
        return engine

    def fake_async_sessionmaker(*args, **kwargs):
        captured["session_call"] = (args, kwargs)
        return session_factory

    monkeypatch.setattr(content_ingestion, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(content_ingestion, "async_sessionmaker", fake_async_sessionmaker)

    class FakeModelRouter:
        def __init__(self, *, session_factory, encryption_key):
            captured["router_call"] = {
                "session_factory": session_factory,
                "encryption_key": encryption_key,
            }

    monkeypatch.setattr(content_ingestion, "ModelRouter", FakeModelRouter)

    resources = content_ingestion._create_worker_resources()

    assert resources.settings.database_url == "postgresql+asyncpg://test/test"
    assert resources.engine is engine
    assert resources.session_factory is session_factory
    assert captured["engine_call"] == (
        "postgresql+asyncpg://test/test",
        {"echo": False, "pool_size": 5, "max_overflow": 10},
    )
    assert captured["session_call"][0] == (engine,)
    assert captured["session_call"][1]["class_"] is content_ingestion.AsyncSession
    assert captured["session_call"][1]["expire_on_commit"] is False
    assert captured["router_call"] == {
        "session_factory": session_factory,
        "encryption_key": "secret",
    }


def test_create_worker_resources_returns_fresh_session_factory_each_time(monkeypatch):
    session_factories = [object(), object()]
    engine_instances = [object(), object()]
    calls = {"engines": 0, "factories": 0}

    monkeypatch.setattr(
        content_ingestion,
        "get_settings",
        lambda: SimpleNamespace(
            database_url="postgresql+asyncpg://test/test",
            llm_encryption_key="secret",
        ),
    )

    def fake_create_async_engine(*args, **kwargs):
        index = calls["engines"]
        calls["engines"] += 1
        return engine_instances[index]

    def fake_async_sessionmaker(*args, **kwargs):
        index = calls["factories"]
        calls["factories"] += 1
        return session_factories[index]

    class FakeModelRouter:
        def __init__(self, *, session_factory, encryption_key):
            self.session_factory = session_factory
            self.encryption_key = encryption_key

    monkeypatch.setattr(content_ingestion, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(content_ingestion, "async_sessionmaker", fake_async_sessionmaker)
    monkeypatch.setattr(content_ingestion, "ModelRouter", FakeModelRouter)

    first = content_ingestion._create_worker_resources()
    second = content_ingestion._create_worker_resources()

    assert first.engine is engine_instances[0]
    assert second.engine is engine_instances[1]
    assert first.session_factory is session_factories[0]
    assert second.session_factory is session_factories[1]
    assert first.session_factory is not second.session_factory
    assert first.model_router.session_factory is session_factories[0]
    assert second.model_router.session_factory is session_factories[1]


@pytest.mark.asyncio
async def test_get_whisper_config_falls_back_to_env_when_stored_key_is_unreadable(
    monkeypatch,
    db_session,
    demo_user,
):
    wrong_key = Fernet.generate_key().decode()
    db_session.add(
        WhisperConfig(
            user_id=demo_user.id,
            mode="api",
            api_base_url="https://example.invalid/v1",
            api_model="custom-whisper",
            api_key_encrypted=encrypt_api_key("stored-secret", wrong_key),
            local_model="small",
        )
    )
    await db_session.flush()

    monkeypatch.setattr(
        content_ingestion,
        "get_settings",
        lambda: SimpleNamespace(
            llm_encryption_key="current-key",
            whisper_mode="local",
            whisper_model="base",
            whisper_api_key="env-secret",
            whisper_api_base_url="https://api.groq.com/openai/v1",
            whisper_api_model="whisper-large-v3",
        ),
    )

    config = await content_ingestion._get_whisper_config(db_session)

    assert config == {
        "whisper_mode": "api",
        "whisper_model": "small",
        "whisper_api_key": "env-secret",
        "whisper_api_base_url": "https://example.invalid/v1",
        "whisper_api_model": "custom-whisper",
    }


@pytest.mark.asyncio
async def test_ingest_source_queues_course_generation_when_pipeline_finishes(
    monkeypatch, db_session, demo_user
):
    source = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=test",
        title="Pending source",
        status="pending",
        metadata_={},
        created_by=demo_user.id,
    )
    db_session.add(source)
    await db_session.flush()

    processing_task = SourceTask(
        source_id=source.id,
        task_type="source_processing",
        status="pending",
        celery_task_id="processing-task-1",
    )
    db_session.add(processing_task)
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
        settings=SimpleNamespace(upload_dir="/tmp"),
        engine=FakeEngine(),
        session_factory=FakeSessionFactory(db_session),
        model_router=SimpleNamespace(get_provider=AsyncMock(return_value=SimpleNamespace())),
    )

    monkeypatch.setattr(
        content_ingestion,
        "_create_worker_resources",
        lambda: fake_resources,
    )
    async def fake_get_whisper_config(_db):
        return {}

    async def fake_get_bilibili_credential(_db):
        return None

    monkeypatch.setattr(content_ingestion, "_get_whisper_config", fake_get_whisper_config)
    monkeypatch.setattr(content_ingestion, "_get_bilibili_credential", fake_get_bilibili_credential)

    class FakeExtractor:
        async def extract(self, _input):
            return SimpleNamespace(
                title="Intro to Testing",
                metadata={"duration_seconds": 42},
                chunks=[SimpleNamespace(raw_text="chunk text")],
            )

    monkeypatch.setattr(
        content_ingestion,
        "_create_extractor",
        lambda *args, **kwargs: FakeExtractor(),
    )

    analyzed_chunk = SimpleNamespace(
        raw_text="chunk text",
        metadata={"page_index": 0, "page_title": "Testing 101"},
        topic="Testing 101",
        summary="summary",
        concepts=[],
        difficulty=1,
        key_terms=["test"],
        has_code=False,
        has_formula=False,
    )

    analysis = SimpleNamespace(
        concepts=[],
        chunks=[analyzed_chunk],
        overall_summary="overall summary",
        overall_difficulty=1,
        estimated_study_minutes=10,
        suggested_prerequisites=[],
    )

    class FakeAnalyzer:
        def __init__(self, *_args, **_kwargs):
            pass

        async def analyze(self, **_kwargs):
            return analysis

    class FakeLessonContent:
        summary = "lesson summary"
        sections = [SimpleNamespace(code_snippets=[], key_concepts=["test"])]

        def model_dump(self):
            return {
                "summary": self.summary,
                "sections": [
                    {
                        "code_snippets": [],
                        "key_concepts": ["test"],
                    }
                ],
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

    class FakeEmbeddingService:
        def __init__(self, *_args, **_kwargs):
            pass

        async def embed_and_store_chunks(self, *_args, **_kwargs):
            return None

        async def embed_and_store_concepts(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        "app.services.content_analyzer.ContentAnalyzer",
        FakeAnalyzer,
    )
    monkeypatch.setattr(
        "app.services.lesson_generator.LessonGenerator",
        FakeLessonGenerator,
    )
    monkeypatch.setattr(
        "app.services.lab_generator.LabGenerator",
        FakeLabGenerator,
    )
    monkeypatch.setattr(
        "app.services.embedding.EmbeddingService",
        FakeEmbeddingService,
    )
    monkeypatch.setattr(
        "app.services.source_tasks.uuid4",
        lambda: "course-task-1",
    )
    monkeypatch.setattr(
        content_ingestion,
        "dispatch_course_generation",
        lambda **kwargs: SimpleNamespace(id=kwargs["task_id"]),
    )

    task_updates: list[tuple[str, dict]] = []

    class FakeTask:
        def update_state(self, state, meta=None):
            task_updates.append((state, meta or {}))

    result = await content_ingestion._ingest_source_async(FakeTask(), str(source.id))

    assert result["status"] == "ready"
    assert result["queued_course_task_id"] == "course-task-1"

    source_row = await db_session.get(Source, source.id)
    assert source_row.status == "ready"
    assert source_row.celery_task_id == "course-task-1"

    tasks = (
        await db_session.execute(
            select(SourceTask).where(SourceTask.source_id == source.id)
        )
    ).scalars().all()
    assert {task.task_type for task in tasks} == {
        "source_processing",
        "course_generation",
    }
    assert any(meta.get("stage") == "embedding" for _, meta in task_updates)


@pytest.mark.asyncio
async def test_ingestion_persists_asset_plan_and_graph_by_page(
    monkeypatch, db_session, demo_user
):
    source = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=test-assets",
        title="Pending source",
        status="pending",
        metadata_={},
        created_by=demo_user.id,
    )
    db_session.add(source)
    await db_session.flush()

    db_session.add(
        SourceTask(
            source_id=source.id,
            task_type="source_processing",
            status="pending",
            celery_task_id="processing-task-assets",
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

    fake_resources = SimpleNamespace(
        settings=SimpleNamespace(upload_dir="/tmp"),
        engine=FakeEngine(),
        session_factory=FakeSessionFactory(db_session),
        model_router=SimpleNamespace(get_provider=AsyncMock(return_value=SimpleNamespace())),
    )

    monkeypatch.setattr(
        content_ingestion,
        "_create_worker_resources",
        lambda: fake_resources,
    )
    monkeypatch.setattr(content_ingestion, "_get_whisper_config", AsyncMock(return_value={}))
    monkeypatch.setattr(
        content_ingestion,
        "_get_bilibili_credential",
        AsyncMock(return_value=None),
    )

    class FakeExtractor:
        async def extract(self, _input):
            return SimpleNamespace(
                title="Intro to Attention",
                metadata={"duration_seconds": 42},
                chunks=[
                    SimpleNamespace(raw_text="attention chunk"),
                    SimpleNamespace(raw_text="decoder chunk"),
                ],
            )

    monkeypatch.setattr(
        content_ingestion,
        "_create_extractor",
        lambda *args, **kwargs: FakeExtractor(),
    )

    analysis = SimpleNamespace(
        concepts=[],
        chunks=[
            SimpleNamespace(
                raw_text="attention chunk",
                metadata={"page_index": 0, "page_title": "Attention"},
                topic="Attention",
                summary="attention summary",
                concepts=[],
                difficulty=1,
                key_terms=["attention"],
                has_code=False,
                has_formula=False,
            ),
            SimpleNamespace(
                raw_text="decoder chunk",
                metadata={"page_index": 1, "page_title": "Decoder"},
                topic="Decoder",
                summary="decoder summary",
                concepts=[],
                difficulty=2,
                key_terms=["decoder"],
                has_code=False,
                has_formula=False,
            ),
        ],
        overall_summary="Transformer overview",
        overall_difficulty=2,
        estimated_study_minutes=12,
        suggested_prerequisites=["Vectors", "Embeddings"],
    )

    class FakeAnalyzer:
        def __init__(self, *_args, **_kwargs):
            pass

        async def analyze(self, **_kwargs):
            return analysis

    class FakeLessonContent:
        def __init__(self, title, summary, key_concepts):
            self.title = title
            self.summary = summary
            self.sections = [
                SimpleNamespace(code_snippets=[], key_concepts=key_concepts)
            ]

        def model_dump(self):
            return {
                "title": self.title,
                "summary": self.summary,
                "sections": [
                    {
                        "code_snippets": [],
                        "key_concepts": self.sections[0].key_concepts,
                    }
                ],
                "blocks": [],
            }

    class FakeLessonGenerator:
        def __init__(self, *_args, **_kwargs):
            pass

        async def generate(self, chunk_texts, page_title, *_args, **_kwargs):
            summary = f"{page_title} summary from {len(chunk_texts)} chunks"
            return FakeLessonContent(page_title, summary, [page_title.lower()])

    class FakeEmbeddingService:
        def __init__(self, *_args, **_kwargs):
            pass

        async def embed_and_store_chunks(self, *_args, **_kwargs):
            return None

        async def embed_and_store_concepts(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr("app.services.content_analyzer.ContentAnalyzer", FakeAnalyzer)
    monkeypatch.setattr(
        "app.services.lesson_generator.LessonGenerator",
        FakeLessonGenerator,
    )
    monkeypatch.setattr(
        "app.services.embedding.EmbeddingService",
        FakeEmbeddingService,
    )
    monkeypatch.setattr("app.services.source_tasks.uuid4", lambda: "course-task-assets")
    monkeypatch.setattr(
        content_ingestion,
        "dispatch_course_generation",
        lambda **kwargs: SimpleNamespace(id=kwargs["task_id"]),
    )

    class FakeTask:
        def update_state(self, *_args, **_kwargs):
            return None

    result = await content_ingestion._ingest_source_async(FakeTask(), str(source.id))

    await db_session.refresh(source)

    assert result["status"] == "ready"
    assert source.metadata_["asset_plan"]["graph_mode"] == "inline_and_overview"
    assert source.metadata_["asset_plan"]["lab_mode"] == "none"
    assert source.metadata_["graph_by_page"] == {
        "0": {
            "current": ["attention"],
            "prerequisites": ["Vectors", "Embeddings"],
            "unlocks": [],
            "section_anchor": 0,
        },
        "1": {
            "current": ["decoder"],
            "prerequisites": ["Vectors", "Embeddings"],
            "unlocks": [],
            "section_anchor": 1,
        },
    }


@pytest.mark.asyncio
async def test_clone_source_queues_course_generation_when_clone_finishes(
    monkeypatch, db_session, demo_user
):
    donor = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=donor",
        title="Donor source",
        status="ready",
        raw_content="donor raw content",
        metadata_={"topic": "reuse"},
        created_by=demo_user.id,
    )
    target = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=target",
        title=None,
        status="pending",
        metadata_={},
        ref_source_id=donor.id,
        created_by=demo_user.id,
    )
    db_session.add_all([donor, target])
    await db_session.flush()

    db_session.add(
        ContentChunk(
            source_id=donor.id,
            text="donor chunk",
            metadata_={"page_index": 0, "page_title": "Cloned Page"},
        )
    )
    db_session.add(
        SourceTask(
            source_id=target.id,
            task_type="source_processing",
            status="running",
            celery_task_id="clone-processing-1",
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

    fake_resources = SimpleNamespace(
        settings=SimpleNamespace(upload_dir="/tmp"),
        engine=FakeEngine(),
        session_factory=FakeSessionFactory(db_session),
        model_router=SimpleNamespace(),
    )

    monkeypatch.setattr(
        content_ingestion,
        "_create_worker_resources",
        lambda: fake_resources,
    )
    monkeypatch.setattr(
        "app.services.source_tasks.uuid4",
        lambda: "course-task-from-clone",
    )
    monkeypatch.setattr(
        content_ingestion,
        "dispatch_course_generation",
        lambda **kwargs: SimpleNamespace(id=kwargs["task_id"]),
    )

    task_updates: list[tuple[str, dict]] = []

    class FakeTask:
        def update_state(self, state, meta=None):
            task_updates.append((state, meta or {}))

    result = await content_ingestion._clone_source_async(
        FakeTask(),
        str(target.id),
        str(donor.id),
    )

    target_row = await db_session.get(Source, target.id)
    tasks = (
        await db_session.execute(
            select(SourceTask).where(SourceTask.source_id == target.id)
        )
    ).scalars().all()
    task_by_type = {task.task_type: task for task in tasks}

    assert result["status"] == "ready"
    assert result["queued_course_task_id"] == "course-task-from-clone"
    assert target_row.status == "ready"
    assert target_row.celery_task_id == "course-task-from-clone"
    assert task_by_type["source_processing"].status == "success"
    assert task_by_type["source_processing"].stage == "ready"
    assert task_by_type["course_generation"].status == "pending"
    assert task_by_type["course_generation"].celery_task_id == "course-task-from-clone"
    assert any(meta.get("stage") == "cloning" for _, meta in task_updates)


@pytest.mark.asyncio
async def test_clone_source_recovers_when_course_dispatch_fails(
    monkeypatch, db_session, demo_user
):
    donor = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=donor",
        title="Donor source",
        status="ready",
        raw_content="donor raw content",
        metadata_={"topic": "reuse"},
        created_by=demo_user.id,
    )
    target = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=target",
        title=None,
        status="pending",
        metadata_={},
        ref_source_id=donor.id,
        created_by=demo_user.id,
    )
    db_session.add_all([donor, target])
    await db_session.flush()

    db_session.add(
        ContentChunk(
            source_id=donor.id,
            text="donor chunk",
            metadata_={"page_index": 0, "page_title": "Cloned Page"},
        )
    )
    db_session.add(
        SourceTask(
            source_id=target.id,
            task_type="source_processing",
            status="running",
            celery_task_id="clone-processing-1",
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

    fake_resources = SimpleNamespace(
        settings=SimpleNamespace(upload_dir="/tmp"),
        engine=FakeEngine(),
        session_factory=FakeSessionFactory(db_session),
        model_router=SimpleNamespace(),
    )

    monkeypatch.setattr(
        content_ingestion,
        "_create_worker_resources",
        lambda: fake_resources,
    )
    monkeypatch.setattr(
        "app.services.source_tasks.uuid4",
        lambda: "course-task-from-clone",
    )
    monkeypatch.setattr(
        content_ingestion,
        "dispatch_course_generation",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("broker unavailable")),
    )

    class FakeTask:
        def update_state(self, state, meta=None):
            return None

    with pytest.raises(RuntimeError, match="Failed to dispatch course generation"):
        await content_ingestion._clone_source_async(
            FakeTask(),
            str(target.id),
            str(donor.id),
        )

    target_row = await db_session.get(Source, target.id)
    tasks = (
        await db_session.execute(
            select(SourceTask).where(SourceTask.source_id == target.id)
        )
    ).scalars().all()
    task_by_type = {task.task_type: task for task in tasks}

    assert target_row.status == "ready"
    assert target_row.celery_task_id == "clone-processing-1"
    assert task_by_type["course_generation"].status == "failure"
    assert task_by_type["course_generation"].stage == "error"
    assert task_by_type["course_generation"].error_summary == "broker unavailable"


@pytest.mark.asyncio
async def test_ref_subscriber_ready_waiter_dispatches_only_clone_task(
    monkeypatch, db_session, demo_user
):
    donor = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=donor",
        title="Donor source",
        status="ready",
        metadata_={},
        created_by=demo_user.id,
    )
    db_session.add(donor)
    await db_session.flush()

    waiter = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=waiter",
        title="Waiting source",
        status="waiting_donor",
        metadata_={"pending_goal": "overview"},
        ref_source_id=donor.id,
        created_by=demo_user.id,
    )
    db_session.add(waiter)
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

    monkeypatch.setattr(
        ref_subscriber,
        "get_settings",
        lambda: SimpleNamespace(database_url="postgresql+asyncpg://test/test"),
    )
    monkeypatch.setattr(ref_subscriber, "create_async_engine", lambda *args, **kwargs: FakeEngine())
    monkeypatch.setattr(
        ref_subscriber,
        "async_sessionmaker",
        lambda *args, **kwargs: FakeSessionFactory(db_session),
    )

    clone_calls: list[tuple[str, str]] = []

    class FakeCloneTask:
        def delay(self, source_id, ref_source_id):
            clone_calls.append((source_id, ref_source_id))
            return SimpleNamespace(id="clone-task-1")

    monkeypatch.setattr(
        "app.worker.tasks.content_ingestion.clone_source",
        FakeCloneTask(),
    )

    await ref_subscriber._handle_source_done(str(donor.id), "ready")

    waiter_row = await db_session.get(Source, waiter.id)
    task_row = (
        await db_session.execute(
            select(SourceTask).where(
                SourceTask.source_id == waiter.id,
                SourceTask.task_type == "source_processing",
            )
        )
    ).scalar_one_or_none()

    assert clone_calls == [(str(waiter.id), str(donor.id))]
    assert waiter_row.celery_task_id == "clone-task-1"
    assert waiter_row.status == "pending"
    assert task_row is not None
    assert task_row.status == "pending"
    assert task_row.stage == "pending"
    assert task_row.celery_task_id == "clone-task-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_status", "expected_task_status", "expected_stage", "error_message"),
    [
        ("pending", "pending", "pending", None),
        ("extracting", "running", "extracting", None),
        ("ready", "success", "ready", None),
        ("error", "failure", "error", "boom"),
    ],
)
async def test_update_status_syncs_source_task_lifecycle(
    db_session,
    demo_user,
    source_status,
    expected_task_status,
    expected_stage,
    error_message,
):
    source = Source(
        type="youtube",
        url="https://www.youtube.com/watch?v=test",
        title="Lifecycle source",
        status="pending",
        metadata_={},
        created_by=demo_user.id,
    )
    db_session.add(source)
    await db_session.flush()

    task = SourceTask(
        source_id=source.id,
        task_type="source_processing",
        status="pending",
        celery_task_id="fake-task-123",
    )
    db_session.add(task)
    await db_session.flush()

    await content_ingestion._update_status(
        db_session,
        source.id,
        source_status,
        error_message=error_message,
    )

    task_row = (
        await db_session.execute(
            select(SourceTask).where(SourceTask.source_id == source.id)
        )
    ).scalar_one()
    source_row = await db_session.get(Source, source.id)

    assert source_row.status == source_status
    assert task_row.status == expected_task_status
    assert task_row.stage == expected_stage
    if error_message:
        assert task_row.error_summary == error_message
        assert source_row.metadata_["error"] == error_message
