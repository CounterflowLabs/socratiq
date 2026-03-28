"""Tests for LLM cost guard."""
import uuid
import pytest
from uuid import uuid4
from unittest.mock import AsyncMock

from app.services.cost_guard import CostGuard
from app.db.models.user import User


class TestCostGuard:
    @pytest.mark.asyncio
    async def test_log_usage(self, db_session):
        # Create a user first
        user = User(email=f"cost-{uuid4().hex[:6]}@test.com", name="Cost Test")
        db_session.add(user)
        await db_session.flush()

        guard = CostGuard(db_session)
        await guard.log_usage(
            user_id=user.id, task_type="diagnostic",
            model_name="claude-sonnet", tokens_in=500, tokens_out=200,
        )
        # Should not raise

    @pytest.mark.asyncio
    async def test_check_budget_within_limit(self, db_session):
        user = User(email=f"budget-{uuid4().hex[:6]}@test.com", name="Budget Test")
        db_session.add(user)
        await db_session.flush()

        guard = CostGuard(db_session)
        allowed = await guard.check_budget(user.id, "diagnostic")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_check_budget_exceeded(self, db_session):
        user = User(email=f"over-{uuid4().hex[:6]}@test.com", name="Over Budget")
        db_session.add(user)
        await db_session.flush()

        guard = CostGuard(db_session)
        # Log enough to exceed the 50,000 token daily limit
        for _ in range(6):
            await guard.log_usage(user.id, "diagnostic", "model", 5000, 5000)

        allowed = await guard.check_budget(user.id, "diagnostic")
        assert allowed is False


class TestCostGuardLogUsage:
    @pytest.mark.asyncio
    async def test_log_usage_stores_duration_ms(self):
        mock_db = AsyncMock()
        guard = CostGuard(mock_db)

        await guard.log_usage(
            user_id=uuid.uuid4(),
            task_type="content_analysis",
            model_name="claude-sonnet",
            tokens_in=100,
            tokens_out=200,
            duration_ms=1500,
        )

        mock_db.add.assert_called_once()
        log_obj = mock_db.add.call_args[0][0]
        assert log_obj.duration_ms == 1500

    @pytest.mark.asyncio
    async def test_log_usage_duration_ms_defaults_to_none(self):
        mock_db = AsyncMock()
        guard = CostGuard(mock_db)

        await guard.log_usage(
            user_id=uuid.uuid4(),
            task_type="content_analysis",
            model_name="claude-sonnet",
            tokens_in=100,
            tokens_out=200,
        )

        log_obj = mock_db.add.call_args[0][0]
        assert log_obj.duration_ms is None
