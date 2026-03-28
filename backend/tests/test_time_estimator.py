"""Tests for ingestion time estimation."""

import pytest
from unittest.mock import AsyncMock

from app.services.time_estimator import TimeEstimator


class TestTimeEstimator:
    @pytest.mark.asyncio
    async def test_estimate_with_no_history_uses_defaults(self):
        """Cold start: uses default LLM latency."""
        mock_db = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalar.return_value = None
        mock_db.execute.return_value = mock_result

        estimator = TimeEstimator(mock_db)
        result = estimator.estimate_remaining(
            chunk_count=10,
            total_chars=50000,
            page_count=5,
            code_page_count=2,
        )

        # Formula: ceil(50000/6000)*20 + 5*20 + 2*20 + ceil(10/50)*5 + 5
        # = 9*20 + 100 + 40 + 1*5 + 5 = 180 + 100 + 40 + 5 + 5 = 330
        assert result == 330

    @pytest.mark.asyncio
    async def test_estimate_with_history_uses_calibrated_latency(self):
        """After accumulating history, uses average measured latency."""
        mock_db = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalar.return_value = 12000
        mock_db.execute.return_value = mock_result

        estimator = TimeEstimator(mock_db)
        await estimator.load_calibration()
        result = estimator.estimate_remaining(
            chunk_count=10,
            total_chars=50000,
            page_count=5,
            code_page_count=2,
        )

        # ceil(50000/6000)*12 + 5*12 + 2*12 + ceil(10/50)*5 + 5
        # = 9*12 + 60 + 24 + 5 + 5 = 108 + 60 + 24 + 5 + 5 = 202
        assert result == 202

    def test_estimate_remaining_stages_from_current(self):
        """Only estimates remaining stages, not already completed ones."""
        estimator = TimeEstimator(db=None)
        result = estimator.estimate_remaining(
            chunk_count=10,
            total_chars=50000,
            page_count=5,
            code_page_count=2,
            current_stage="generating_lessons",
        )

        # Skips analyze, only: lessons(5*20) + labs(2*20) + embed(ceil(10/50)*5) + store(5)
        # = 100 + 40 + 5 + 5 = 150
        assert result == 150

    def test_estimate_with_zero_code_pages(self):
        """No code pages means no lab generation time."""
        estimator = TimeEstimator(db=None)
        result = estimator.estimate_remaining(
            chunk_count=5,
            total_chars=3000,
            page_count=2,
            code_page_count=0,
        )

        # <8000 chars -> 1 analyze call: 1*20 + 2*20 + 0 + ceil(5/50)*5 + 5
        # = 20 + 40 + 0 + 5 + 5 = 70
        assert result == 70
