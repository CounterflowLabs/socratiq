"""Regression tests for content ingestion worker isolation."""

import uuid
from types import SimpleNamespace

import pytest

from app.worker.tasks import content_ingestion
from app.db.models.source import Source


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
async def test_ingest_source_returns_course_id_when_pipeline_finishes(
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

    class FakeCourseGenerator:
        def __init__(self, *_args, **_kwargs):
            pass

        async def generate(self, **_kwargs):
            return SimpleNamespace(id=uuid.uuid4())

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
        "app.services.course_generator.CourseGenerator",
        FakeCourseGenerator,
    )

    task_updates: list[tuple[str, dict]] = []

    class FakeTask:
        def update_state(self, state, meta=None):
            task_updates.append((state, meta or {}))

    result = await content_ingestion._ingest_source_async(FakeTask(), str(source.id))

    assert result["status"] == "ready"
    assert "course_id" in result
    assert any(meta.get("stage") == "assembling_course" for _, meta in task_updates)
