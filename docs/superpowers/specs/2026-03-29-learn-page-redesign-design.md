# Socratiq Learn Experience Redesign — Design Spec

## Overview

Redesign the single-course learning experience to fix broken data flows and deliver a cohesive, Apple-style UI. Covers: Learn page (core), Lab, Dashboard (with inline SRS review), Path (with progress tracking), Exercise, and Knowledge Graph.

## Scope

### In Scope
- Learn page: video + lesson split layout, collapsible lesson, AI tutor drawer
- Lab tab: Monaco editor with file tree, editable starter code, read-only tests
- Knowledge graph tab: mount existing D3 force-graph component
- Dashboard: inline spaced repetition review cards
- Path page: fine-grained progress tracking per section
- Exercise page: field alignment fix, code syntax highlighting
- Fix broken data flows: section.content parsing, video embed (Bilibili + YouTube), exercise explanation field
- Apple.com visual style system
- Responsive design (desktop / tablet / mobile)

### Out of Scope
- Diagnostic assessment (deferred)
- Welcome / Login pages (deferred)
- Online code execution sandbox
- Dark mode
- Auth/JWT frontend integration
- Video watch progress tracking (iframe cross-origin restrictions make Bilibili/YouTube progress unreliable — defer to v2)

---

## 1. Learn Page

### 1.1 Layout Structure

Three tabs at top: **学习 (Learn)** | **Lab** | **图谱 (Graph)**

Default tab is Learn, which is a left-right split:

- **Left panel (55% desktop)**: Video player (16:9, fixed height)
  - Bilibili: iframe embed, bvid extracted from `Source.url` (not `section.source_start`)
  - YouTube: iframe embed, video ID extracted from `Source.url`
  - Fallback: placeholder with "无视频" message
- **Right panel (45% desktop)**: Lesson content, scrollable
  - Section title
  - LessonContent rendered via LessonRenderer: prose, code blocks, Mermaid diagrams, timestamp links, key concept badges, interactive steps
  - Collapse button at bottom: "收起课文 ▲"

**Collapsed state**: Video expands to full width. A floating pill button "展开课文" appears at bottom-right.

**AI Tutor**: Floating button (fixed, top-right of header). Clicking opens a right-side drawer (~400px wide) that **overlays** the content area as a z-index layer with semi-transparent backdrop. On the Learn tab this means the drawer covers the lesson panel (acceptable — the user is switching context to chat). Contains chat UI with message history, input field, quick prompts. Available across all tabs. Drawer slides in with `ease-out 0.25s`.

**Section navigation**: Bottom bar with "上一节 / 下一节" buttons.

**Header**: Back button, course title, progress indicator ("3/12"), tutor button.

### 1.2 Data Flow Fixes

**Critical fix — section.content parsing**:
- Current: frontend checks `isLessonContent(section.content)` at top level → always fails
- Fix option A (recommended): Frontend reads `section.content.lesson` instead of `section.content` directly
- Fix option B: Backend flattens — stores LessonContent at top level of section.content
- Decision: **Option A** — less disruptive, preserves existing metadata (summary, key_terms, has_code) alongside lesson

**Critical fix — video embed**:
- Current: `extractBvid()` reads from `section.source_start` (contains timestamps like "123s") and `course.source_ids[0]` (UUID)
- Fix: Replace `source_ids: list[UUID]` with `sources: list[SourceSummary]` in `CourseDetailResponse`
- New Pydantic model:
  ```python
  class SourceSummary(BaseModel):
      id: uuid.UUID
      url: str | None = None
      type: str  # "bilibili" | "youtube" | "pdf" | ...
  ```
- Backend: `GET /api/v1/courses/{id}` joins CourseSource → Source to return `sources` list
- Frontend: each Section has `source_id` (already in DB model but not in SectionResponse). Add `source_id` to `SectionResponse`. Frontend resolves video URL by matching `section.source_id` against `course.sources[]`. This correctly handles multi-source courses (e.g., Bilibili video + PDF).

**New — YouTube embed**:
- Detect YouTube URL → extract video ID via regex (`/(?:v=|\/embed\/|youtu\.be\/)([^&?#]+)/`)
- Render `<iframe src="https://www.youtube.com/embed/{videoId}?start={timestamp}" ...>`
- Same position as Bilibili iframe, selected based on `source.type`

**Translation feature**: The existing section translation UI (estimate cost → translate) is preserved within the lesson panel as a button/toggle above the lesson content.

