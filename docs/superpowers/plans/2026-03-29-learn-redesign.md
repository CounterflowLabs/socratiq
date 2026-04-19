# Learn Experience Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the single-course learning experience with video+lesson split layout, AI tutor drawer, Lab editor, knowledge graph integration, inline SRS review, progress tracking, and Apple-style visual system.

**Architecture:** Backend-first approach — fix data contracts and add new endpoints first, then rebuild frontend pages against correct APIs. Visual system applied as a foundational layer before page work. Each task is independently deployable.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Next.js 16, React 19, Zustand, Tailwind CSS 4, Monaco Editor, JSZip, D3.js

**Spec:** `docs/superpowers/specs/2026-03-29-learn-page-redesign-design.md`

---

## Phase 1: Backend Data Contract Fixes

### Task 1: Fix CourseDetailResponse — add SourceSummary and section source_id

**Files:**
- Modify: `backend/app/models/course.py:27-50`
- Modify: `backend/app/api/routes/courses.py:93-138`
- Test: `backend/tests/test_smoke.py` (existing test for GET /courses/{id})

- [ ] **Step 1: Add SourceSummary model and update response schemas**

In `backend/app/models/course.py`, add `SourceSummary` class after `CourseResponse` (line 24), add `source_id` to `SectionResponse`, and replace `source_ids` with `sources` in `CourseDetailResponse`:

```python
# After CourseResponse (line 24), add:
class SourceSummary(BaseModel):
    id: uuid.UUID
    url: str | None = None
    type: str

# In SectionResponse (line 27), add field after source_end:
    source_id: uuid.UUID | None = None

# In CourseDetailResponse (line 40), replace source_ids:
    sources: list[SourceSummary] = Field(default_factory=list)
    # DELETE: source_ids: list[uuid.UUID] = Field(default_factory=list)
```

- [ ] **Step 2: Update course detail route handler**

In `backend/app/api/routes/courses.py`, update `get_course()` (line 93) to join Source table and build `sources` list instead of `source_ids`:

```python
# Replace the source_ids query (around line 115-120) with:
from app.db.models import Source
source_rows = (await db.execute(
    select(Source.id, Source.url, Source.type)
    .join(CourseSource, CourseSource.source_id == Source.id)
    .where(CourseSource.course_id == course.id)
)).all()
sources = [SourceSummary(id=r.id, url=r.url, type=r.type) for r in source_rows]

# In the CourseDetailResponse construction, use sources=sources instead of source_ids=...
```

Also update `SectionResponse` construction to include `source_id=section.source_id`.

- [ ] **Step 3: Run existing tests to verify no regression**

Run: `cd backend && .venv/bin/pytest tests/test_smoke.py -k "course" -v`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/course.py backend/app/api/routes/courses.py
git commit -m "fix: replace source_ids with sources in CourseDetailResponse, add source_id to SectionResponse"
```

---

### Task 2: Add explanation to exercise submit response

**Files:**
- Modify: `backend/app/api/routes/exercises.py:38-44,75-135`

- [ ] **Step 1: Add explanation field to SubmitAnswerResponse**

In `backend/app/api/routes/exercises.py` line 38-44, add field:

```python
class SubmitAnswerResponse(BaseModel):
    submission_id: uuid.UUID
    exercise_id: uuid.UUID
    attempt_number: int
    score: float | None
    feedback: str | None
    correct: bool | None
    explanation: str | None = None  # ADD THIS LINE
```

- [ ] **Step 2: Populate explanation in submit handler**

In `submit_answer()` (around line 130), after grading, add `explanation=exercise.explanation` to the response construction:

```python
return SubmitAnswerResponse(
    submission_id=submission.id,
    exercise_id=exercise.id,
    attempt_number=submission.attempt_number,
    score=submission.score,
    feedback=submission.feedback,
    correct=float(submission.score) >= 0.8 if submission.score is not None else None,
    explanation=exercise.explanation,  # ADD THIS
)
```

- [ ] **Step 3: Run tests**

Run: `cd backend && .venv/bin/pytest tests/test_smoke.py -k "exercise" -v`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/routes/exercises.py
git commit -m "fix: include exercise explanation in submit response"
```

---

### Task 3: Add section_id to chat request

**Files:**
- Modify: `backend/app/models/chat.py` (ChatRequest)
- Modify: `backend/app/api/routes/chat.py:36-140`

- [ ] **Step 1: Add section_id to ChatRequest**

In `backend/app/models/chat.py`, add to `ChatRequest`:

```python
class ChatRequest(BaseModel):
    message: str
    conversation_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None
    section_id: uuid.UUID | None = None  # ADD THIS
```

- [ ] **Step 2: Pass section_id to agent context in chat route**

In `backend/app/api/routes/chat.py`, the `chat()` handler already receives `ChatRequest`. Pass `section_id` to the MentorAgent system prompt context. In the section where the system prompt is built (around line 85-90), add section context:

```python
# If section_id is provided, load section title for agent context
section_context = ""
if req.section_id:
    section = await db.get(Section, req.section_id)
    if section:
        section_context = f"\n\nThe student is currently studying section: {section.title}"
```

