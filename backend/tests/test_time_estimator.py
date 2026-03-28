"""Tests for ingestion time estimation."""

import pytest
from unittest.mock import AsyncMock

from app.services.time_estimator import TimeEstimator


class TestTimeEstimator:
    @pytest.mark.asyncio
    async def test_estimate_with_no_history_uses_defaults(self):
        mock_db = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalar.return_value = None
        mock_db.execute.return_value = mock_result

        estimator = TimeEstimator(mock_db)
        result = estimator.estimate_remaining(chunk_count=10, total_chars=50000)
        # ceil(50000/6000)*20 + 5 + ceil(10/50)*5 = 9*20 + 5 + 5 = 190
        assert result == 190

    @pytest.mark.asyncio
    async def test_estimate_with_history_uses_calibrated_latency(self):
        from unittest.mock import MagicMock
        mock_db = AsyncMock()
        mock_result = MagicMock()  # sync mock — scalar() is not async
        mock_result.scalar.return_value = 12000
        mock_db.execute.return_value = mock_result

        estimator = TimeEstimator(mock_db)
        await estimator.load_calibration()
        result = estimator.estimate_remaining(chunk_count=10, total_chars=50000)
        # ceil(50000/6000)*12 + 5 + ceil(10/50)*5 = 9*12 + 5 + 5 = 118
        assert result == 118

    def test_estimate_remaining_stages_from_current(self):
        estimator = TimeEstimator(db=None)
        result = estimator.estimate_remaining(chunk_count=10, total_chars=50000, current_stage="storing")
        # storing(5) + embed(ceil(10/50)*5) = 5 + 5 = 10
        assert result == 10

    def test_estimate_small_content(self):
        estimator = TimeEstimator(db=None)
        result = estimator.estimate_remaining(chunk_count=5, total_chars=3000)
        # <8000 chars: 1*20 + 5 + ceil(5/50)*5 = 20 + 5 + 5 = 30
        assert result == 30
