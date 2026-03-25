# Sub-project C: MentorAgent Core + Frontend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the MentorAgent AI agent core (backend) and the Next.js frontend — the user-facing layers of LearnMentor.

**Architecture:** MentorAgent agent loop with tool_use (knowledge RAG, profile, progress tools) → SSE streaming via FastAPI → Next.js App Router frontend with Zustand state + shadcn/ui components.

**Tech Stack:** Python 3.12+ · FastAPI · sse-starlette · pgvector | Next.js 14+ · TypeScript · Tailwind CSS · shadcn/ui · Zustand · eventsource-parser

**Design Spec:** `docs/superpowers/specs/2026-03-24-subproject-c-agent-frontend-design.md`

**Project Conventions:** `CLAUDE.md`

---

## Pre-requisites

Before starting, verify Sub-project A (and ideally B) is in place:

```bash
cd backend && .venv/bin/python -m pytest -v  # All existing tests pass
.venv/bin/python -c "from app.main import app; print('FastAPI OK')"
.venv/bin/python -c "from app.services.llm.router import ModelRouter, TaskType; print('LLM OK')"
.venv/bin/python -c "from app.db.models.user import User; print('User model OK')"
.venv/bin/python -c "from app.db.models.conversation import Conversation; print('Conversation model OK')"
.venv/bin/python -c "from app.db.models.message import Message; print('Message model OK')"
.venv/bin/python -c "from app.db.models.content_chunk import ContentChunk; print('ContentChunk model OK')"
```

---

## Task 1: Agent Directory Structure + AgentTool Base

**Files:**
- Create: `backend/app/agent/__init__.py`
- Create: `backend/app/agent/tools/__init__.py`
- Create: `backend/app/agent/tools/base.py`
- Create: `backend/app/agent/prompts/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p backend/app/agent/tools
mkdir -p backend/app/agent/prompts
touch backend/app/agent/__init__.py
touch backend/app/agent/tools/__init__.py
touch backend/app/agent/prompts/__init__.py
```

- [ ] **Step 2: Implement AgentTool base class**

Create `backend/app/agent/tools/base.py` from design spec Section 2.1 (`AgentTool` ABC):
- Abstract properties: `name`, `description`, `parameters`
- Abstract method: `execute(**params) -> str`
- Concrete method: `to_tool_definition()` → `ToolDefinition`

- [ ] **Step 3: Verify import**

```bash
cd backend
.venv/bin/python -c "from app.agent.tools.base import AgentTool; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/agent/
git commit -m "feat(agent): add agent directory structure and AgentTool abstract base class"
```

---

## Task 2: StudentProfile Service

**Files:**
- Create: `backend/app/services/profile.py`
- Create: `backend/tests/services/test_profile.py`

- [ ] **Step 1: Write profile service tests (TDD)**

Create `backend/tests/services/test_profile.py`. Test cases:
1. `test_student_profile_defaults` — verify default values for all fields
2. `test_load_profile_empty` — returns default `StudentProfile` when user has no profile
3. `test_load_profile_existing` — returns populated `StudentProfile` from JSONB
4. `test_save_profile` — writes profile to `users.student_profile`
5. `test_apply_profile_updates_valid` — parse LLM JSON, apply updates
6. `test_apply_profile_updates_invalid_json` — handle gracefully

Mock DB session.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
.venv/bin/python -m pytest tests/services/test_profile.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement profile service**

Create `backend/app/services/profile.py` from design spec Section 2.4. Include:
- Pydantic models: `LearningStyle`, `Competency`, `LearningHistory`, `MentorStrategy`, `StudentProfile`
- `load_profile(db, user_id)` — load from `users.student_profile` JSONB
- `save_profile(db, user_id, profile)` — write to DB
- `apply_profile_updates(db, user_id, llm_response_text)` — parse LLM JSON and merge

- [ ] **Step 4: Run tests**

```bash
cd backend
.venv/bin/python -m pytest tests/services/test_profile.py -v
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/profile.py backend/tests/services/test_profile.py
git commit -m "feat(agent): implement StudentProfile model and DB operations"
```

---

## Task 3: Agent Tools (Knowledge + Profile + Progress)

**Files:**
- Create: `backend/app/agent/tools/knowledge.py`
- Create: `backend/app/agent/tools/profile.py`
- Create: `backend/app/agent/tools/progress.py`
- Create: `backend/tests/agent/__init__.py`
- Create: `backend/tests/agent/test_tools.py`