Append `section_context` to the system prompt string.

- [ ] **Step 3: Run tests**

Run: `cd backend && .venv/bin/pytest tests/test_smoke.py -k "chat" -v`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/chat.py backend/app/api/routes/chat.py
git commit -m "feat: add section_id context to chat endpoint"
```

---

### Task 4: SectionProgress table + migration + endpoints

**Files:**
- Create: `backend/app/db/models/section_progress.py`
- Modify: `backend/app/db/models/__init__.py:22-46`
- Create: `backend/app/api/routes/progress.py`
- Modify: `backend/app/main.py:28-41`
- Modify: `backend/app/api/routes/exercises.py:75-135` (auto-update score)

- [ ] **Step 1: Create SectionProgress model**

Create `backend/app/db/models/section_progress.py`:

```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.models.base import Base, BaseMixin


class SectionProgress(BaseMixin, Base):
    __tablename__ = "section_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "section_id", name="uq_progress_user_section"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id"), nullable=False, index=True)
    lesson_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    lab_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    exercise_best_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Note: BaseMixin already provides id, created_at, updated_at — do NOT redefine updated_at
```

- [ ] **Step 2: Export SectionProgress in models __init__**

In `backend/app/db/models/__init__.py`, add import and export:

```python
from app.db.models.section_progress import SectionProgress
# Add SectionProgress to __all__
```

- [ ] **Step 3: Generate Alembic migration**

Run: `cd backend && .venv/bin/alembic revision --autogenerate -m "add section_progress table"`

- [ ] **Step 4: Create progress routes**

Create `backend/app/api/routes/progress.py`:

```python
import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_local_user
from app.db.models import Section, SectionProgress, User

router = APIRouter(prefix="/api/v1", tags=["progress"])


class SectionProgressResponse(BaseModel):
    section_id: uuid.UUID
    lesson_read: bool
    lab_completed: bool
    exercise_best_score: float | None
    status: str  # "not_started" | "in_progress" | "completed"


class ProgressEventRequest(BaseModel):
    event: str  # "lesson_read" | "lab_completed"


def _compute_status(p: SectionProgress) -> str:
    if p.lesson_read and p.exercise_best_score is not None and p.exercise_best_score >= 60.0:
        return "completed"
    if p.lesson_read or p.lab_completed or p.exercise_best_score is not None:
        return "in_progress"
    return "not_started"


@router.get("/courses/{course_id}/progress")
async def get_course_progress(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_local_user),
) -> list[SectionProgressResponse]:
    section_ids = (await db.execute(
        select(Section.id).where(Section.course_id == course_id)
    )).scalars().all()

    rows = (await db.execute(
        select(SectionProgress).where(
            SectionProgress.user_id == user.id,
            SectionProgress.section_id.in_(section_ids),
        )
    )).scalars().all()

    progress_map = {r.section_id: r for r in rows}
    result = []
    for sid in section_ids:
        if sid in progress_map:
            p = progress_map[sid]
            result.append(SectionProgressResponse(
                section_id=sid,
                lesson_read=p.lesson_read,
                lab_completed=p.lab_completed,
                exercise_best_score=p.exercise_best_score,
                status=_compute_status(p),
            ))
        else:
            result.append(SectionProgressResponse(
                section_id=sid, lesson_read=False, lab_completed=False,
                exercise_best_score=None, status="not_started",
            ))
    return result


@router.post("/sections/{section_id}/progress")
async def record_progress(
    section_id: uuid.UUID,
    req: ProgressEventRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_local_user),
):
    row = (await db.execute(
        select(SectionProgress).where(
            SectionProgress.user_id == user.id,
            SectionProgress.section_id == section_id,
        )
    )).scalar_one_or_none()

    if not row:
        row = SectionProgress(user_id=user.id, section_id=section_id)
        db.add(row)

    if req.event == "lesson_read":
        row.lesson_read = True
    elif req.event == "lab_completed":
        row.lab_completed = True

    await db.commit()
    return {"ok": True}
```

- [ ] **Step 5: Register progress router in main.py**

In `backend/app/main.py`, add:

```python
from app.api.routes.progress import router as progress_router
app.include_router(progress_router)
```

- [ ] **Step 6: Auto-update exercise_best_score on submission**

In `backend/app/api/routes/exercises.py`, in `submit_answer()` after grading (around line 130), add:

```python
# After submission is saved and scored
if submission.score is not None:
    from app.db.models import SectionProgress
    progress = (await db.execute(
        select(SectionProgress).where(
            SectionProgress.user_id == user.id,
            SectionProgress.section_id == exercise.section_id,
        )
    )).scalar_one_or_none()
    if not progress:
        progress = SectionProgress(user_id=user.id, section_id=exercise.section_id)
        db.add(progress)
    if progress.exercise_best_score is None or submission.score > progress.exercise_best_score:
        progress.exercise_best_score = submission.score
    await db.commit()
```

- [ ] **Step 7: Run migration (requires DB)**

Run: `cd backend && .venv/bin/alembic upgrade head`

- [ ] **Step 8: Commit**

```bash
git add backend/app/db/models/section_progress.py backend/app/db/models/__init__.py \
  backend/app/api/routes/progress.py backend/app/main.py \
  backend/app/api/routes/exercises.py backend/alembic/versions/