### 1.3 Responsive Behavior

- **Desktop (≥1024px)**: Left-right split, 55/45
- **Tablet (768–1024px)**: Left-right split, 50/50
- **Mobile (<768px)**: Vertical stack — video on top (sticky), lesson below (default collapsed). Tutor drawer becomes full-screen sheet from bottom.

---

## 2. Lab Tab

Activated by clicking "Lab" tab. Replaces the learn split-view with a full-width lab environment.

### 2.1 Layout

- **Top bar**: Lab title, AI confidence badge (e.g., "信心度 85%"), download button
- **Description**: Lab description text below title
- **Main area — left-right split**:
  - Left (220px fixed): File tree
    - Grouped: 📄 Source files (editable) / 🧪 Test files (read-only)
    - Click to switch editor content
  - Right (flex): Monaco editor
    - Starter code files: editable, TODO comments highlighted with yellow background
    - Test code files: read-only, grey background tint
- **Bottom bar**: "重置代码" (reset to original, with confirmation dialog) | "下载项目 ↓" (ZIP of current edited state)
- **Run instructions**: Collapsible block in left panel below file tree

### 2.2 State Management

- Edited code stored in component state (not persisted to backend)
- Reset restores original `lab.starter_code` values
- Download bundles: current editor state (starter) + original test code + README with run_instructions

### 2.3 Responsive

- **Desktop**: File tree sidebar + editor
- **Mobile**: File tree becomes horizontal tab bar at top, editor full-width below

---

## 3. Knowledge Graph Tab

Activated by clicking "图谱" tab. Replaces the learn split-view with full-width D3 visualization.

### 3.1 Layout

- Full content area rendered by existing `ForceGraph` component
- Calls `getKnowledgeGraph(courseId)` on tab activation (lazy load)
- Loading state: centered spinner while fetching
- Error state: "知识图谱加载失败" with retry button
- Empty state: "完成练习后将生成知识图谱" (mastery data requires exercise submissions)
- Nodes colored by mastery: green (≥0.7), yellow (≥0.3), red (<0.3)
- Interactive: draggable nodes, hover tooltips showing concept name + mastery percentage

### 3.2 Integration

- Import existing `frontend/src/components/knowledge-graph/force-graph.tsx`
- Pass `courseId` from Learn page context
- No backend changes needed — endpoint already exists

---

## 4. AI Tutor Drawer

### 4.1 Behavior

- Trigger: floating button, always visible (fixed position in header)
- Opens: right-side drawer, 400px wide on desktop, full-screen sheet on mobile
- Backdrop: semi-transparent dark overlay, click to close
- Persists across tab switches (Learn / Lab / Graph)
- Chat state maintained via Zustand `useChatStore`

### 4.2 UI

- Message list (scrollable, auto-scroll to bottom)
- Quick prompt chips: "解释这个概念", "举个例子", "我不理解"
- Text input + send button
- Streaming: SSE text_delta rendered incrementally
- Tool use indicators: "正在搜索知识库..." during tool_start/tool_end

### 4.3 Context Awareness

- `streamChat()` should pass both `courseId` AND `sectionId` to the backend so the tutor can reference the specific lesson being viewed
- Backend: add optional `section_id` parameter to the chat endpoint request body
- Agent uses section context to narrow RAG search and provide section-specific guidance

---

## 5. Dashboard

### 5.1 Layout (top to bottom)

1. **Header**: App name + "导入新资料" button
2. **Review card** (conditional — only if `due_today > 0`):
   - Title: "今日复习" with count
   - Horizontal scrolling concept cards
   - Card front: concept name + hint question
   - Card back: answer/explanation
   - Rating buttons: 忘了(quality=1) / 模糊(3) / 记得(4) / 简单(5)
   - On all complete: card collapses to "今日复习完成 ✓"
3. **Course grid**: Cards with title, description, progress bar, section count
4. **Active imports**: Task cards with stage label + progress bar

### 5.2 Review Data Flow

- On mount: call `getReviewStats()` and `getDueReviews()`
- Each review card maps to a `ReviewItem` (concept + review metadata)
- On rate: call `completeReview(reviewId, quality)` → animate card away → next card