- [ ] **Step 1: Write agent tools tests (TDD)**

Create `backend/tests/agent/test_tools.py`. Test cases:
1. `test_knowledge_tool_properties` — name, description, parameters schema
2. `test_knowledge_tool_execute` — mock RAG service, verify formatted results
3. `test_knowledge_tool_no_results` — verify "No relevant content" message
4. `test_profile_read_tool_all` — returns full profile JSON
5. `test_profile_read_tool_section` — returns specific section
6. `test_progress_tool_record` — creates learning record
7. `test_progress_tool_query` — returns formatted records
8. `test_tool_to_tool_definition` — verifies ToolDefinition conversion

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
.venv/bin/python -m pytest tests/agent/test_tools.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement KnowledgeSearchTool**

Create `backend/app/agent/tools/knowledge.py` from design spec Section 2.2.1.

- [ ] **Step 4: Implement ProfileReadTool**

Create `backend/app/agent/tools/profile.py` from design spec Section 2.2.2.

- [ ] **Step 5: Implement ProgressTrackTool**

Create `backend/app/agent/tools/progress.py` from design spec Section 2.2.3.

- [ ] **Step 6: Run tests**

```bash
cd backend
.venv/bin/python -m pytest tests/agent/test_tools.py -v
```
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/agent/tools/ backend/tests/agent/
git commit -m "feat(agent): implement Knowledge, Profile, and Progress agent tools"
```

---

## Task 4: System Prompt Template

**Files:**
- Create: `backend/app/agent/prompts/mentor.py`
- Create: `backend/tests/agent/test_prompts.py`

- [ ] **Step 1: Write prompt tests (TDD)**

Create `backend/tests/agent/test_prompts.py`. Test cases:
1. `test_build_system_prompt_default` — verify prompt string contains key sections
2. `test_build_system_prompt_with_profile` — verify profile data injected
3. `test_build_system_prompt_chinese` — verify Chinese content present

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
.venv/bin/python -m pytest tests/agent/test_prompts.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement build_system_prompt**

Create `backend/app/agent/prompts/mentor.py` from design spec Section 2.3.

- [ ] **Step 4: Run tests**

```bash
cd backend
.venv/bin/python -m pytest tests/agent/test_prompts.py -v
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/prompts/ backend/tests/agent/test_prompts.py
git commit -m "feat(agent): implement system prompt template with profile injection"
```

---

## Task 5: MentorAgent Core Loop

**Files:**
- Create: `backend/app/agent/mentor.py`
- Create: `backend/tests/agent/test_mentor.py`

- [ ] **Step 1: Write MentorAgent tests (TDD)**

Create `backend/tests/agent/test_mentor.py`. Test cases:
1. `test_process_simple_message` — mock LLM streams text-only, verify StreamChunks yielded
2. `test_process_with_tool_call` — mock LLM returns tool_use, verify tool executed and result sent back
3. `test_process_max_loops` — verify safety limit prevents infinite loops
4. `test_process_triggers_profile_update` — verify async profile update task created
5. `test_tool_execution_error` — verify graceful error handling when tool fails

Mock `ModelRouter`, `LLMProvider.chat_stream()`, all tools.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
.venv/bin/python -m pytest tests/agent/test_mentor.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement MentorAgent**

Create `backend/app/agent/mentor.py` from design spec Section 2.1. Key:
- `process(user_message, conversation_history, course_id)` async generator
- Agent loop: stream LLM → detect tool_use → execute → loop
- Text deltas yielded immediately for SSE
- Async profile update via `asyncio.create_task`

- [ ] **Step 4: Run tests**

```bash
cd backend
.venv/bin/python -m pytest tests/agent/test_mentor.py -v
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/mentor.py backend/tests/agent/test_mentor.py
git commit -m "feat(agent): implement MentorAgent core loop with tool use and streaming"
```

---

## Task 6: RAG Service

**Files:**
- Create: `backend/app/services/rag.py`
- Create: `backend/tests/services/test_rag.py`

- [ ] **Step 1: Write RAG service tests (TDD)**

Create `backend/tests/services/test_rag.py`. Test cases:
1. `test_search_returns_results` — mock embedding + DB query, verify results
2. `test_search_empty_results` — verify empty list for no matches
3. `test_search_with_course_filter` — verify course_id filter applied
4. `test_search_top_k_limit` — verify result count respects top_k

Mock `ModelRouter.get_provider(TaskType.EMBEDDING)` and DB session.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
.venv/bin/python -m pytest tests/services/test_rag.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement RAGService**

Create `backend/app/services/rag.py` from design spec Section 2.5. Include:
- `RAGService` class with `search(query, course_id, top_k)` method
- Compute query embedding via `ModelRouter.get_provider(TaskType.EMBEDDING)`
- pgvector cosine similarity search on `content_chunks.embedding`
- Format results with metadata (timestamps, page numbers)

- [ ] **Step 4: Run tests**

```bash
cd backend
.venv/bin/python -m pytest tests/services/test_rag.py -v
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rag.py backend/tests/services/test_rag.py
git commit -m "feat(agent): implement RAG service with pgvector cosine similarity search"
```

---

## Task 7: Chat API Schemas + Routes

**Files:**
- Create: `backend/app/models/chat.py`
- Create: `backend/app/api/routes/chat.py`
- Create: `backend/tests/api/test_chat.py`

- [ ] **Step 1: Create chat Pydantic schemas**

Create `backend/app/models/chat.py` from design spec. Include:
- `ChatRequest(BaseModel)` — message, conversation_id (optional), course_id (optional)
- `ConversationResponse(BaseModel)` — id, title, created_at, message_count
- `MessageResponse(BaseModel)` — id, role, content, created_at

- [ ] **Step 2: Write chat API tests (TDD)**

Create `backend/tests/api/test_chat.py`. Test cases:
1. `test_chat_endpoint_creates_conversation` — POST /api/chat without conversation_id
2. `test_chat_endpoint_existing_conversation` — POST with conversation_id
3. `test_list_conversations` — GET /api/conversations
4. `test_get_conversation_messages` — GET /api/conversations/{id}/messages
5. `test_chat_sse_content_type` — verify `text/event-stream` response

Mock MentorAgent and DB.

- [ ] **Step 3: Run test to verify it fails**

```bash
cd backend
.venv/bin/python -m pytest tests/api/test_chat.py -v
```
Expected: FAIL

- [ ] **Step 4: Implement chat routes**

Create `backend/app/api/routes/chat.py` from design spec Section 2.6. Endpoints:
- `POST /api/chat` — SSE streaming response via MentorAgent.process()
- `GET /api/conversations` — list conversations
- `GET /api/conversations/{id}/messages` — get conversation messages

Use `sse-starlette` for SSE response.

- [ ] **Step 5: Run tests**

```bash
cd backend
.venv/bin/python -m pytest tests/api/test_chat.py -v
```
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/chat.py backend/app/api/routes/chat.py backend/tests/api/test_chat.py
git commit -m "feat(agent): implement Chat SSE API with conversation CRUD"
```