git commit -m "feat: add section_progress tracking table, endpoints, and auto-update on exercise submit"
```

---

### Task 5: Enrich review due response with concept details

**Files:**
- Modify: `backend/app/api/routes/reviews.py:18-77`

- [ ] **Step 1: Update ReviewItemResponse and query**

In `backend/app/api/routes/reviews.py`, add fields to `ReviewItemResponse` (line 18):

```python
class ReviewItemResponse(BaseModel):
    id: uuid.UUID
    concept_id: uuid.UUID
    concept_name: str = ""
    concept_description: str = ""
    review_question: str | None = None
    review_answer: str | None = None
    easiness: float
    interval_days: int
    repetitions: int
    review_at: datetime
    last_reviewed_at: datetime | None = None
```

- [ ] **Step 2: Update get_due_reviews to join Concept and Exercise**

In `get_due_reviews()` (line 52), after fetching ReviewItems, enrich with concept and exercise data:

```python
from app.db.models import Concept, Exercise

# After getting review items from service:
items = srs.get_due_reviews(...)  # existing call

# Batch-load concepts and exercises to avoid N+1 queries
concept_ids = [i.concept_id for i in items]
exercise_ids = [i.exercise_id for i in items if i.exercise_id]

concepts_map = {}
if concept_ids:
    rows = (await db.execute(select(Concept).where(Concept.id.in_(concept_ids)))).scalars().all()
    concepts_map = {c.id: c for c in rows}

exercises_map = {}
if exercise_ids:
    rows = (await db.execute(select(Exercise).where(Exercise.id.in_(exercise_ids)))).scalars().all()
    exercises_map = {e.id: e for e in rows}

enriched = []
for item in items:
    concept = concepts_map.get(item.concept_id)
    concept_name = concept.name if concept else ""
    concept_desc = concept.description if concept else ""

    review_question = None
    review_answer = None
    if item.exercise_id:
        exercise = exercises_map.get(item.exercise_id)
        if exercise:
            review_question = exercise.question
            review_answer = exercise.explanation

    enriched.append(ReviewItemResponse(
        id=item.id,
        concept_id=item.concept_id,
        concept_name=concept_name,
        concept_description=concept_desc,
        review_question=review_question or concept_name,
        review_answer=review_answer or concept_desc,
        easiness=item.easiness,
        interval_days=item.interval_days,
        repetitions=item.repetitions,
        review_at=item.review_at,
        last_reviewed_at=item.last_reviewed_at,
    ))

return DueReviewsResponse(items=enriched, total=len(enriched))
```

- [ ] **Step 3: Run tests**

Run: `cd backend && .venv/bin/pytest tests/test_spaced_repetition.py -v`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/routes/reviews.py
git commit -m "feat: enrich review items with concept name and exercise question/answer"
```

---

## Phase 2: Frontend Foundation

### Task 6: Install new dependencies (Monaco Editor, JSZip)

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install packages**

```bash
cd frontend && npm install @monaco-editor/react jszip
```

Note: JSZip ships its own TypeScript declarations — no `@types/jszip` needed.

- [ ] **Step 2: Verify build still works**

Run: `cd frontend && npm run build`

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore: add Monaco Editor and JSZip dependencies"
```

---

### Task 7: Apple design system — CSS custom properties + Tailwind theme

**Files:**
- Modify: `frontend/src/app/globals.css:1-58`

- [ ] **Step 1: Replace globals.css with Apple design tokens**

Replace the content of `frontend/src/app/globals.css` with the design system. Preserve the existing custom property structure (lines 4-25) but update values to match the Apple spec. Add typography, spacing, and component tokens:

```css
@import "tailwindcss";

:root {
  /* Colors */
  --bg: #fafafa;
  --surface: #ffffff;
  --surface-alt: #f5f5f7;
  --border: rgba(0, 0, 0, 0.08);
  --border-medium: rgba(0, 0, 0, 0.15);
  --text: #1d1d1f;
  --text-secondary: #6e6e73;
  --text-tertiary: #86868b;

  /* Brand */
  --primary: #0071e3;
  --primary-hover: #0077ed;
  --primary-light: #e8f2fe;

  /* Status */
  --success: #34c759;
  --success-light: #e8f8ed;
  --warning: #ff9500;
  --warning-light: #fff4e5;
  --error: #ff3b30;
  --error-light: #fff0ef;

  /* Spacing */
  --page-padding: 48px;
  --section-gap: 48px;
  --card-padding: 24px;

  /* Radius */
  --radius-sm: 8px;
  --radius: 12px;
  --radius-lg: 16px;
  --radius-pill: 9999px;

  /* Shadow */
  --shadow-sm: 0 1px 4px rgba(0, 0, 0, 0.04);
  --shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  --shadow-lg: 0 4px 20px rgba(0, 0, 0, 0.1);

  /* Animation */
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --duration: 0.3s;
  --duration-fast: 0.2s;
}

@media (max-width: 768px) {
  :root {
    --page-padding: 20px;
    --section-gap: 32px;
    --card-padding: 16px;
  }
}

