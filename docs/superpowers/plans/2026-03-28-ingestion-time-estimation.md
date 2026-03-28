# Ingestion Time Estimation (B+C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Predict and display remaining processing time during content ingestion, using formula-based estimation (B) calibrated by historical LLM call durations (C).

**Architecture:** After the Extract stage completes, compute estimated remaining seconds based on chunk count, page count, and average LLM latency. LLM latency defaults to static values (20s cloud / 8s local) but is progressively replaced by actual measured durations stored in `llm_usage_logs`. The estimate is passed via Celery `task.update_state(meta=...)` and displayed in the frontend Dashboard.

**Tech Stack:** Python (FastAPI, Celery, SQLAlchemy), Alembic migration, TypeScript (Next.js), existing `llm_usage_logs` table + new `duration_ms` column.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/app/db/models/llm_usage_log.py` | Modify | Add `duration_ms` column |
| `backend/alembic/versions/XXXX_add_duration_ms_to_llm_usage_logs.py` | Create | Migration for new column |
| `backend/app/services/cost_guard.py` | Modify | Accept + store `duration_ms` in `log_usage()` |
| `backend/app/services/time_estimator.py` | Create | Estimation logic: formula + historical calibration |
| `backend/app/worker/tasks/content_ingestion.py` | Modify | Instrument LLM calls with timing, emit estimates |
| `backend/app/api/routes/tasks.py` | Modify | Pass `estimated_remaining_seconds` in response |
| `frontend/src/lib/api.ts` | Modify | Add estimate fields to task status type |
| `frontend/src/app/page.tsx` | Modify | Display "预计剩余 X 分钟" with progress bar |
| `backend/tests/test_time_estimator.py` | Create | Unit tests for estimation logic |

---

### Task 1: Add `duration_ms` Column to `llm_usage_logs`

**Files:**
- Modify: `backend/app/db/models/llm_usage_log.py`
- Create: `backend/alembic/versions/XXXX_add_duration_ms_to_llm_usage_logs.py`

- [ ] **Step 1: Add column to ORM model**

In `backend/app/db/models/llm_usage_log.py`, add after line 23 (`estimated_cost_usd`):

```python
duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 2: Generate Alembic migration**

Run:
```bash
cd /home/tulip/project/socratiq/backend
alembic revision --autogenerate -m "add duration_ms to llm_usage_logs"
```

Expected: New migration file created in `backend/alembic/versions/`.

- [ ] **Step 3: Apply migration**

Run:
```bash
cd /home/tulip/project/socratiq/backend
alembic upgrade head
```