---

## Task 8: Courses API (Read-Only for C)

**Files:**
- Create: `backend/app/api/routes/courses.py` (if not created by Sub-project B)
- Create: `backend/tests/api/test_courses.py`

> **Note:** If Sub-project B already created `courses.py`, only add the read endpoints here. If B is not done, create the full file with read-only endpoints.

- [ ] **Step 1: Write courses API tests**

Create `backend/tests/api/test_courses.py`. Test cases:
1. `test_list_courses` — GET /api/courses returns list
2. `test_get_course_with_sections` — GET /api/courses/{id} returns course with sections

- [ ] **Step 2: Implement courses read routes**

Endpoints:
- `GET /api/courses` — list courses for user
- `GET /api/courses/{id}` — get course with sections

- [ ] **Step 3: Run tests**

```bash
cd backend
.venv/bin/python -m pytest tests/api/test_courses.py -v
```
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/routes/courses.py backend/tests/api/test_courses.py
git commit -m "feat(agent): add read-only courses API for frontend"
```

---

## Task 9: Register Backend Routers + Add Dependencies

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Register routers**

Add to `backend/app/main.py`:
```python
from app.api.routes import chat
app.include_router(chat.router, prefix="/api")
# courses router may already be registered by Sub-project B
```

- [ ] **Step 2: Add sse-starlette dependency**

Add to `backend/pyproject.toml`:
```
"sse-starlette",
"numpy",
```

- [ ] **Step 3: Install and verify**

```bash
cd backend
uv pip install -e .
.venv/bin/python -c "from app.main import app; print('OK')"
```

- [ ] **Step 4: Run full backend tests**

```bash
cd backend
.venv/bin/python -m pytest -v --tb=short
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/pyproject.toml
git commit -m "feat(agent): register chat router and add SSE dependencies"
```

---

## Task 10: Next.js Frontend Skeleton

**Files:**
- Create: Full Next.js project in `frontend/`

- [ ] **Step 1: Initialize Next.js project**

```bash
cd /path/to/learnmentor
npx create-next-app@latest frontend --typescript --tailwind --eslint --app --src-dir=false --import-alias="@/*" --use-npm
```

- [ ] **Step 2: Install dependencies**

```bash
cd frontend
npm install zustand eventsource-parser react-markdown remark-gfm
npx shadcn@latest init
npx shadcn@latest add button input card dialog scroll-area badge tabs separator skeleton avatar dropdown-menu sheet textarea toast
```

- [ ] **Step 3: Verify build**

```bash
cd frontend
npm run build
```
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): initialize Next.js project with shadcn/ui and dependencies"
```

