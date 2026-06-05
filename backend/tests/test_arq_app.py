"""ARQ worker registration tests (replaces the old Celery registration test)."""

import json

import pytest

from app.worker.arq_app import WorkerSettings


def test_expected_tasks_are_registered() -> None:
    names = {f.name for f in WorkerSettings.functions}
    assert {
        "ingest_source",
        "clone_source",
        "generate_course",
        "generate_multi",
        "regenerate_course",
        "generate_section_exercises",
        "regenerate_section_lesson",
        "prune_expired_memories",
    } <= names


def test_abort_jobs_enabled() -> None:
    # Required so the cancel/revoke endpoints can abort in-flight jobs.
    assert WorkerSettings.allow_abort_jobs is True


async def test_generate_course_emits_agui_run_lifecycle(monkeypatch):
    """The course-gen task wraps generation in an AG-UI run, publishing
    RUN_STARTED → STATE_SNAPSHOT(progress) → RUN_FINISHED to the run's Redis
    stream so the web process can re-stream it over SSE."""
    fakeredis = pytest.importorskip("fakeredis")
    from app.agentcore.events import state_snapshot
    from app.worker.tasks import course_generation

    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        course_generation.aioredis,
        "from_url",
        lambda *a, **k: fakeredis.aioredis.FakeRedis(server=server),
    )

    async def fake_impl(task, source_id, user_id, resources, event_bus=None):
        if event_bus is not None:
            await event_bus.emit(state_snapshot({"total": 1, "completed": 1}))
        return {"status": "ready", "course_id": "c1"}

    monkeypatch.setattr(course_generation, "_generate_course_async", fake_impl)

    ctx = {"job_id": "run-x", "resources": object()}
    result = await course_generation.generate_course(ctx, {"source_id": "s1"})
    assert result["status"] == "ready"

    reader = fakeredis.aioredis.FakeRedis(server=server)
    entries = await reader.xrange("agui:run:run-x")
    types = []
    for _id, fields in entries:
        body = fields.get(b"e") or fields.get("e")
        if body:
            types.append(json.loads(body)["type"])
    assert types[0] == "RUN_STARTED"
    assert "STATE_SNAPSHOT" in types
    assert types[-1] == "RUN_FINISHED"
    await reader.aclose()


async def test_course_critic_emits_verdict():
    from types import SimpleNamespace

    from app.worker.tasks.course_generation import (
        _run_course_critic,
        _section_to_critic_dict,
    )

    # One healthy section, one missing knowledge points → critic should fail.
    healthy = SimpleNamespace(
        title="Intro",
        difficulty=1,
        content={"lesson": {"blocks": [
            {"type": "concept_relation", "concepts": [{"label": "kp1"}]},
            {"type": "practice_trigger"},
        ]}},
    )
    thin = SimpleNamespace(title="Empty", difficulty=2, content={"lesson": {"blocks": []}})
    assert _section_to_critic_dict(healthy)["knowledge_points"] == ["kp1"]
    assert _section_to_critic_dict(healthy)["has_practice"] is True

    captured = []

    class Sink:
        async def emit(self, ev):
            captured.append(ev)

    from app.agentcore.events import EventBus

    bus = EventBus.new(sinks=[Sink()])
    await _run_course_critic([healthy, thin], bus, resources=None)
    verdict_events = [e for e in captured if e.type.value == "CUSTOM"]
    assert verdict_events and verdict_events[0].name == "critic_verdict"
    assert verdict_events[0].value["passed"] is False  # thin section flagged