/* Typography */
body {
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: var(--text);
  background: var(--bg);
  font-size: 16px;
  line-height: 1.6;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-medium); border-radius: 3px; }

/* Prose (lesson content) */
.prose p { margin-bottom: 1em; line-height: 1.7; }
.prose ul, .prose ol { margin-bottom: 1em; padding-left: 1.5em; }
.prose pre { background: var(--surface-alt); border-radius: var(--radius); padding: 16px; overflow-x: auto; margin-bottom: 1em; }
.prose code { font-size: 0.9em; }
.prose h2 { font-size: 1.5rem; font-weight: 600; margin: 1.5em 0 0.5em; }
.prose h3 { font-size: 1.25rem; font-weight: 600; margin: 1.25em 0 0.5em; }

/* Card base */
.card {
  background: var(--surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  padding: var(--card-padding);
  transition: box-shadow var(--duration) var(--ease-out), transform var(--duration) var(--ease-out);
}
.card:hover {
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px);
}
.card-flat {
  background: var(--surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  padding: var(--card-padding);
}

/* Button styles */
.btn-primary {
  background: var(--primary);
  color: white;
  border: none;
  border-radius: var(--radius-pill);
  padding: 10px 24px;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}
.btn-primary:hover { background: var(--primary-hover); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-secondary {
  background: transparent;
  color: var(--text);
  border: 1px solid var(--border-medium);
  border-radius: var(--radius);
  padding: 8px 20px;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}
.btn-secondary:hover { background: var(--surface-alt); }

.btn-ghost {
  background: transparent;
  color: var(--text-secondary);
  border: none;
  padding: 8px 16px;
  font-size: 15px;
  cursor: pointer;
  border-radius: var(--radius);
  transition: background var(--duration-fast) var(--ease-out);
}
.btn-ghost:hover { background: rgba(0, 0, 0, 0.04); }

/* Badge */
.badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-weight: 500;
}

/* Preserve existing layout classes used by layout.tsx and sidebar.tsx */
.app-layout { display: flex; min-height: 100vh; }
.main-content { flex: 1; min-width: 0; }
```

- [ ] **Step 2: Verify existing pages still render**

Run: `cd frontend && npm run build`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/globals.css
git commit -m "style: apply Apple design system CSS custom properties and utility classes"
```

---

### Task 8: Update frontend API types to match new backend contracts

**Files:**
- Modify: `frontend/src/lib/api.ts:70-91,314-344`

- [ ] **Step 1: Add SourceSummary type, update CourseDetailResponse**

In `frontend/src/lib/api.ts`:

```typescript
// After SectionResponse (line 78), add:
export interface SourceSummary {
  id: string;
  url: string | null;
  type: string;
}

// Update SectionResponse (line 70) — add source_id:
export interface SectionResponse {
  id: string;
  title: string;
  order_index?: number;
  source_id?: string;  // ADD THIS
  source_start?: string;
  source_end?: string;
  content: Record<string, unknown>;
  difficulty: number;
}

// Update CourseDetailResponse (line 88) — replace source_ids with sources:
export interface CourseDetailResponse extends CourseResponse {
  sources: SourceSummary[];  // CHANGED from source_ids: string[]
  sections: SectionResponse[];
}
```

- [ ] **Step 2: Fix SubmissionResult type**

```typescript
// Update SubmissionResult (line 323):
export interface SubmissionResult {
  submission_id: string;
  score: number | null;
  feedback: string | null;  // was string
  explanation: string | null;  // was string
}
```

- [ ] **Step 3: Fix getSectionExercises to read `items`**

```typescript
// Around line 330, change:
export async function getSectionExercises(sectionId: string): Promise<{ exercises: ExerciseResponse[] }> {
  const res = await fetch(`${API_BASE}/exercises/section/${sectionId}`);
  if (!res.ok) throw new Error("Failed to fetch exercises");
  const data = await res.json();
  return { exercises: data.items ?? [] };  // Map items → exercises for frontend compatibility
}
```

- [ ] **Step 4: Add sectionId to streamChat using options object**

```typescript
// Replace the positional params with an options object to avoid breaking callers (around line 131):
interface StreamChatOptions {
  message: string;
  conversationId?: string;
  courseId?: string;
  sectionId?: string;
  signal?: AbortSignal;
}

export async function* streamChat(opts: StreamChatOptions): AsyncGenerator<ChatStreamEvent> {
  const body: Record<string, unknown> = { message: opts.message };
  if (opts.conversationId) body.conversation_id = opts.conversationId;
  if (opts.courseId) body.course_id = opts.courseId;
  if (opts.sectionId) body.section_id = opts.sectionId;
  // ... rest unchanged, but use opts.signal instead of signal
```

**IMPORTANT**: This changes the call signature. All callers must be updated in the same commit. Current callers:
- `frontend/src/app/learn/page.tsx:237` — will be rewritten in Task 9
- Update this call in the same task to use the new options object.

- [ ] **Step 5: Add progress API functions**

Add at end of file:

```typescript
// Progress
export async function getCourseProgress(courseId: string): Promise<
  Array<{ section_id: string; lesson_read: boolean; lab_completed: boolean; exercise_best_score: number | null; status: string }>
> {
  const res = await fetch(`${API_BASE}/courses/${courseId}/progress`);
  if (!res.ok) throw new Error("Failed to fetch progress");
  return res.json();
}

export async function recordProgress(sectionId: string, event: "lesson_read" | "lab_completed"): Promise<void> {
  await fetch(`${API_BASE}/sections/${sectionId}/progress`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event }),
  });
}
```

- [ ] **Step 6: Update review item type**

```typescript
// Update getDueReviews return type (around line 347):
export interface ReviewItemDetail {
  id: string;
  concept_name: string;
  concept_description: string;
  review_question: string | null;
  review_answer: string | null;
  easiness: number;
  interval_days: number;
  repetitions: number;
  review_at: string;
}

export async function getDueReviews(): Promise<{ items: ReviewItemDetail[]; total: number }> {
  const res = await fetch(`${API_BASE}/reviews/due`);
  if (!res.ok) throw new Error("Failed to fetch reviews");
  return res.json();
}
```

- [ ] **Step 7: Run lint**

Run: `cd frontend && npm run lint`

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "fix: align frontend API types with backend contracts (sources, exercises, reviews, progress)"
```

---

## Phase 3: Core Pages

### Task 9: Learn page — video + lesson split layout

This is the largest task. Rewrite `frontend/src/app/learn/page.tsx` from the current 4-tab layout to the new split view.

**Files:**
- Rewrite: `frontend/src/app/learn/page.tsx`
- Create: `frontend/src/components/tutor-drawer.tsx`
- Create: `frontend/src/components/lab/lab-editor.tsx`
- Modify: `frontend/src/components/lesson/lesson-renderer.tsx` (no structural changes, just verify props)

- [ ] **Step 1: Create TutorDrawer component**

Create `frontend/src/components/tutor-drawer.tsx`:

```tsx
"use client";
import { useEffect, useRef, useState } from "react";
import { X, MessageCircle, Send } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useChatStore } from "@/lib/stores";
import { streamChat } from "@/lib/api";

