"""Ingestion time estimation: formula-based (B) with historical calibration (C)."""

import math
import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.llm_usage_log import LlmUsageLog

logger = logging.getLogger(__name__)

# Default LLM latency per call (seconds) — used before history is available
DEFAULT_LLM_LATENCY_S = 20
# Embedding API latency per batch (seconds)
DEFAULT_EMBED_LATENCY_S = 5
# DB store overhead (seconds)
DEFAULT_STORE_OVERHEAD_S = 5
# Content analyzer batch char limit (mirrors content_analyzer.py)
ANALYZER_BATCH_CHARS = 6000
# Embedding batch size (mirrors embedding.py)
EMBED_BATCH_SIZE = 50

# Ordered stages for partial estimation
STAGES = ["analyzing", "storing", "embedding"]


class TimeEstimator:
    """Estimates remaining ingestion time based on content metrics and optional history."""

    def __init__(self, db: AsyncSession | None = None):
        self._db = db
        self._llm_latency_s: float = DEFAULT_LLM_LATENCY_S

    async def load_calibration(self) -> None:
        """Load average LLM call duration from history. Call once per task."""
        if not self._db:
            return

        result = await self._db.execute(
            select(func.avg(LlmUsageLog.duration_ms)).where(
                LlmUsageLog.duration_ms.is_not(None),
                LlmUsageLog.task_type.in_(["content_analysis"]),
            )
        )
        avg_ms = await result.scalar()

        if avg_ms is not None:
            self._llm_latency_s = avg_ms / 1000.0
            logger.info(f"Calibrated LLM latency: {self._llm_latency_s:.1f}s")

    def estimate_remaining(
        self,
        chunk_count: int,
        total_chars: int,
        current_stage: str | None = None,
    ) -> int:
        """Estimate remaining seconds from current_stage onward."""
        llm = self._llm_latency_s

        stage_estimates = {
            "analyzing": math.ceil(total_chars / ANALYZER_BATCH_CHARS) * llm if total_chars >= 8000 else llm,
            "storing": DEFAULT_STORE_OVERHEAD_S,
            "embedding": math.ceil(chunk_count / EMBED_BATCH_SIZE) * DEFAULT_EMBED_LATENCY_S,
        }

        if current_stage and current_stage in STAGES:
            start_idx = STAGES.index(current_stage)
            active_stages = STAGES[start_idx:]
        else:
            active_stages = STAGES

        total = sum(stage_estimates[s] for s in active_stages)
        return round(total)