---

## Task 11: Frontend Core Files (API Client + SSE + Stores)

**Files:**
- Create: `frontend/lib/api.ts`
- Create: `frontend/lib/sse.ts`
- Create: `frontend/lib/stores/chat-store.ts`
- Create: `frontend/lib/stores/course-store.ts`

- [ ] **Step 1: Implement API client**

Create `frontend/lib/api.ts` from design spec Section 3.3. Backend API fetch wrapper with:
- `API_BASE_URL` configuration
- Generic `apiGet()`, `apiPost()` functions
- Error handling

- [ ] **Step 2: Implement SSE helper**

Create `frontend/lib/sse.ts` from design spec Section 3.4. SSE streaming helper with:
- `streamChat(message, conversationId, callbacks)` function
- Uses `eventsource-parser` for POST-based SSE
- Callbacks: `onTextDelta`, `onMessageEnd`, `onError`

- [ ] **Step 3: Implement Zustand stores**

Create `frontend/lib/stores/chat-store.ts` and `frontend/lib/stores/course-store.ts` from design spec Section 3.5.

- [ ] **Step 4: Verify build**

```bash
cd frontend && npm run build
```
Expected: Build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/
git commit -m "feat(frontend): implement API client, SSE helper, and Zustand stores"
```

---

## Task 12: Frontend Layout (Sidebar + Header + Dashboard)

**Files:**
- Modify: `frontend/app/layout.tsx`
- Modify: `frontend/app/globals.css`
- Create: `frontend/components/layout/sidebar.tsx`
- Create: `frontend/components/layout/header.tsx`
- Modify: `frontend/app/page.tsx`

- [ ] **Step 1: Update root layout**

Update `frontend/app/layout.tsx` with dark theme, Inter font from design spec Section 3.2.

- [ ] **Step 2: Update global CSS**

Update `frontend/app/globals.css` with Tailwind + shadcn CSS variables (dark palette).

- [ ] **Step 3: Create sidebar navigation**

Create `frontend/components/layout/sidebar.tsx` from design spec Section 3.7.4. Navigation items:
- Dashboard
- Import
- Courses
- Settings

- [ ] **Step 4: Create header bar**

Create `frontend/components/layout/header.tsx`.

- [ ] **Step 5: Create dashboard page**

Update `frontend/app/page.tsx` as dashboard with course overview.

- [ ] **Step 6: Verify**

```bash
cd frontend && npm run build
npm run dev  # Open http://localhost:3000 — sidebar + dashboard visible
```

- [ ] **Step 7: Commit**

```bash
git add frontend/app/ frontend/components/layout/
git commit -m "feat(frontend): implement app layout with sidebar, header, and dashboard"
```

---

## Task 13: Import Page

**Files:**
- Create: `frontend/app/import/page.tsx`
- Create: `frontend/components/import/import-form.tsx`

- [ ] **Step 1: Create import form component**

Create `frontend/components/import/import-form.tsx` from design spec Section 3.6.2. Features:
- URL input tab (Bilibili URL)
- PDF upload tab (file drag & drop)
- Submit button → calls POST /api/sources
- Status polling display

- [ ] **Step 2: Create import page**

Create `frontend/app/import/page.tsx` using the import form component.

- [ ] **Step 3: Verify**

```bash
cd frontend && npm run build
```
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/import/ frontend/components/import/
git commit -m "feat(frontend): implement import page with URL and PDF upload forms"
```

---

## Task 14: Course Pages

**Files:**
- Create: `frontend/app/courses/[id]/page.tsx`
- Create: `frontend/components/course/course-card.tsx`
- Create: `frontend/components/course/section-list.tsx`