interface TutorDrawerProps {
  open: boolean;
  onClose: () => void;
  courseId: string | null;
  sectionId: string | null;
}

const QUICK_PROMPTS = ["解释这个概念", "举个例子", "我不理解", "能简单点说吗"];

export default function TutorDrawer({ open, onClose, courseId, sectionId }: TutorDrawerProps) {
  const { messages, conversationId, isStreaming, addMessage, appendToLast, setConversationId, setStreaming } = useChatStore();
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage(text: string) {
    if (!text.trim() || isStreaming) return;
    const userMsg = { id: crypto.randomUUID(), role: "user" as const, content: text };
    addMessage(userMsg);
    setInput("");
    setStreaming(true);

    const assistantId = crypto.randomUUID();
    addMessage({ id: assistantId, role: "assistant", content: "" });

    try {
      for await (const event of streamChat({ message: text, conversationId: conversationId ?? undefined, courseId: courseId ?? undefined, sectionId: sectionId ?? undefined })) {
        if (event.event === "text_delta" && event.text) {
          appendToLast(event.text);
        } else if (event.event === "tool_start") {
          appendToLast("\n\n*正在搜索知识库...*\n\n");
        } else if (event.event === "message_end" && event.conversation_id) {
          setConversationId(event.conversation_id);
        }
      }
    } catch { /* stream ended */ }
    setStreaming(false);
  }

  return (
    <>
      {/* Backdrop */}
      {open && <div className="fixed inset-0 bg-black/20 z-40" onClick={onClose} />}
      {/* Drawer */}
      <div
        className="fixed top-0 right-0 h-full z-50 bg-[var(--surface)] shadow-lg flex flex-col transition-transform duration-300"
        style={{
          width: "min(400px, 100vw)",
          transform: open ? "translateX(0)" : "translateX(100%)",
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2">
            <MessageCircle size={18} />
            <span className="font-semibold">AI 导师</span>
          </div>
          <button onClick={onClose} className="btn-ghost p-2 rounded-full">
            <X size={18} />
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <p className="text-[var(--text-tertiary)] text-center mt-8">有什么不懂的？问我吧</p>
          )}
          {messages.map((msg) => (
            <div key={msg.id} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-2 text-[15px] ${
                  msg.role === "user"
                    ? "bg-[var(--primary)] text-white"
                    : "bg-[var(--surface-alt)] text-[var(--text)]"
                }`}
              >
                {msg.role === "assistant" ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]} className="prose prose-sm">
                    {msg.content || "…"}
                  </ReactMarkdown>
                ) : (
                  msg.content
                )}
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Quick prompts */}
        <div className="px-4 pb-2 flex gap-2 flex-wrap">
          {QUICK_PROMPTS.map((p) => (
            <button
              key={p}
              onClick={() => sendMessage(p)}
              disabled={isStreaming}
              className="badge bg-[var(--surface-alt)] text-[var(--text-secondary)] hover:bg-[var(--border)] cursor-pointer transition-colors"
            >
              {p}
            </button>
          ))}
        </div>

        {/* Input */}
        <div className="p-4 border-t border-[var(--border)] flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage(input)}
            placeholder="输入问题..."
            disabled={isStreaming}
            className="flex-1 px-4 py-2 rounded-full border border-[var(--border-medium)] bg-[var(--surface)] text-[15px] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={isStreaming || !input.trim()}
            className="btn-primary rounded-full p-2.5"
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 2: Create LabEditor component**

Create `frontend/src/components/lab/lab-editor.tsx`:

```tsx
"use client";
import { useState, useMemo } from "react";
import { Download, RotateCcw, FileCode, TestTube } from "lucide-react";
import Editor from "@monaco-editor/react";
import type { LabResponse } from "@/lib/api";

interface LabEditorProps {
  lab: LabResponse;
}

export default function LabEditor({ lab }: LabEditorProps) {
  const starterFiles = Object.entries(lab.starter_code);
  const testFiles = Object.entries(lab.test_code);
  const allFiles = [
    ...starterFiles.map(([name, code]) => ({ name, code, type: "starter" as const })),
    ...testFiles.map(([name, code]) => ({ name, code, type: "test" as const })),
  ];

  const [activeFile, setActiveFile] = useState(allFiles[0]?.name ?? "");
  const [editedCode, setEditedCode] = useState<Record<string, string>>(() =>
    Object.fromEntries(starterFiles)
  );

  const currentFile = allFiles.find((f) => f.name === activeFile);
  const isReadOnly = currentFile?.type === "test";
  const currentCode = isReadOnly ? currentFile?.code ?? "" : editedCode[activeFile] ?? "";

  const langMap: Record<string, string> = { py: "python", js: "javascript", ts: "typescript", go: "go", rs: "rust" };
  const ext = activeFile.split(".").pop() ?? "";
  const monacoLang = langMap[ext] ?? lab.language ?? "plaintext";

  function handleReset() {
    if (confirm("重置将丢失所有修改，确认？")) {
      setEditedCode(Object.fromEntries(starterFiles));
    }
  }

  async function handleDownload() {
    const JSZip = (await import("jszip")).default;
    const zip = new JSZip();
    // Edited starter code
    for (const [name, code] of Object.entries(editedCode)) {
      zip.file(name, code);
    }
    // Original test code
    for (const [name, code] of testFiles) {
      zip.file(name, code);
    }
    // README
    zip.file("README.md", `# ${lab.title}\n\n${lab.description}\n\n## Run\n\n${lab.run_instructions}`);

    const blob = await zip.generateAsync({ type: "blob" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${lab.title.replace(/\s+/g, "-").toLowerCase()}.zip`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)]">
        <div>
          <h2 className="text-lg font-semibold">{lab.title}</h2>
          <p className="text-sm text-[var(--text-secondary)]">{lab.description}</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="badge bg-[var(--primary-light)] text-[var(--primary)]">信心度 {Math.round(lab.confidence * 100)}%</span>
          <button onClick={handleDownload} className="btn-secondary flex items-center gap-1.5 text-sm">
            <Download size={14} /> 下载项目
          </button>
        </div>
      </div>

      {/* Main area */}
      <div className="flex flex-1 min-h-0">
        {/* File tree */}
        <div className="w-[220px] border-r border-[var(--border)] p-3 flex flex-col gap-1 overflow-y-auto shrink-0">
          <p className="text-xs font-medium text-[var(--text-tertiary)] uppercase tracking-wide mb-1">📄 源码</p>
          {starterFiles.map(([name]) => (
            <button
              key={name}
              onClick={() => setActiveFile(name)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm text-left transition-colors ${
                activeFile === name ? "bg-[var(--primary-light)] text-[var(--primary)] font-medium" : "text-[var(--text-secondary)] hover:bg-[var(--surface-alt)]"
              }`}
            >
              <FileCode size={14} /> {name}
            </button>
          ))}
          <p className="text-xs font-medium text-[var(--text-tertiary)] uppercase tracking-wide mt-3 mb-1">🧪 测试</p>
          {testFiles.map(([name]) => (
            <button
              key={name}
              onClick={() => setActiveFile(name)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm text-left transition-colors ${
                activeFile === name ? "bg-[var(--warning-light)] text-[var(--warning)] font-medium" : "text-[var(--text-secondary)] hover:bg-[var(--surface-alt)]"
              }`}
            >
              <TestTube size={14} /> {name}
            </button>
          ))}

          {/* Run instructions */}
          {lab.run_instructions && (
            <details className="mt-4">
              <summary className="text-xs font-medium text-[var(--text-tertiary)] cursor-pointer">运行说明</summary>
              <pre className="mt-2 text-xs bg-[var(--surface-alt)] p-2 rounded-lg whitespace-pre-wrap">{lab.run_instructions}</pre>
            </details>
          )}
        </div>

        {/* Editor */}
        <div className="flex-1 min-h-0">
          <Editor
            height="100%"
            language={monacoLang}
            value={currentCode}
            onChange={(value) => {
              if (!isReadOnly && value !== undefined) {
                setEditedCode((prev) => ({ ...prev, [activeFile]: value }));
              }
            }}
            options={{
              readOnly: isReadOnly,
              minimap: { enabled: false },
              fontSize: 14,
              lineNumbers: "on",
              scrollBeyondLastLine: false,
              wordWrap: "on",
              padding: { top: 16 },
            }}
            theme="vs-light"
          />
        </div>
      </div>

      {/* Bottom bar */}
      <div className="flex items-center justify-between px-6 py-3 border-t border-[var(--border)]">
        <button onClick={handleReset} className="btn-ghost flex items-center gap-1.5 text-sm text-[var(--error)]">
          <RotateCcw size={14} /> 重置代码
        </button>
        <button onClick={handleDownload} className="btn-primary text-sm">下载项目 ↓</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Rewrite Learn page**

Rewrite `frontend/src/app/learn/page.tsx` completely. The new page has:
- 3 tabs: 学习 / Lab / 图谱
- Learn tab: video (left 55%) + lesson (right 45%), lesson collapsible
- Lab tab: full-width LabEditor
- Graph tab: full-width ForceGraph
- AI Tutor: TutorDrawer overlay triggered by header button
- Translation preserved in lesson panel
- Video extracts bvid/ytid from `course.sources[].url` matching `section.source_id`
- Section.content.lesson used for LessonContent (not section.content directly)
- URL updates on section change
- Bottom nav: prev/next section
- Lesson read tracking: fire `recordProgress` after 30s or scroll to bottom

Key structural changes from current 712-line file:
- Remove `activeTab` states for "lesson"/"video"/"lab"/"tutor" → replace with "learn"/"lab"/"graph"
- Remove inline chat UI → replaced by TutorDrawer component
- Remove LabViewer usage → replaced by LabEditor component
- Video embed logic: use `course.sources` to find matching source by `section.source_id`
- `extractBvid`: match source URL for bilibili, extract BV ID
- `extractYoutubeId`: new function for YouTube URLs
- `isLessonContent` check: read from `section.content.lesson` property

This is a complete rewrite — write the full component (~400 lines) implementing all the above. Use the CSS classes from the design system (`.card`, `.btn-primary`, etc.).

- [ ] **Step 4: Verify build**

Run: `cd frontend && npm run build`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/learn/page.tsx frontend/src/components/tutor-drawer.tsx frontend/src/components/lab/lab-editor.tsx
git commit -m "feat: redesign learn page with video+lesson split, tutor drawer, lab editor, knowledge graph tab"
```

---

### Task 10: Dashboard — inline SRS review cards + progress on course cards

**Files:**
- Rewrite: `frontend/src/app/page.tsx`
- Create: `frontend/src/components/review-card.tsx`

- [ ] **Step 1: Create ReviewCard component**

Create `frontend/src/components/review-card.tsx` — a flip-card component:

```tsx
"use client";
import { useState } from "react";

interface ReviewCardProps {
  conceptName: string;
  question: string | null;
  answer: string | null;
  onRate: (quality: number) => void;
  disabled?: boolean;
}

export default function ReviewCard({ conceptName, question, answer, onRate, disabled }: ReviewCardProps) {
  const [flipped, setFlipped] = useState(false);

  return (
    <div
      className="w-[280px] h-[200px] shrink-0 cursor-pointer"
      style={{ perspective: "1000px" }}
      onClick={() => !flipped && setFlipped(true)}
    >
      <div
        className="relative w-full h-full transition-transform duration-500"
        style={{
          transformStyle: "preserve-3d",
          transform: flipped ? "rotateY(180deg)" : "rotateY(0)",
        }}
      >
        {/* Front */}
        <div className="absolute inset-0 card flex flex-col items-center justify-center text-center p-6" style={{ backfaceVisibility: "hidden" }}>
          <p className="text-xs text-[var(--text-tertiary)] mb-2">点击翻转</p>
          <p className="font-semibold text-lg mb-2">{conceptName}</p>
          <p className="text-sm text-[var(--text-secondary)]">{question ?? conceptName}</p>
        </div>

        {/* Back */}
        <div
          className="absolute inset-0 card flex flex-col items-center justify-between p-6"
          style={{ backfaceVisibility: "hidden", transform: "rotateY(180deg)" }}
        >
          <p className="text-sm text-[var(--text)] text-center flex-1 flex items-center">{answer ?? "暂无解析"}</p>
          <div className="flex gap-2 mt-3">
            {[
              { label: "忘了", quality: 1, color: "var(--error)" },
              { label: "模糊", quality: 3, color: "var(--warning)" },
              { label: "记得", quality: 4, color: "var(--success)" },
              { label: "简单", quality: 5, color: "var(--primary)" },
            ].map((btn) => (
              <button
                key={btn.quality}
                onClick={(e) => { e.stopPropagation(); onRate(btn.quality); }}
                disabled={disabled}
                className="px-3 py-1.5 rounded-full text-xs font-medium text-white transition-opacity"
                style={{ background: btn.color, opacity: disabled ? 0.5 : 1 }}
              >
                {btn.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Rewrite Dashboard page**

Rewrite `frontend/src/app/page.tsx` to include:
- Review section with horizontal scrolling ReviewCard components
- Course cards with progress bars (call `getCourseProgress` for each course)
- Active import tasks with stage progress
- Apple-style layout using `.card` CSS classes

Key changes:
- Add `getDueReviews()` call on mount
- Add `completeReview()` on card rate
- Add `getCourseProgress(course.id)` for each course to show completion ratio
- Remove hardcoded review stats display, replace with actual review UI

- [ ] **Step 3: Verify build**

Run: `cd frontend && npm run build`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/page.tsx frontend/src/components/review-card.tsx
git commit -m "feat: dashboard with inline SRS review cards and course progress bars"
```

---

### Task 11: Path page — fine-grained progress tracking

**Files:**
- Rewrite: `frontend/src/app/path/page.tsx`

- [ ] **Step 1: Rewrite Path page**

Rewrite `frontend/src/app/path/page.tsx` to include:
- Call `getCourseProgress(courseId)` alongside `getCourse(courseId)`
- Section cards with: title, status badge (✅/🔵/○), difficulty dots, concept tags
- Progress indicators per section: 📝 课文 (已读/未读), 🧪 Lab (完成/未完成), 📊 练习 (score %)
- Section click → `/learn?sectionId=...&courseId=...`
- Apple-style card layout

Key data joins:
- Match progress items to sections by `section_id`
- Status computed from progress data
- Lab existence: check `section.content.has_code` or check if lab exists (may need to add a `has_lab` field later, for now check section content)

- [ ] **Step 2: Verify build**

Run: `cd frontend && npm run build`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/path/page.tsx
git commit -m "feat: path page with fine-grained section progress tracking"
```

---

### Task 12: Exercise page fixes

**Files:**
- Modify: `frontend/src/app/exercise/page.tsx`

- [ ] **Step 1: Fix exercise data loading**

In `frontend/src/app/exercise/page.tsx`, the `getSectionExercises` call already maps `items` → `exercises` (from Task 8). Verify this works.

- [ ] **Step 2: Add Monaco editor for code exercises**

Replace the textarea for `type === "code"` with Monaco Editor:

```tsx
import Editor from "@monaco-editor/react";

// In the answer area section, when exercise.type === "code":
<Editor
  height="300px"
  language="python"
  value={textAnswer}
  onChange={(v) => setTextAnswer(v ?? "")}
  options={{ minimap: { enabled: false }, fontSize: 14, lineNumbers: "on" }}
  theme="vs-light"
/>
```

- [ ] **Step 3: Add explanation display**

After submission result, display `result.explanation` if present:

```tsx
{result.explanation && (
  <div className="mt-3 p-4 bg-[var(--surface-alt)] rounded-xl">
    <p className="text-sm font-medium text-[var(--text-secondary)] mb-1">解析</p>
    <p className="text-sm">{result.explanation}</p>
  </div>
)}
```

- [ ] **Step 4: Add completion summary**

Add state to accumulate results:
```tsx
const [results, setResults] = useState<Array<{ exerciseId: string; score: number | null }>>([]);
```

After last exercise submission, show summary card with overall score.

- [ ] **Step 5: Apply Apple styling**

Update all buttons to use `.btn-primary`, `.btn-secondary`, `.card` classes. Update option cards to use design system colors.

- [ ] **Step 6: Verify build**

Run: `cd frontend && npm run build`

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/exercise/page.tsx
git commit -m "feat: exercise page with Monaco for code, explanation display, completion summary, Apple styling"
```

---

## Phase 4: Polish & Verify

### Task 13: Update sidebar and layout for Apple style

**Files:**
- Modify: `frontend/src/components/sidebar.tsx`
- Modify: `frontend/src/app/layout.tsx`

- [ ] **Step 1: Update sidebar styling**

Apply Apple design tokens: use `var(--surface)` background, `var(--border)` borders, `var(--primary)` for active states, proper font sizes and spacing. Remove any hardcoded colors.

- [ ] **Step 2: Update layout**

Ensure `layout.tsx` uses `var(--bg)` for page background and proper padding.

- [ ] **Step 3: Verify build**

Run: `cd frontend && npm run build`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/sidebar.tsx frontend/src/app/layout.tsx
git commit -m "style: apply Apple design system to sidebar and root layout"
```

---

### Task 14: End-to-end build verification

- [ ] **Step 1: Run backend tests (unit tests that don't need DB)**

```bash
cd backend && .venv/bin/pytest --ignore=tests/test_smoke.py --ignore=tests/test_health.py --ignore=tests/test_memory.py --ignore=tests/test_cost_guard.py -v
```

Expected: All pass (these are LLM adapter, extractor, SM-2 tests).

- [ ] **Step 2: Run frontend build**

```bash
cd frontend && npm run build
```

Expected: No TypeScript errors, build succeeds.

- [ ] **Step 3: Run frontend lint**

```bash
cd frontend && npm run lint
```

Expected: No lint errors.

- [ ] **Step 4: Run frontend tests**

```bash
cd frontend && npm run test
```

Expected: Existing smoke tests may need updates due to page rewrites. Update mocks if needed.

- [ ] **Step 5: Final commit if any fixes**

```bash
git add -A && git commit -m "fix: resolve build and test issues from redesign"
```