**Backend change needed**: Enrich `GET /api/v1/reviews/due` response:
- Join ReviewItem → Concept to add `concept_name: str` and `concept_description: str`
- Join ReviewItem → Exercise (if linked) to add `review_question: str` and `review_answer: str`
- Fallback if no linked exercise: card front shows `concept_name`, card back shows `concept_description`
- New response shape per item:
  ```json
  {
    "id": "uuid",
    "concept_name": "useEffect",
    "review_question": "What happens when...",
    "review_answer": "The effect runs after...",
    "easiness": 2.5,
    "interval_days": 6,
    "repetitions": 3,
    "review_at": "2026-03-29T00:00:00Z"
  }
  ```

### 5.3 Course Cards

- Show actual progress: completed sections / total sections
- Progress bar color: blue fill
- Click → navigate to `/path?courseId={id}`

---

## 6. Path Page (Course Outline)

### 6.1 Layout

- Header: back button, course title, description
- Section list: ordered cards

### 6.2 Section Card Content

Each card shows:
- Section number + title
- Status badge: ✅ 已完成 / 🔵 进行中 / ○ 未开始
- Difficulty dots (1-5)
- Concept tags (from section.content.key_terms or concepts)
- Progress indicators:
  - 📝 课文: 已读 / 未读
  - 🧪 Lab: 完成 / 未完成 (hidden if no lab)
  - 📊 练习: best score % (or "--")

Note: Video watch progress is out of scope (iframe cross-origin limitations). Video indicator omitted.

### 6.3 Status Logic

- **未开始**: All sub-indicators are zero/unstarted
- **进行中**: At least one sub-indicator has progress
- **已完成**: Lesson read + exercise score ≥ 60%

### 6.4 Backend Changes Needed

**New table: `section_progress`**

```python
class SectionProgress(Base):
    id: UUID (PK)
    user_id: UUID (FK → users)
    section_id: UUID (FK → sections)
    lesson_read: bool = False
    lab_completed: bool = False
    exercise_best_score: float | None = None
    updated_at: datetime

    # Unique constraint: (user_id, section_id)
```

**New endpoints:**

- `GET /api/v1/courses/{course_id}/progress` → returns list of `SectionProgressResponse` for current user
  ```json
  [
    {
      "section_id": "uuid",
      "lesson_read": true,
      "lab_completed": false,
      "exercise_best_score": 0.85,
      "status": "in_progress"
    }
  ]
  ```
  Status is computed server-side from the fields above.

- `POST /api/v1/sections/{section_id}/progress` → upsert progress event
  Request body: `{ "event": "lesson_read" | "lab_completed" }`
  Exercise score is auto-updated when submitting exercises (no separate call needed).

