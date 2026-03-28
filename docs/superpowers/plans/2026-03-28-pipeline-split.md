# Pipeline Split: Content Ingestion vs Course Generation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the ingestion pipeline into two layers — content ingestion (dedupable) and course generation (goal-specific) — connected by Celery chain, with learning goal influencing lesson/lab generation.

**Architecture:** `ingest_source` is trimmed to Extract→Analyze→Store→Embed. A new `generate_course_task` handles lesson/lab generation + course assembly, receiving `goal` to customize prompts. The two are connected via Celery chain so the frontend sees one continuous progress flow. The import page passes `goal` to the backend, which threads it through the chain.

**Tech Stack:** Python (FastAPI, Celery chain, SQLAlchemy), Alembic, TypeScript (Next.js)

**Spec:** `docs/superpowers/specs/2026-03-28-pipeline-split-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/app/db/models/course.py` | Modify | Add `goal` column to Course |
| `backend/alembic/versions/XXXX_add_goal_to_courses.py` | Create | Migration |
| `backend/app/models/course.py` | Modify | Add `goal` to CourseGenerateRequest and CourseResponse |
| `backend/app/services/lesson_generator.py` | Modify | Accept `goal` param, inject into prompt |
| `backend/app/services/lab_generator.py` | Modify | Accept `goal` param, skip for overview, adjust prompt |
| `backend/app/worker/tasks/content_ingestion.py` | Modify | Remove lessons/labs steps, reorder store→embed, adjust time estimates |
| `backend/app/worker/tasks/course_generation.py` | Create | New Celery task: generate lessons/labs + assemble course |
| `backend/app/worker/celery_app.py` | Modify | Register new task module |
| `backend/app/api/routes/sources.py` | Modify | Accept `goal`, use Celery chain |
| `backend/app/services/course_generator.py` | Modify | Add goal param, call LessonGenerator/LabGenerator internally |
| `frontend/src/lib/api.ts` | Modify | Pass `goal` in createSourceFromURL/createSourceFromFile; update task status type |
| `frontend/src/app/import/page.tsx` | Modify | Pass `goal` to API calls |
| `frontend/src/app/page.tsx` | Modify | Remove manual `generateCourse` call; handle chain result with course_id |

---

### Task 1: Add `goal` column to Course table

**Files:**
- Modify: `backend/app/db/models/course.py`
- Modify: `backend/app/models/course.py`
- Create: Alembic migration

- [ ] **Step 1: Add goal column to Course ORM**

In `backend/app/db/models/course.py`, add after `description` (line 14):

```python
goal: Mapped[str | None] = mapped_column(String(50), nullable=True)
```

- [ ] **Step 2: Add goal to Pydantic schemas**

In `backend/app/models/course.py`, add `goal` field to `CourseGenerateRequest`:

```python
class CourseGenerateRequest(BaseModel):
    source_ids: list[uuid.UUID] = Field(..., min_length=1)
    title: str | None = None
    goal: str | None = None
```

Add `goal` to `CourseResponse`:

