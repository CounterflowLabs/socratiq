"""Tests for memory manager and agent tools."""

import json

import pytest
from uuid import uuid4

from app.agent.tools.memory import EpisodicMemoryTool, MetacognitiveReflectTool
from app.db.models.user import User
from app.memory.manager import MemoryManager


class TestEpisodicMemoryTool:
    """Tests for the EpisodicMemoryTool agent tool."""

    @pytest.mark.asyncio
    async def test_record_and_recall(self, db_session):
        user = User(email=f"mem-{uuid4().hex[:6]}@test.com", name="Memory Test")
        db_session.add(user)
        await db_session.flush()

        tool = EpisodicMemoryTool(db=db_session, user_id=user.id)

        # Record an event
        result = await tool.execute(
            action="record",
            content="Student struggled with recursion",
            event_type="stuck",
            importance=0.7,
        )
        data = json.loads(result)
        assert data["status"] == "recorded"
        assert "id" in data

        # Recall events
        result = await tool.execute(action="recall", content="recursion", limit=5)
        data = json.loads(result)
        assert len(data["memories"]) >= 1
        assert "recursion" in data["memories"][0]["content"]

    @pytest.mark.asyncio
    async def test_low_importance_skipped(self, db_session):
        user = User(email=f"skip-{uuid4().hex[:6]}@test.com", name="Skip Test")
        db_session.add(user)
        await db_session.flush()

        tool = EpisodicMemoryTool(db=db_session, user_id=user.id)
        result = await tool.execute(
            action="record", content="trivial", importance=0.1
        )
        data = json.loads(result)
        assert data["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_medium_importance_gets_expiry(self, db_session):
        user = User(email=f"exp-{uuid4().hex[:6]}@test.com", name="Expiry Test")
        db_session.add(user)
        await db_session.flush()

        tool = EpisodicMemoryTool(db=db_session, user_id=user.id)
        result = await tool.execute(
            action="record",
            content="minor observation",
            event_type="observation",
            importance=0.25,
        )
        data = json.loads(result)
        assert data["status"] == "recorded"

        # Verify the memory was created with an expiry
        from sqlalchemy import select
        from app.db.models.episodic_memory import EpisodicMemory

        mem_result = await db_session.execute(
            select(EpisodicMemory).where(
                EpisodicMemory.id == data["id"]
            )
        )
        mem = mem_result.scalar_one()
        assert mem.expires_at is not None


class TestMetacognitiveReflectTool:
    """Tests for the MetacognitiveReflectTool agent tool."""

    @pytest.mark.asyncio
    async def test_record_strategy(self, db_session):
        from unittest.mock import MagicMock

        user = User(email=f"meta-{uuid4().hex[:6]}@test.com", name="Meta Test")
        db_session.add(user)
        await db_session.flush()

        mock_provider = MagicMock()
        tool = MetacognitiveReflectTool(
            db=db_session, provider=mock_provider, user_id=user.id
        )
        result = await tool.execute(
            strategy="code_first",
            effectiveness=0.8,
            evidence="Student grasped the concept quickly when shown code examples",
        )
        data = json.loads(result)
        assert data["status"] == "recorded"
        assert data["strategy"] == "code_first"
        assert data["effectiveness"] == 0.8


class TestMemoryManager:
    """Tests for the 5-layer MemoryManager."""

    @pytest.mark.asyncio
    async def test_retrieve_empty(self, db_session):
        user = User(email=f"mgr-{uuid4().hex[:6]}@test.com", name="Manager Test")
        db_session.add(user)
        await db_session.flush()

        mgr = MemoryManager(db=db_session)
        ctx = await mgr.retrieve(user_id=user.id, query="test")

        assert ctx.working == []
        assert ctx.episodic == []
        assert ctx.progress == []
        assert ctx.metacognitive == []
        assert ctx.content == []

    @pytest.mark.asyncio
    async def test_retrieve_with_episodic(self, db_session):
        from app.db.models.episodic_memory import EpisodicMemory

        user = User(email=f"mgr2-{uuid4().hex[:6]}@test.com", name="Manager Test 2")
        db_session.add(user)
        await db_session.flush()

        # Insert an episodic memory
        db_session.add(
            EpisodicMemory(
                user_id=user.id,
                event_type="breakthrough",
                content="Understood closures after analogy",
                context={},
                importance=0.9,
            )
        )
        await db_session.flush()

        mgr = MemoryManager(db=db_session)
        ctx = await mgr.retrieve(user_id=user.id, query="closures")

        assert len(ctx.episodic) == 1
        assert ctx.episodic[0]["event_type"] == "breakthrough"

    @pytest.mark.asyncio
    async def test_retrieve_effective_strategies(self, db_session):
        from app.db.models.metacognitive_record import MetacognitiveRecord

        user = User(email=f"mgr3-{uuid4().hex[:6]}@test.com", name="Manager Test 3")
        db_session.add(user)
        await db_session.flush()

        # Insert strategies with varying effectiveness
        db_session.add(
            MetacognitiveRecord(
                user_id=user.id,
                strategy="analogy",
                effectiveness=0.9,
                context={},
                evidence="Student understood quickly",
            )
        )
        db_session.add(
            MetacognitiveRecord(
                user_id=user.id,
                strategy="direct",
                effectiveness=0.3,
                context={},
                evidence="Student seemed confused",
            )
        )
        await db_session.flush()

        mgr = MemoryManager(db=db_session)
        ctx = await mgr.retrieve(user_id=user.id, query="test")

        # Only strategies with effectiveness >= 0.6 should appear
        assert len(ctx.metacognitive) == 1
        assert ctx.metacognitive[0]["strategy"] == "analogy"