**Frontend triggers:**
- `lesson_read`: fire when user scrolls to bottom of lesson content, or after 30s on the lesson panel
- `lab_completed`: fire when user clicks "下载项目" (implies they're done editing)

---

## 7. Exercise Page

### 7.1 Layout (mostly unchanged)

- Header: back button, section title, question counter, progress bar
- Question card: type badge, difficulty, question text
- Answer area: MCQ option cards / Monaco editor (code) / textarea (open)
- Submit button
- Feedback card (after submission): score, feedback text, explanation
- Bottom nav: prev / next

### 7.2 Fixes Needed

**Backend — add explanation to submit response**:
- Current `SubmitAnswerResponse` lacks `explanation`
- Add `explanation: str | None` field, populated from `Exercise.explanation` after submission
- Frontend type `SubmissionResult.explanation` should be `string | null` (currently `string`, will show `undefined` if backend returns null)
- This is the "why this is correct" text, only revealed after answering

**Backend — fix exercise list response shape**:
- Frontend `getSectionExercises()` expects `{ exercises: ExerciseResponse[] }`
- Backend returns `{ items: [...], total: int }` via `ExerciseListResponse`
- Fix: Either change backend to return `exercises` key, or update frontend to read `items` key
- Decision: **Update frontend** — use `data.items` to match existing `ExerciseListResponse` pattern

**Frontend — code exercises**:
- Replace textarea with Monaco editor for `type === "code"`
- Language hint from exercise metadata or section context

**Frontend — completion summary**:
- Accumulate per-question results in component state (array of `{exerciseId, score, feedback}`)
- After last question: show summary card with total score, per-question breakdown
- "返回课程大纲" button → `/path?courseId={id}`

---

## 8. Visual Design System (Apple Style)

### Colors
- Background: `#FAFAFA` (page), `#FFFFFF` (cards)
- Text: `#1D1D1F` (primary), `#6E6E73` (secondary), `#86868B` (tertiary)
- Accent: `#0071E3` (links, primary buttons, active states)
- Success: `#34C759`, Error: `#FF3B30`, Warning: `#FF9500`
- Borders: `rgba(0,0,0,0.08)` — used sparingly

### Typography
- Font stack: `-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", system-ui, sans-serif`
- Page title: 36px / semibold
- Section title: 28px / semibold
- Card title: 20px / semibold
- Body: 17px / regular, line-height 1.6
- Caption: 14px / regular, color secondary

### Spacing
- Page padding: 48px horizontal (desktop), 24px (mobile)
- Section gap: 48–64px
- Card padding: 24–32px
- Element gap within cards: 16px

### Components
- Card: 16px border-radius, shadow `0 2px 12px rgba(0,0,0,0.06)`, hover shadow `0 4px 20px rgba(0,0,0,0.1)` + `translateY(-2px)`
- Button (primary): pill shape, 12px radius, `#0071E3` fill, white text
- Button (secondary): 12px radius, 1px border `rgba(0,0,0,0.15)`, transparent fill
- Button (ghost): no border, text only, hover background `rgba(0,0,0,0.04)`
- Input: 10px radius, 1px border, focus ring `#0071E3`
- Badge/tag: 8px radius, light tinted background + matching text color

### Animation
- All transitions: `ease-out 0.3s`
- Drawer slide-in: `ease-out 0.25s`
- Card hover: `transform: translateY(-2px)` + shadow deepen
- Tab switch: crossfade 0.2s
- Review card flip: 3D rotate Y-axis 0.4s

### Dark Mode
- Not in scope. Light theme only.

---

## 9. Backend Changes Summary

| Change | File(s) | Description |
|--------|---------|-------------|
| New `SourceSummary` model | `models/course.py` | `SourceSummary(id, url, type)` Pydantic model |
| Fix CourseDetailResponse | `models/course.py`, `routes/courses.py` | Replace `source_ids` with `sources: list[SourceSummary]`, add `source_id` to `SectionResponse` |
| Add explanation to submit | `routes/exercises.py` | Add `explanation: str \| None` to `SubmitAnswerResponse`, populate from Exercise model |
| Add chat section context | `routes/chat.py` | Add optional `section_id` parameter to chat request |
| New SectionProgress table | `db/models/section_progress.py` | `(user_id, section_id, lesson_read, lab_completed, exercise_best_score)` |
| New migration | `alembic/versions/` | Migration for `section_progress` table |
| Progress endpoints | `routes/courses.py` or new route | `GET /courses/{id}/progress` + `POST /sections/{id}/progress` |
| Review due enrichment | `routes/reviews.py` | Join Concept + Exercise to return `concept_name`, `review_question`, `review_answer` |
| Auto-update exercise score | `routes/exercises.py` | After exercise submit, upsert best score into `section_progress` |

---

## 10. Frontend Changes Summary

| Change | File(s) | Description |
|--------|---------|-------------|
| Learn page redesign | `app/learn/page.tsx` | Replace 4-tab layout with split view + drawer + 3 tabs (Learn/Lab/Graph) |
| Fix lesson parsing | `app/learn/page.tsx` | Read `section.content.lesson` instead of `section.content` |
| Fix video embed | `app/learn/page.tsx` | Extract bvid/ytid from `course.sources[].url`, add YouTube iframe |
| Preserve translation | `app/learn/page.tsx` | Keep translation toggle in lesson panel |
| Lab tab | `app/learn/page.tsx`, new `components/lab/lab-editor.tsx` | Monaco editor with file tree, client-side ZIP via JSZip |
| Knowledge graph tab | `app/learn/page.tsx` | Mount existing ForceGraph with loading/error/empty states |
| Tutor drawer | New `components/tutor-drawer.tsx` | Right-side overlay drawer with chat UI, passes sectionId |
| Dashboard review | `app/page.tsx`, new `components/review-card.tsx` | Inline flip-card SRS review |
| Path progress | `app/path/page.tsx` | Fine-grained section progress display |
| Fix exercise list | `app/exercise/page.tsx`, `lib/api.ts` | Read `data.items` instead of `data.exercises` |
| Fix exercise types | `lib/api.ts` | `SubmissionResult.explanation: string \| null` |
| Exercise completion | `app/exercise/page.tsx` | Accumulate results, show summary card |
| Code exercise editor | `app/exercise/page.tsx` | Monaco editor for `type === "code"` |
| Visual system | `app/globals.css`, Tailwind theme extend | Apple design tokens as CSS custom properties |
| Section navigation | `app/learn/page.tsx` | URL updates on section change for back-button support |