- [ ] **Step 1: Create course card component**

Create `frontend/components/course/course-card.tsx` — card display for course overview.

- [ ] **Step 2: Create section list component**

Create `frontend/components/course/section-list.tsx` — ordered list of sections with difficulty/status.

- [ ] **Step 3: Create course detail page**

Create `frontend/app/courses/[id]/page.tsx` from design spec Section 3.6.3.

- [ ] **Step 4: Update dashboard to show courses**

Update dashboard page to display course cards linking to course detail.

- [ ] **Step 5: Verify**

```bash
cd frontend && npm run build
```
Expected: Build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/app/courses/ frontend/components/course/
git commit -m "feat(frontend): implement course detail page with section list"
```

---

## Task 15: Learning Page + Mentor Chat Panel

**Files:**
- Create: `frontend/app/learn/[sectionId]/page.tsx`
- Create: `frontend/components/mentor-chat/chat-panel.tsx`
- Create: `frontend/components/mentor-chat/message-bubble.tsx`
- Create: `frontend/components/mentor-chat/chat-input.tsx`
- Create: `frontend/components/mentor-chat/streaming-text.tsx`

- [ ] **Step 1: Create message bubble component**

Create `frontend/components/mentor-chat/message-bubble.tsx` from design spec Section 3.7.2.
- Markdown rendering with `react-markdown`
- Different styles for user/assistant/tool messages

- [ ] **Step 2: Create chat input component**

Create `frontend/components/mentor-chat/chat-input.tsx` — textarea + send button.

- [ ] **Step 3: Create streaming text component**

Create `frontend/components/mentor-chat/streaming-text.tsx` — displays text with streaming cursor.

- [ ] **Step 4: Create chat panel**

Create `frontend/components/mentor-chat/chat-panel.tsx` from design spec Section 3.7.1.
- Uses chat store for state
- SSE streaming integration
- Auto-scroll to bottom
- Message list + input

- [ ] **Step 5: Create learning page**

Create `frontend/app/learn/[sectionId]/page.tsx` from design spec Section 3.6.4.
- Two-panel layout: content (left) + chat (right)
- Content panel: Bilibili player or PDF viewer depending on source type

- [ ] **Step 6: Verify**

```bash
cd frontend && npm run build
```
Expected: Build succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/app/learn/ frontend/components/mentor-chat/
git commit -m "feat(frontend): implement learning page with mentor chat panel and SSE streaming"
```

---

## Task 16: Video Player + PDF Viewer

**Files:**
- Create: `frontend/components/video-player/bilibili-player.tsx`
- Create: `frontend/components/pdf-viewer/pdf-viewer.tsx`

- [ ] **Step 1: Create Bilibili player component**

Create `frontend/components/video-player/bilibili-player.tsx` from design spec Section 3.7.3.
- iframe embed with `//player.bilibili.com/player.html?bvid=...`
- Responsive sizing

- [ ] **Step 2: Create PDF viewer component**

Create `frontend/components/pdf-viewer/pdf-viewer.tsx` — iframe-based PDF display.

- [ ] **Step 3: Verify**

```bash
cd frontend && npm run build
```
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/video-player/ frontend/components/pdf-viewer/
git commit -m "feat(frontend): implement Bilibili player and PDF viewer components"
```

---

## Task 17: Settings Page

**Files:**
- Create: `frontend/app/settings/page.tsx`

- [ ] **Step 1: Create settings page**

Create `frontend/app/settings/page.tsx` from design spec Section 3.6.5.
- Model configuration UI
- Student profile display/edit
- Provider settings

- [ ] **Step 2: Verify**

```bash
cd frontend && npm run build
```
Expected: Build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/settings/
git commit -m "feat(frontend): implement settings page with model configuration UI"
```

---

## Task 18: Full Verification

- [ ] **Step 1: Run all backend tests**

```bash
cd backend
.venv/bin/python -m pytest -v --tb=short
```
Expected: All tests pass.

- [ ] **Step 2: Build frontend**

```bash
cd frontend && npm run build
```
Expected: No errors.

- [ ] **Step 3: Integration smoke test**

```bash
# Terminal 1: Start backend
cd backend && .venv/bin/uvicorn app.main:app --reload

# Terminal 2: Start frontend
cd frontend && npm run dev

# Browser: Open http://localhost:3000
# Verify: Sidebar navigation, dashboard, import page, settings page render
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(agent+frontend): complete Sub-project C — MentorAgent core + Next.js frontend"
```