Expected: Migration applies successfully.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models/llm_usage_log.py backend/alembic/versions/*add_duration_ms*
git commit -m "feat: add duration_ms column to llm_usage_logs for latency tracking"
```

---

### Task 2: Update `CostGuard.log_usage()` to Accept Duration

**Files:**
- Modify: `backend/app/services/cost_guard.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_cost_guard.py`:

```python
"""Tests for CostGuard usage logging with duration."""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.cost_guard import CostGuard


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tulip/project/socratiq/backend && python -m pytest tests/test_cost_guard.py -v`

Expected: FAIL — `log_usage()` doesn't accept `duration_ms` parameter.

- [ ] **Step 3: Update `log_usage` signature**

In `backend/app/services/cost_guard.py`, change `log_usage`:

```python
async def log_usage(
    self, user_id: UUID, task_type: str,
    model_name: str, tokens_in: int, tokens_out: int,
    duration_ms: int | None = None,
) -> None:
    cost = (tokens_in * 0.000003) + (tokens_out * 0.000015)
    log = LlmUsageLog(
        user_id=user_id, task_type=task_type,
        model_name=model_name, tokens_in=tokens_in,
        tokens_out=tokens_out, estimated_cost_usd=cost,
        duration_ms=duration_ms,
    )
    self._db.add(log)
    await self._db.flush()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tulip/project/socratiq/backend && python -m pytest tests/test_cost_guard.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/cost_guard.py backend/tests/test_cost_guard.py
git commit -m "feat: add duration_ms parameter to CostGuard.log_usage()"
```

---

### Task 3: Create `TimeEstimator` Service

**Files:**
- Create: `backend/app/services/time_estimator.py`
- Create: `backend/tests/test_time_estimator.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_time_estimator.py`:

```python
"""Tests for ingestion time estimation."""

import pytest
from unittest.mock import AsyncMock

from app.services.time_estimator import TimeEstimator


class TestTimeEstimator:
    @pytest.mark.asyncio
    async def test_estimate_with_no_history_uses_defaults(self):
        """Cold start: uses default LLM latency."""
        mock_db = AsyncMock()
        # No rows returned from history query
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
        # avg duration_ms = 12000 → 12s per call
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

        # <8000 chars → 1 analyze call: 1*20 + 2*20 + 0 + ceil(5/50)*5 + 5
        # = 20 + 40 + 0 + 5 + 5 = 70
        assert result == 70
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tulip/project/socratiq/backend && python -m pytest tests/test_time_estimator.py -v`

Expected: FAIL — module `app.services.time_estimator` not found.

- [ ] **Step 3: Implement `TimeEstimator`**

Create `backend/app/services/time_estimator.py`:

```python
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
# Minimum history samples before trusting calibration
MIN_CALIBRATION_SAMPLES = 5
# Content analyzer batch char limit (mirrors content_analyzer.py)
ANALYZER_BATCH_CHARS = 6000
# Embedding batch size (mirrors embedding.py)
EMBED_BATCH_SIZE = 50

# Ordered stages for partial estimation
STAGES = ["analyzing", "generating_lessons", "generating_labs", "storing", "embedding"]


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
                LlmUsageLog.task_type.in_(["content_analysis", "lesson_gen", "lab_gen"]),
            )
        )
        avg_ms = result.scalar()

        if avg_ms is not None:
            # Check sample count
            count_result = await self._db.execute(
                select(func.count()).where(
                    LlmUsageLog.duration_ms.is_not(None),
                    LlmUsageLog.task_type.in_(["content_analysis", "lesson_gen", "lab_gen"]),
                )
            )
            count = count_result.scalar() or 0

            if count >= MIN_CALIBRATION_SAMPLES:
                self._llm_latency_s = avg_ms / 1000.0
                logger.info(f"Calibrated LLM latency: {self._llm_latency_s:.1f}s (from {count} samples)")

    def estimate_remaining(
        self,
        chunk_count: int,
        total_chars: int,
        page_count: int,
        code_page_count: int,
        current_stage: str | None = None,
    ) -> int:
        """Estimate remaining seconds from current_stage onward.

        Args:
            chunk_count: Number of content chunks after extraction.
            total_chars: Total character count of extracted content.
            page_count: Number of page groups (determines lesson LLM calls).
            code_page_count: Pages with code snippets (determines lab LLM calls).
            current_stage: If set, only estimate from this stage forward.

        Returns:
            Estimated remaining seconds (rounded to int).
        """
        llm = self._llm_latency_s

        stage_estimates = {
            "analyzing": math.ceil(total_chars / ANALYZER_BATCH_CHARS) * llm if total_chars >= 8000 else llm,
            "generating_lessons": page_count * llm,
            "generating_labs": code_page_count * llm,
            "storing": DEFAULT_STORE_OVERHEAD_S,
            "embedding": math.ceil((chunk_count + page_count) / EMBED_BATCH_SIZE) * DEFAULT_EMBED_LATENCY_S,
        }

        # Determine which stages to include
        if current_stage and current_stage in STAGES:
            start_idx = STAGES.index(current_stage)
            active_stages = STAGES[start_idx:]
        else:
            active_stages = STAGES

        total = sum(stage_estimates[s] for s in active_stages)
        return round(total)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tulip/project/socratiq/backend && python -m pytest tests/test_time_estimator.py -v`

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/time_estimator.py backend/tests/test_time_estimator.py
git commit -m "feat: add TimeEstimator service with formula + historical calibration"
```

---

### Task 4: Instrument Ingestion Pipeline with Timing + Estimates

**Files:**
- Modify: `backend/app/worker/tasks/content_ingestion.py`

- [ ] **Step 1: Add timing instrumentation and estimate emission**

In `backend/app/worker/tasks/content_ingestion.py`, add `import time` at the top (after `import logging`):

```python
import time
```

After the Extract stage (after `logger.info(f"Extracted {len(result.chunks)} chunks from source {source_id}")`, around line 73), add the estimation setup:

```python
                # --- Compute time estimate after extraction ---
                from app.services.time_estimator import TimeEstimator
                total_chars = sum(len(c.raw_text) for c in result.chunks)
                estimator = TimeEstimator(db)
                await estimator.load_calibration()
                # code_page_count unknown until after lessons; estimate 30% of pages have code
                est_code_pages = max(1, len(result.chunks) // 3)
                page_set = set()
                for c in result.chunks:
                    page_set.add(c.metadata.get("page_index", 0))
                est_page_count = len(page_set)
                estimated_total = estimator.estimate_remaining(
                    chunk_count=len(result.chunks),
                    total_chars=total_chars,
                    page_count=est_page_count,
                    code_page_count=est_code_pages,
                )
```

Then update **every** `task.update_state` call in steps 2-6 to include the estimate. For each stage, compute the remaining estimate from that stage onward. Replace each `task.update_state(state="PROGRESS", meta={"stage": "..."})` with:

```python
                # STEP 2: ANALYZE
                remaining = estimator.estimate_remaining(
                    chunk_count=len(result.chunks), total_chars=total_chars,
                    page_count=est_page_count, code_page_count=est_code_pages,
                    current_stage="analyzing",
                )
                task.update_state(state="PROGRESS", meta={"stage": "analyzing", "estimated_remaining_seconds": remaining})
```

```python
                # STEP 3: GENERATE LESSONS
                remaining = estimator.estimate_remaining(
                    chunk_count=len(result.chunks), total_chars=total_chars,
                    page_count=len(page_groups), code_page_count=est_code_pages,
                    current_stage="generating_lessons",
                )
                task.update_state(state="PROGRESS", meta={"stage": "generating_lessons", "estimated_remaining_seconds": remaining})
```

```python
                # STEP 4: GENERATE LABS — now we know actual code_page_count
                actual_code_pages = 0  # will be counted in the loop below
```

After the labs loop completes (after line ~149), before STEP 5:

```python
                actual_code_pages = sum(1 for v in labs_by_page.values() if v is not None)
```

```python
                # STEP 5: STORE
                remaining = estimator.estimate_remaining(
                    chunk_count=len(analysis.chunks), total_chars=total_chars,
                    page_count=len(page_groups), code_page_count=0,
                    current_stage="storing",
                )
                task.update_state(state="PROGRESS", meta={"stage": "storing", "estimated_remaining_seconds": remaining})
```

```python
                # STEP 6: EMBED
                remaining = estimator.estimate_remaining(
                    chunk_count=len(analysis.chunks), total_chars=total_chars,
                    page_count=len(page_groups), code_page_count=0,
                    current_stage="embedding",
                )
                task.update_state(state="PROGRESS", meta={"stage": "embedding", "estimated_remaining_seconds": remaining})
```

- [ ] **Step 2: Add LLM call duration logging**

Wrap the LLM calls in the pipeline with timing. After the content_analyzer call (around line 80-84), add duration logging:

```python
                analyzer = ContentAnalyzer(model_router)
                t0 = time.monotonic()
                analysis = await analyzer.analyze(
                    title=source.title or "Untitled",
                    chunks=result.chunks,
                    source_type=source.type,
                )
                analyze_ms = int((time.monotonic() - t0) * 1000)

                # Log timing for calibration (C)
                from app.services.cost_guard import CostGuard
                cost_guard = CostGuard(db)
                analyze_calls = max(1, math.ceil(total_chars / 6000)) if total_chars >= 8000 else 1
                per_call_ms = analyze_ms // analyze_calls
                await cost_guard.log_usage(
                    user_id=None, task_type="content_analysis",
                    model_name="unknown", tokens_in=0, tokens_out=0,
                    duration_ms=per_call_ms,
                )
```

Similarly, inside the lesson generation loop (around line 110), wrap each `lesson_gen.generate()`:

```python
                    t0 = time.monotonic()
                    lesson_content = await lesson_gen.generate(chunk_texts, page_title)
                    lesson_ms = int((time.monotonic() - t0) * 1000)
                    await cost_guard.log_usage(
                        user_id=None, task_type="lesson_gen",
                        model_name="unknown", tokens_in=0, tokens_out=0,
                        duration_ms=lesson_ms,
                    )
```

Similarly, inside the lab generation loop (around line 140), wrap each `lab_gen.generate()`:

```python
                    t0 = time.monotonic()
                    lab_result = await lab_gen.generate(
                        code_snippets=all_snippets,
                        lesson_context=lesson_content.summary,
                        language=language,
                    )
                    lab_ms = int((time.monotonic() - t0) * 1000)
                    await cost_guard.log_usage(
                        user_id=None, task_type="lab_gen",
                        model_name="unknown", tokens_in=0, tokens_out=0,
                        duration_ms=lab_ms,
                    )
```

Add `import math` at the top alongside `import time`.

- [ ] **Step 3: Verify no syntax errors**

Run: `cd /home/tulip/project/socratiq/backend && python -c "from app.worker.tasks.content_ingestion import ingest_source; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/worker/tasks/content_ingestion.py
git commit -m "feat: instrument ingestion pipeline with timing + time estimates"
```

---

### Task 5: Expose Estimate in Task Status API

**Files:**
- Modify: `backend/app/api/routes/tasks.py`

- [ ] **Step 1: Update status endpoint to include estimate**

In `backend/app/api/routes/tasks.py`, update the `PROGRESS` branch (around line 54-55):

Replace:
```python
    elif result.state == "PROGRESS" and result.info:
        response["progress"] = result.info
```

With:
```python
    elif result.state == "PROGRESS" and result.info:
        response["progress"] = result.info
        response["stage"] = result.info.get("stage")
        if "estimated_remaining_seconds" in result.info:
            response["estimated_remaining_seconds"] = result.info["estimated_remaining_seconds"]
```

- [ ] **Step 2: Verify no syntax errors**

Run: `cd /home/tulip/project/socratiq/backend && python -c "from app.api.routes.tasks import router; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/routes/tasks.py
git commit -m "feat: expose estimated_remaining_seconds in task status API"
```

---

### Task 6: Update Frontend to Display Time Estimate

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/lib/stores.ts`

- [ ] **Step 1: Update API type**

In `frontend/src/lib/api.ts`, update `getTaskStatus` return type:

Replace:
```typescript
export async function getTaskStatus(taskId: string): Promise<{
  task_id: string;
  state: string;
  result?: unknown;
  error?: string;
  progress?: unknown;
}> {
```

With:
```typescript
export async function getTaskStatus(taskId: string): Promise<{
  task_id: string;
  state: string;
  result?: unknown;
  error?: string;
  progress?: unknown;
  stage?: string;
  estimated_remaining_seconds?: number;
}> {
```

- [ ] **Step 2: Update PendingTask store type**

In `frontend/src/lib/stores.ts`, add to the `PendingTask` interface:

```typescript
export interface PendingTask {
  taskId: string;
  sourceId: string;
  title: string;
  sourceType: string;
  state: string;
  error?: string;
  courseId?: string;
  estimatedRemainingSeconds?: number;  // NEW
}
```

- [ ] **Step 3: Pass estimate through in polling**

In `frontend/src/app/page.tsx`, update the polling `updateTask` call (around line 72):

Replace:
```typescript
          updateTask(task.taskId, { state: status.state, error: status.error });
```

With:
```typescript
          updateTask(task.taskId, {
            state: status.state,
            error: status.error,
            estimatedRemainingSeconds: status.estimated_remaining_seconds,
          });
```

- [ ] **Step 4: Display estimate in task card**

In `frontend/src/app/page.tsx`, add a helper function before `DashboardPage`:

```typescript
function formatRemainingTime(seconds: number | undefined): string | null {
  if (!seconds || seconds <= 0) return null;
  if (seconds < 60) return `预计剩余 ${seconds} 秒`;
  const minutes = Math.ceil(seconds / 60);
  return `预计剩余 ${minutes} 分钟`;
}
```

Then update the task card progress section. Replace the current progress/error display block:

```tsx
                  <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-medium text-gray-900 truncate">{task.title}</h3>
                    {task.state === "FAILURE" && task.error ? (
                      <p className="text-xs text-red-600 mt-0.5">{task.error}</p>
                    ) : (
                      <p className="text-xs text-gray-500 mt-0.5">
                        {taskStateLabel(task.state)}
                      </p>
                    )}
                  </div>
```

With:

```tsx
                  <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-medium text-gray-900 truncate">{task.title}</h3>
                    {task.state === "FAILURE" && task.error ? (
                      <p className="text-xs text-red-600 mt-0.5">{task.error}</p>
                    ) : (
                      <div className="mt-0.5">
                        <p className="text-xs text-gray-500">
                          {taskStateLabel(task.state)}
                          {task.state !== "SUCCESS" && formatRemainingTime(task.estimatedRemainingSeconds) && (
                            <span className="text-gray-400 ml-2">
                              {formatRemainingTime(task.estimatedRemainingSeconds)}
                            </span>
                          )}
                        </p>
                      </div>
                    )}
                  </div>
```

- [ ] **Step 5: Verify frontend compiles**

Run: `cd /home/tulip/project/socratiq/frontend && npx next build --no-lint 2>&1 | tail -5`

Expected: Build succeeds (or only pre-existing warnings).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/stores.ts frontend/src/app/page.tsx
git commit -m "feat: display estimated remaining time during content ingestion"
```

---

### Task 7: Integration Smoke Test

- [ ] **Step 1: Run all backend tests**

Run: `cd /home/tulip/project/socratiq/backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -20`

Expected: All tests pass, including new `test_time_estimator.py` and `test_cost_guard.py`.

- [ ] **Step 2: Verify Celery task imports cleanly**

Run: `cd /home/tulip/project/socratiq/backend && python -c "from app.worker.tasks.content_ingestion import ingest_source; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Final commit if any fixups needed**

Only if tests revealed issues in previous tasks. Otherwise skip.

---

Plan complete and saved to `docs/superpowers/plans/2026-03-28-ingestion-time-estimation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
