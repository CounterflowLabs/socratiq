"""Tests for LLM cost guard."""
import pytest
from uuid import uuid4
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