```python
class CourseResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    goal: str | None = None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 3: Generate and apply migration**

```bash
cd /home/tulip/project/socratiq/backend
uv run alembic revision --autogenerate -m "add goal to courses"
uv run alembic upgrade head
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models/course.py backend/app/models/course.py backend/alembic/versions/*goal*
git commit -m "feat: add goal column to courses table

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Add `goal` parameter to LessonGenerator and LabGenerator

**Files:**
- Modify: `backend/app/services/lesson_generator.py`
- Modify: `backend/app/services/lab_generator.py`
- Modify: `backend/tests/test_lesson_generator.py`
- Modify: `backend/tests/test_lab_generator.py`

- [ ] **Step 1: Write failing test for LessonGenerator with goal**

Add to `backend/tests/test_lesson_generator.py`:

```python
    @pytest.mark.asyncio
    async def test_generate_passes_goal_to_prompt(self):
        mock_provider = AsyncMock()
        mock_provider.chat.return_value = LLMResponse(
            content=[ContentBlock(type="text", text=json.dumps({
                "title": "Quick Overview",
                "summary": "Brief overview of Python",
                "sections": [{"heading": "Key Points", "content": "Main ideas.", "timestamp": 0.0,
                              "code_snippets": [], "key_concepts": ["python"], "diagrams": []}],
            }))],
            model="mock",
        )
        gen = LessonGenerator(mock_provider)
        result = await gen.generate(["Python basics intro"], "Python Basics", goal="overview")
        assert result.title == "Quick Overview"
        # Verify goal was included in the prompt
        call_args = mock_provider.chat.call_args
        prompt_content = call_args[1]["messages"][0].content if "messages" in call_args[1] else call_args[0][0][0].content
        assert "overview" in prompt_content.lower() or "快速了解" in prompt_content
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_lesson_generator.py::TestLessonGenerator::test_generate_passes_goal_to_prompt -v
```

Expected: FAIL — `generate()` doesn't accept `goal` parameter.

- [ ] **Step 3: Update LessonGenerator to accept goal**

In `backend/app/services/lesson_generator.py`, add goal-specific prompt snippets before the class:

```python
GOAL_PROMPTS = {
    "overview": "\n\nLearning goal: 快速了解大意 (Quick Overview). Keep content concise and focused on core ideas. Skip implementation details. Summarize key takeaways.",
    "master": "\n\nLearning goal: 系统掌握核心概念 (Deep Mastery). Explain each concept thoroughly with examples. Include edge cases and nuances. Build understanding step by step.",
    "apply": "\n\nLearning goal: 实战应用 (Practical Application). Focus on how-to steps and hands-on procedures. Emphasize code examples and practical usage patterns. Include actionable instructions.",
}
```

Update `generate` method signature and prompt:

```python
    async def generate(self, subtitle_chunks: list[str], video_title: str, goal: str | None = None) -> LessonContent:
        subtitles = "\n\n".join(subtitle_chunks)
        goal_suffix = GOAL_PROMPTS.get(goal, "") if goal else ""

        try:
            response = await self._provider.chat(
                messages=[UnifiedMessage(
                    role="user",
                    content=LESSON_PROMPT.format(title=video_title, subtitles=subtitles[:8000]) + goal_suffix,
                )],
                max_tokens=4000,
                temperature=0.3,
            )
```

- [ ] **Step 4: Run lesson tests**

```bash
uv run pytest tests/test_lesson_generator.py -v
```

Expected: All tests pass (existing tests use `goal=None` default).

- [ ] **Step 5: Write failing test for LabGenerator with goal**

Add to `backend/tests/test_lab_generator.py`:

```python
    @pytest.mark.asyncio
    async def test_overview_goal_skips_lab(self):
        mock_provider = AsyncMock()
        gen = LabGenerator(mock_provider)
        result = await gen.generate(
            code_snippets=[CodeSnippet(language="python", code="x=1", context="test")],
            lesson_context="intro",
            language="python",
            goal="overview",
        )
        assert result is None
        mock_provider.chat.assert_not_called()
```

- [ ] **Step 6: Update LabGenerator to accept goal**

In `backend/app/services/lab_generator.py`, update `generate` signature:

```python
    async def generate(
        self, code_snippets: list[CodeSnippet], lesson_context: str, language: str,
        goal: str | None = None,
    ) -> dict | None:
        if not code_snippets:
            return None

        # Overview goal: skip lab generation entirely
        if goal == "overview":
            return None

        snippets_text = "\n\n".join(
            f"```{s.language}\n{s.code}\n```\nContext: {s.context}" for s in code_snippets
        )

        goal_suffix = ""
        if goal == "master":
            goal_suffix = "\n\nLearning goal: 系统掌握 (Deep Mastery). Create focused exercises that test understanding of core concepts. Include fill-in-the-blank and targeted questions."
        elif goal == "apply":
            goal_suffix = "\n\nLearning goal: 实战应用 (Practical Application). Create a complete project-style lab with realistic starter code, comprehensive tests, and a full solution."
```

Then append `goal_suffix` to the prompt in the `response = await self._provider.chat(...)` call, adding it to the end of `LAB_PROMPT.format(...)`.

- [ ] **Step 7: Run all generator tests**

```bash
uv run pytest tests/test_lesson_generator.py tests/test_lab_generator.py -v
```

Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/lesson_generator.py backend/app/services/lab_generator.py backend/tests/test_lesson_generator.py backend/tests/test_lab_generator.py
git commit -m "feat: add goal parameter to LessonGenerator and LabGenerator

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Trim ingestion pipeline — remove lessons/labs, reorder store→embed

**Files:**
- Modify: `backend/app/worker/tasks/content_ingestion.py`

This is the core refactoring. The pipeline becomes: Extract → Analyze → Store → Embed → Done.

- [ ] **Step 1: Remove lessons/labs generation from `_ingest_source_async`**

In `backend/app/worker/tasks/content_ingestion.py`, delete the entire STEP 3 (Generate Lessons) and STEP 4 (Generate Labs) blocks. This includes:
- The `generating_lessons` status update and estimate
- The `LessonGenerator` import and usage
- The `page_groups` loop that generates lessons
- The `generating_labs` status update and estimate
- The `LabGenerator` import and usage
- The `labs_by_page` loop
- All timing instrumentation for lesson/lab calls (`cost_guard.log_usage` for `lesson_gen` and `lab_gen`)

- [ ] **Step 2: Remove lesson/lab data from source.metadata_**

In the Store step, remove `lesson_by_page` and `labs_by_page` from `source.metadata_`:

Replace the metadata update block with:

```python
                source.metadata_ = {
                    **source.metadata_,
                    "overall_summary": analysis.overall_summary,
                    "overall_difficulty": analysis.overall_difficulty,
                    "concept_count": len(analysis.concepts),
                    "chunk_count": len(analysis.chunks),
                    "estimated_study_minutes": analysis.estimated_study_minutes,
                    "suggested_prerequisites": analysis.suggested_prerequisites,
                }
```

- [ ] **Step 3: Update time estimate stages**

The `TimeEstimator` stages are now only: analyzing, storing, embedding. Update the estimate calls:
- Remove all `generating_lessons` and `generating_labs` estimate calculations
- The store step estimate uses `current_stage="storing"`
- The embed step estimate uses `current_stage="embedding"`

Also update `backend/app/services/time_estimator.py` — remove `generating_lessons` and `generating_labs` from `STAGES` list and `stage_estimates` dict:

```python
STAGES = ["analyzing", "storing", "embedding"]
```

And update `estimate_remaining` to remove the page_count/code_page_count parameters from the stage_estimates (they're no longer relevant):

```python
        stage_estimates = {
            "analyzing": math.ceil(total_chars / ANALYZER_BATCH_CHARS) * llm if total_chars >= 8000 else llm,
            "storing": DEFAULT_STORE_OVERHEAD_S,
            "embedding": math.ceil(chunk_count / EMBED_BATCH_SIZE) * DEFAULT_EMBED_LATENCY_S,
        }
```

- [ ] **Step 4: Update return value**

The return dict should no longer include `lessons_generated` or `labs_generated`:

```python
                return {
                    "source_id": source_id,
                    "title": source.title,
                    "chunks_created": len(chunk_ids),
                    "concepts_created": len(concept_ids),
                    "status": "ready",
                }
```

- [ ] **Step 5: Verify syntax**

```bash
uv run python -c "from app.worker.tasks.content_ingestion import ingest_source; print('OK')"
```

- [ ] **Step 6: Update time estimator tests**

Update `backend/tests/test_time_estimator.py` to match new formula (no lessons/labs stages). Remove `page_count` and `code_page_count` params from test calls and update expected values:

```python
class TestTimeEstimator:
    @pytest.mark.asyncio
    async def test_estimate_with_no_history_uses_defaults(self):
        mock_db = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalar.return_value = None
        mock_db.execute.return_value = mock_result

        estimator = TimeEstimator(mock_db)
        result = estimator.estimate_remaining(
            chunk_count=10,
            total_chars=50000,
        )
        # ceil(50000/6000)*20 + 5 + ceil(10/50)*5 = 9*20 + 5 + 5 = 190
        assert result == 190

    @pytest.mark.asyncio
    async def test_estimate_with_history_uses_calibrated_latency(self):
        mock_db = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalar.return_value = 12000
        mock_db.execute.return_value = mock_result

        estimator = TimeEstimator(mock_db)
        await estimator.load_calibration()
        result = estimator.estimate_remaining(
            chunk_count=10,
            total_chars=50000,
        )
        # ceil(50000/6000)*12 + 5 + ceil(10/50)*5 = 9*12 + 5 + 5 = 118
        assert result == 118

    def test_estimate_remaining_stages_from_current(self):
        estimator = TimeEstimator(db=None)
        result = estimator.estimate_remaining(
            chunk_count=10,
            total_chars=50000,
            current_stage="storing",
        )
        # storing(5) + embed(ceil(10/50)*5) = 5 + 5 = 10
        assert result == 10

    def test_estimate_small_content(self):
        estimator = TimeEstimator(db=None)
        result = estimator.estimate_remaining(
            chunk_count=5,
            total_chars=3000,
        )
        # <8000 chars: 1*20 + 5 + ceil(5/50)*5 = 20 + 5 + 5 = 30
        assert result == 30
```

- [ ] **Step 7: Run tests**

```bash
uv run pytest tests/test_time_estimator.py -v
```

Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/worker/tasks/content_ingestion.py backend/app/services/time_estimator.py backend/tests/test_time_estimator.py
git commit -m "refactor: trim ingestion pipeline to Extract→Analyze→Store→Embed only

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Create `generate_course_task` Celery task

**Files:**
- Create: `backend/app/worker/tasks/course_generation.py`
- Modify: `backend/app/worker/celery_app.py`

- [ ] **Step 1: Create the course generation task module**

Create `backend/app/worker/tasks/course_generation.py`:

```python
"""Course generation Celery task — generates lessons, labs, and assembles course."""

import logging
from uuid import UUID

from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="course_generation.generate_course",
    max_retries=1,
    default_retry_delay=30,
    soft_time_limit=600,
    time_limit=660,
)
def generate_course_task(self, ingest_result: dict, goal: str | None = None, user_id: str | None = None) -> dict:
    """Generate course from an ingested source.

    Args:
        ingest_result: Result dict from ingest_source (contains source_id, title, etc.)
        goal: Learning goal — "overview", "master", or "apply".
        user_id: User UUID string for course ownership.
    """
    import asyncio
    source_id = ingest_result["source_id"]
    return asyncio.run(_generate_course_async(self, source_id, goal, user_id))


async def _generate_course_async(task, source_id: str, goal: str | None, user_id: str | None) -> dict:
    """Async implementation of course generation."""
    import time
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.db.models.source import Source
    from app.db.models.content_chunk import ContentChunk as ContentChunkModel
    from app.db.models.concept import ConceptSource
    from app.db.models.course import Course, CourseSource, Section
    from app.db.models.lab import Lab
    from app.services.lesson_generator import LessonGenerator
    from app.services.lab_generator import LabGenerator
    from app.services.llm.router import ModelRouter, TaskType
    from app.services.cost_guard import CostGuard
    from app.config import get_settings

    settings = get_settings()
    worker_engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=10)
    worker_session_factory = async_sessionmaker(worker_engine, class_=AsyncSession, expire_on_commit=False)
    model_router = ModelRouter(session_factory=worker_session_factory, encryption_key=settings.llm_encryption_key)

    sid = UUID(source_id)
    uid = UUID(user_id) if user_id else None

    try:
        async with worker_session_factory() as db:
            source = await db.get(Source, sid)
            if not source or source.status != "ready":
                raise ValueError(f"Source {source_id} not ready for course generation")

            cost_guard = CostGuard(db)

            # Load chunks grouped by page
            result = await db.execute(
                select(ContentChunkModel)
                .where(ContentChunkModel.source_id == sid)
                .order_by(ContentChunkModel.created_at)
            )
            chunks = result.scalars().all()

            page_groups: dict[int, list] = {}
            for chunk in chunks:
                page_idx = (chunk.metadata_ or {}).get("page_index", 0)
                page_groups.setdefault(page_idx, []).append(chunk)

            # === STEP 1: GENERATE LESSONS ===
            task.update_state(state="PROGRESS", meta={"stage": "generating_lessons"})

            lesson_provider = await model_router.get_provider(TaskType.CONTENT_ANALYSIS)
            lesson_gen = LessonGenerator(lesson_provider)

            lesson_by_page: dict[int, object] = {}
            for page_idx in sorted(page_groups.keys()):
                page_chunks = page_groups[page_idx]
                chunk_texts = [c.text for c in page_chunks]
                page_title = (page_chunks[0].metadata_ or {}).get("page_title") or source.title or "Untitled"

                t0 = time.monotonic()
                lesson_content = await lesson_gen.generate(chunk_texts, page_title, goal=goal)
                lesson_ms = int((time.monotonic() - t0) * 1000)
                await cost_guard.log_usage(
                    user_id=uid, task_type="lesson_gen",
                    model_name="unknown", tokens_in=0, tokens_out=0,
                    duration_ms=lesson_ms,
                )
                lesson_by_page[page_idx] = lesson_content
                logger.info(f"Generated lesson for page {page_idx}: {len(lesson_content.sections)} sections")

            # === STEP 2: GENERATE LABS ===
            task.update_state(state="PROGRESS", meta={"stage": "generating_labs"})

            lab_gen = LabGenerator(lesson_provider)
            labs_by_page: dict[int, dict | None] = {}

            for page_idx, lesson_content in lesson_by_page.items():
                all_snippets = []
                for section in lesson_content.sections:
                    all_snippets.extend(section.code_snippets)

                if not all_snippets:
                    labs_by_page[page_idx] = None
                    continue

                lang_counts: dict[str, int] = {}
                for s in all_snippets:
                    lang_counts[s.language] = lang_counts.get(s.language, 0) + 1
                language = max(lang_counts, key=lang_counts.__getitem__)

                t0 = time.monotonic()
                lab_result = await lab_gen.generate(
                    code_snippets=all_snippets,
                    lesson_context=lesson_content.summary,
                    language=language,
                    goal=goal,
                )
                lab_ms = int((time.monotonic() - t0) * 1000)
                await cost_guard.log_usage(
                    user_id=uid, task_type="lab_gen",
                    model_name="unknown", tokens_in=0, tokens_out=0,
                    duration_ms=lab_ms,
                )
                labs_by_page[page_idx] = lab_result

            # === STEP 3: ASSEMBLE COURSE ===
            task.update_state(state="PROGRESS", meta={"stage": "assembling_course"})

            course_title = source.title or "Untitled Course"
            course = Course(title=course_title, description="", created_by=uid, goal=goal)
            db.add(course)
            await db.flush()

            db.add(CourseSource(course_id=course.id, source_id=sid))

            section_order = 0
            for page_idx in sorted(page_groups.keys()):
                page_chunks = page_groups[page_idx]
                lesson_content = lesson_by_page.get(page_idx)
                if not lesson_content:
                    continue

                first_meta = page_chunks[0].metadata_ or {}
                section_title = first_meta.get("page_title") or first_meta.get("topic") or f"Section {section_order + 1}"

                lesson_data = lesson_content.model_dump()
                section = Section(
                    course_id=course.id,
                    title=section_title,
                    order_index=section_order,
                    source_id=sid,
                    content={
                        "summary": lesson_content.summary,
                        "key_terms": lesson_content.sections[0].key_concepts if lesson_content.sections else [],
                        "has_code": any(s.code_snippets for s in lesson_content.sections),
                        "lesson": lesson_data,
                    },
                    difficulty=first_meta.get("difficulty", 1),
                )
                db.add(section)
                await db.flush()

                # Link chunks to section
                for chunk in page_chunks:
                    chunk.section_id = section.id

                # Create lab if available
                lab_data = labs_by_page.get(page_idx)
                if lab_data:
                    lab = Lab(
                        section_id=section.id,
                        title=lab_data.get("title", "Coding Exercise"),
                        description=lab_data.get("description", ""),
                        language=lab_data.get("language", "python"),
                        starter_code=lab_data.get("starter_code", {}),
                        test_code=lab_data.get("test_code", {}),
                        solution_code=lab_data.get("solution_code", {}),
                        run_instructions=lab_data.get("run_instructions", ""),
                        confidence=float(lab_data.get("confidence", 0.5)),
                    )
                    db.add(lab)

                section_order += 1

            await db.flush()

            # Generate course description
            from app.services.llm.base import UnifiedMessage
            try:
                provider = await model_router.get_provider(TaskType.CONTENT_ANALYSIS)
                response = await provider.chat(
                    messages=[UnifiedMessage(
                        role="user",
                        content=f'Write a 2-3 sentence course description for "{course_title}" with {section_order} sections. Be concise. Respond with ONLY the description.',
                    )],
                    max_tokens=256,
                    temperature=0.5,
                )
                course.description = "".join(b.text or "" for b in response.content if b.type == "text").strip()
            except Exception:
                course.description = f"A course based on {source.title or 'imported content'} with {section_order} sections."

            await db.commit()

            logger.info(f"Generated course '{course_title}' (goal={goal}) with {section_order} sections")
            return {
                "source_id": source_id,
                "course_id": str(course.id),
                "title": course_title,
                "sections_created": section_order,
                "labs_created": sum(1 for v in labs_by_page.values() if v),
                "goal": goal,
                "status": "ready",
            }
    finally:
        await worker_engine.dispose()
```

- [ ] **Step 2: Register task module in celery_app.py**

In `backend/app/worker/celery_app.py`, add after the existing task imports:

```python
import app.worker.tasks.course_generation  # noqa: F401
```

- [ ] **Step 3: Verify syntax**

```bash
uv run python -c "from app.worker.tasks.course_generation import generate_course_task; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/worker/tasks/course_generation.py backend/app/worker/celery_app.py
git commit -m "feat: add generate_course_task Celery task with goal-aware lesson/lab generation

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Wire Celery chain in source creation API

**Files:**
- Modify: `backend/app/api/routes/sources.py`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/app/import/page.tsx`

- [ ] **Step 1: Update API to accept `goal` and use Celery chain**

In `backend/app/api/routes/sources.py`, add import at top:

```python
from celery import chain
from app.worker.tasks.course_generation import generate_course_task
```

Update `create_source` signature to accept `goal`:

```python
async def create_source(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_local_user)],
    url: str | None = Form(None),
    source_type: str | None = Form(None),
    title: str | None = Form(None),
    goal: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> SourceResponse:
```

Replace the task dispatch block with chain logic:

```python
    if ref_source and ref_source.status == "ready":
        pipeline = chain(
            clone_source.s(str(source.id), str(ref_source.id)),
            generate_course_task.s(goal=goal, user_id=str(user.id)),
        )
        result = pipeline.delay()
        source.celery_task_id = result.id
    elif ref_source:
        # Ref still processing — Redis subscriber will dispatch clone, then chain continues
        # Store goal in source metadata for later use
        source.metadata_ = {**source.metadata_, "pending_goal": goal, "pending_user_id": str(user.id)}
    else:
        pipeline = chain(
            ingest_source.s(str(source.id)),
            generate_course_task.s(goal=goal, user_id=str(user.id)),
        )
        result = pipeline.delay()
        source.celery_task_id = result.id

    await db.commit()
    await db.refresh(source)

    return _source_to_response(source)
```

- [ ] **Step 2: Update ref_subscriber to use chain when dispatching clone**

In `backend/app/worker/ref_subscriber.py`, update the ready branch in `_handle_source_done` to chain clone → course generation:

```python
            if status == "ready":
                from celery import chain
                from app.worker.tasks.content_ingestion import clone_source
                from app.worker.tasks.course_generation import generate_course_task
                for waiter in waiters:
                    pending_goal = (waiter.metadata_ or {}).get("pending_goal")
                    pending_user_id = (waiter.metadata_ or {}).get("pending_user_id")
                    pipeline = chain(
                        clone_source.s(str(waiter.id), ref_source_id),
                        generate_course_task.s(goal=pending_goal, user_id=pending_user_id),
                    )
                    result = pipeline.delay()
                    waiter.celery_task_id = result.id
                    waiter.status = "pending"
                    logger.info(f"Dispatched clone→course chain for {waiter.id}")
```

- [ ] **Step 3: Update frontend API to pass goal**

In `frontend/src/lib/api.ts`, update `createSourceFromURL`:

```typescript
export async function createSourceFromURL(
  url: string,
  sourceType?: string,
  title?: string,
  goal?: string,
): Promise<SourceResponse> {
  const form = new FormData();
  form.append("url", url);
  if (sourceType) form.append("source_type", sourceType);
  if (title) form.append("title", title);
  if (goal) form.append("goal", goal);
```

Update `createSourceFromFile`:

```typescript
export async function createSourceFromFile(
  file: File,
  title?: string,
  goal?: string,
): Promise<SourceResponse> {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  if (goal) form.append("goal", goal);
```

- [ ] **Step 4: Update import page to pass goal**

In `frontend/src/app/import/page.tsx`, update the API calls in `handleImport`:

Replace:
```typescript
        source = await createSourceFromURL(url.trim());
```
With:
```typescript
        source = await createSourceFromURL(url.trim(), undefined, undefined, goal ?? undefined);
```

Replace:
```typescript
        source = await createSourceFromFile(pdfFile);
```
With:
```typescript
        source = await createSourceFromFile(pdfFile, undefined, goal ?? undefined);
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/sources.py backend/app/worker/ref_subscriber.py frontend/src/lib/api.ts frontend/src/app/import/page.tsx
git commit -m "feat: wire Celery chain (ingest→course) with goal parameter threading

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Update Dashboard — remove manual generateCourse, handle chain result

**Files:**
- Modify: `frontend/src/app/page.tsx`

- [ ] **Step 1: Remove manual generateCourse call**

In `frontend/src/app/page.tsx`, the polling effect (around line 107-116) currently calls `generateCourse` when ingest succeeds. Replace the SUCCESS handling block:

```typescript
          if (status.state === "SUCCESS" && !task.courseId) {
            // Auto-generate course
            try {
              const course = await generateCourse([task.sourceId]);
              updateTask(task.taskId, { courseId: course.id, state: "SUCCESS" });
              listCourses().then((res) => setCourses(res.items)).catch(() => {});
            } catch {
              updateTask(task.taskId, { state: "FAILURE", error: "课程生成失败" });
            }
          }
```

With:

```typescript
          if (status.state === "SUCCESS" && !task.courseId) {
            // Chain completed — result includes course_id
            const courseId = status.result?.course_id;
            if (courseId) {
              updateTask(task.taskId, { courseId, state: "SUCCESS" });
            } else {
              updateTask(task.taskId, { state: "SUCCESS" });
            }
            listCourses().then((res) => setCourses(res.items)).catch(() => {});
          }
```

- [ ] **Step 2: Update task status type to include result**

In `frontend/src/lib/api.ts`, update `getTaskStatus` return type:

```typescript
export async function getTaskStatus(taskId: string): Promise<{
  task_id: string;
  state: string;
  result?: { course_id?: string; [key: string]: unknown };
  error?: string;
  progress?: unknown;
  stage?: string;
  estimated_remaining_seconds?: number;
}> {
```

- [ ] **Step 3: Add new stage labels**

In `frontend/src/app/page.tsx`, add to `taskStateLabel`:

```typescript
    assembling_course: "组装课程...",
```

- [ ] **Step 4: Remove unused generateCourse import**

In `frontend/src/app/page.tsx`, remove `generateCourse` from the import line if it's no longer used elsewhere in the file.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/page.tsx frontend/src/lib/api.ts
git commit -m "feat: Dashboard uses chain result for course_id, removes manual generateCourse

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Integration verification

- [ ] **Step 1: Run all backend tests**

```bash
cd /home/tulip/project/socratiq/backend
uv run pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All non-integration tests pass.

- [ ] **Step 2: Verify all imports**

```bash
uv run python -c "from app.worker.tasks.content_ingestion import ingest_source, clone_source; print('ingest OK')"
uv run python -c "from app.worker.tasks.course_generation import generate_course_task; print('course OK')"
uv run python -c "from app.api.routes.sources import router; print('sources OK')"
uv run python -c "from app.worker.celery_app import celery_app; print('celery OK')"
```

- [ ] **Step 3: Verify chain construction**

```bash
uv run python -c "
from celery import chain
from app.worker.tasks.content_ingestion import ingest_source
from app.worker.tasks.course_generation import generate_course_task
pipeline = chain(ingest_source.s('test-id'), generate_course_task.s(goal='master', user_id='user-id'))
print(f'Chain constructed: {pipeline}')
print('OK')
"
```

- [ ] **Step 4: Commit any fixups**

---

## Self-Review

**Spec coverage:**
- ✅ Pipeline split: ingest = Extract→Analyze→Store→Embed (Task 3)
- ✅ Course generation Celery task with goal (Task 4)
- ✅ Celery chain connecting both (Task 5)
- ✅ Goal threading: frontend→API→chain→generators (Tasks 1,2,5)
- ✅ LessonGenerator goal prompts (Task 2)
- ✅ LabGenerator goal prompts + overview skip (Task 2)
- ✅ Course.goal column (Task 1)
- ✅ Dashboard removes manual generateCourse (Task 6)
- ✅ Clone path chains to course generation (Task 5 step 2)

**Placeholder scan:** No TBD/TODO found.

**Type consistency:** `generate_course_task(ingest_result, goal, user_id)` matches chain usage. `goal` parameter consistent across LessonGenerator.generate(), LabGenerator.generate(), CourseGenerateRequest, Course model. `clone_source` return dict matches `generate_course_task` input (`source_id` key present).
