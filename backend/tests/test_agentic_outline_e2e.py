"""DB-backed e2e for the agentic outline wiring (`_maybe_run_agentic_outline`).

Simulates the pathological fragmentation case — a long video whose chunks each
landed in their own section_bucket (the "113 sections" shape) — and verifies
the critic-gated video→course graph consolidates them into a few contiguous
buckets, projected back onto chunk metadata for CourseGenerator to consume.

The PLANNING route is served by a fake provider (no network); the full
RouterLLMClient → AgentRuntime → graph → validator → metadata-rewrite path runs
for real against the test database.
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.db.models.content_chunk import ContentChunk
from app.db.models.source import Source
from app.services.llm.base import ContentBlock, LLMResponse, TokenUsage
from app.services.section_planner import SECTION_BUCKET_KEY, SECTION_BUCKET_TOPIC_KEY
from app.worker.tasks.course_generation import _maybe_run_agentic_outline

N_CHUNKS = 12


def _mock_llm_response(payload: dict) -> LLMResponse:
    return LLMResponse(
        content=[ContentBlock(type="text", text=json.dumps(payload))],
        model="mock",
        usage=TokenUsage(input_tokens=100, output_tokens=50),
    )


def _fake_resources(outline: dict):
    """A resources stub whose model_router serves any task with one provider
    that returns ``outline`` from chat() — exercises the real runtime/graph."""
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=_mock_llm_response(outline))
    router = AsyncMock()
    router.get_provider = AsyncMock(return_value=provider)
    return SimpleNamespace(model_router=router), provider


async def _seed_fragmented_source(db) -> Source:
    """A 'ready' video source whose 12 chunks each sit in their own bucket."""
    source = Source(
        id=uuid.uuid4(), type="youtube", title="Long Video", status="ready",
        metadata_={},
    )
    db.add(source)
    await db.flush()
    for i in range(N_CHUNKS):
        db.add(
            ContentChunk(
                id=uuid.uuid4(),
                source_id=source.id,
                text=f"transcript segment {i} " * 20,
                metadata_={
                    "topic": f"Topic {i}",
                    "summary": f"Summary of segment {i}",
                    "start_time": float(i * 60),
                    "end_time": float((i + 1) * 60),
                    "difficulty": 1,
                    # Pathological warm start: one bucket per chunk.
                    SECTION_BUCKET_KEY: i,
                    SECTION_BUCKET_TOPIC_KEY: None,
                },
            )
        )
    await db.flush()
    return source


@pytest.mark.asyncio
async def test_agentic_outline_collapses_fragmented_buckets(db_session):
    source = await _seed_fragmented_source(db_session)

    # The planner consolidates 12 per-chunk buckets into 3 contiguous sections
    # with a ramping difficulty.
    outline = {
        "sections": [
            {"title": "Setup", "difficulty": 1, "knowledge_points": ["intro"],
             "source_chunk_indices": [0, 1, 2, 3]},
            {"title": "Mechanics", "difficulty": 3, "knowledge_points": ["core"],
             "source_chunk_indices": [4, 5, 6, 7]},
            {"title": "Putting it together", "difficulty": 4,
             "knowledge_points": ["synthesis"],
             "source_chunk_indices": [8, 9, 10, 11]},
        ]
    }
    resources, provider = _fake_resources(outline)

    n = await _maybe_run_agentic_outline(
        db_session, source, source.id, resources, event_bus=None
    )

    assert n == 3
    assert provider.chat.await_count == 1  # planned once, critic passed

    rows = (
        await db_session.execute(
            select(ContentChunk).where(ContentChunk.source_id == source.id)
        )
    ).scalars().all()
    by_start = sorted(rows, key=lambda c: c.metadata_["start_time"])

    buckets = [c.metadata_[SECTION_BUCKET_KEY] for c in by_start]
    # 12 fragments collapsed into 3 contiguous buckets.
    assert buckets == [0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2]
    titles = [c.metadata_[SECTION_BUCKET_TOPIC_KEY] for c in by_start]
    assert titles[0] == "Setup" and titles[4] == "Mechanics" and titles[8] == "Putting it together"
    # Per-section difficulty was written through to every chunk in the section.
    assert [c.metadata_["difficulty"] for c in by_start] == [1, 1, 1, 1, 3, 3, 3, 3, 4, 4, 4, 4]


@pytest.mark.asyncio
async def test_agentic_outline_skips_page_structured_source(db_session):
    # A page-based source (PDF/markdown) must keep its page structure — the
    # agentic outline no-ops so CourseGenerator's page mode is untouched.
    source = Source(
        id=uuid.uuid4(), type="pdf", title="A Paper", status="ready", metadata_={}
    )
    db_session.add(source)
    await db_session.flush()
    for i in range(4):
        db_session.add(
            ContentChunk(
                id=uuid.uuid4(), source_id=source.id, text=f"page {i}",
                metadata_={"topic": f"P{i}", "summary": "", "page_index": i},
            )
        )
    await db_session.flush()

    resources, provider = _fake_resources({"sections": []})
    n = await _maybe_run_agentic_outline(
        db_session, source, source.id, resources, event_bus=None
    )
    assert n is None
    provider.chat.assert_not_awaited()
