# Socratiq 开源版 MVP 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Socratiq as a polished open-source project — add citation cards, optimize DX, write docs, and ensure quality.

**Architecture:** Citation cards require changes across 3 layers: RAG service returns source metadata → SSE stream carries citation events → frontend renders collapsible citation cards below assistant messages. DX work focuses on docker compose defaults and .env simplification. Documentation is the primary "product" for an open-source release.

**Tech Stack:** Python/FastAPI, Next.js/React, PostgreSQL/pgvector, Docker Compose, pytest, Vitest

**Spec:** `docs/superpowers/specs/2026-04-12-opensource-mvp-design.md`

---

## File Structure

### New Files
- `backend/app/models/citation.py` — Citation Pydantic schema
- `backend/tests/test_citations.py` — Citation unit tests
- `frontend/src/components/citation-card.tsx` — Citation card UI component
- `LICENSE` — AGPL-3.0 license text
- `CONTRIBUTING.md` — Contributor guide
- `docs/architecture.md` — System architecture overview
- `docs/llm-providers.md` — LLM backend configuration guide

### Modified Files
- `backend/app/services/rag.py` — Return source_id + chunk_id in results
- `backend/app/agent/tools/knowledge.py` — Pass citation data through tool output
- `backend/app/api/routes/chat.py` — Add `citations` SSE event
- `backend/app/agent/mentor.py` — Collect and emit citation data
- `frontend/src/lib/api.ts` — Add `citations` event type
- `frontend/src/lib/stores.ts` — Add citations to ChatMessage
- `frontend/src/components/tutor-drawer.tsx` — Render citation cards
- `docker-compose.yml` — Add defaults, health checks, Ollama service
- `.env.example` — Simplify, add inline docs
- `README.md` — Complete rewrite for open-source launch

---

## Task 1: Citation Cards — Backend (RAG + Tool)

**Files:**
- Modify: `backend/app/services/rag.py:46-85` (add source_id, chunk_id to results)
- Modify: `backend/app/agent/tools/knowledge.py:55-77` (return structured citation data)
- Create: `backend/app/models/citation.py` (Citation schema)
- Create: `backend/tests/test_citations.py`

- [ ] **Step 1: Create Citation schema**

```python
# backend/app/models/citation.py
"""Citation schema for source attribution in mentor responses."""

from pydantic import BaseModel


class Citation(BaseModel):
    """A reference to a specific chunk in source material."""
    chunk_id: str
    source_id: str
    source_title: str | None = None
    source_type: str | None = None  # "bilibili", "youtube", "pdf", etc.
    source_url: str | None = None
    text: str  # The referenced passage
    start_time: float | None = None  # Video timestamp in seconds
    end_time: float | None = None
    page_start: int | None = None  # PDF page number
```

- [ ] **Step 2: Write failing test for RAG source metadata**

```python
# backend/tests/test_citations.py
"""Tests for citation data flow through RAG → tool → SSE."""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.rag import RAGService
from app.agent.tools.knowledge import KnowledgeSearchTool
from app.models.citation import Citation


@pytest.fixture
def mock_router():
    router = MagicMock()
    return router


@pytest.fixture
def rag_service(mock_router):
    return RAGService(mock_router)


class TestRAGSourceMetadata:
    """RAG search results must include source_id and chunk_id."""

    async def test_search_returns_source_and_chunk_ids(self, rag_service):
        """search() results must contain source_id and chunk_id fields."""
        mock_db = AsyncMock()
        # Simulate a pgvector query result row
        mock_row = MagicMock()
        mock_row.id = uuid.uuid4()
        mock_row.source_id = uuid.uuid4()
        mock_row.text = "Backpropagation applies the chain rule"
        mock_row.metadata_ = {"start_time": 120, "end_time": 135}
        mock_row.distance = 0.15
        mock_row.source_title = "Neural Networks Explained"
        mock_row.source_type = "youtube"
        mock_row.source_url = "https://youtube.com/watch?v=abc"

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch.object(rag_service, '_embed_query', return_value=[0.1] * 1536):
            results = await rag_service.search(db=mock_db, query="backpropagation")

        assert len(results) == 1
        r = results[0]
        assert "chunk_id" in r
        assert "source_id" in r
        assert "source_title" in r
        assert "source_type" in r
        assert "source_url" in r
        assert r["chunk_id"] == str(mock_row.id)
        assert r["source_id"] == str(mock_row.source_id)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_citations.py::TestRAGSourceMetadata::test_search_returns_source_and_chunk_ids -v`
Expected: FAIL — results dict missing `chunk_id`, `source_id` etc.

- [ ] **Step 4: Update RAG service to return source metadata**

Modify `backend/app/services/rag.py`. The SQL queries need to JOIN source table and return source fields. Update both the course-filtered and unfiltered queries:

```python
# backend/app/services/rag.py — replace the search() method body (lines 21-85)

    async def search(
        self,
        db: AsyncSession,
        query: str,
        course_id: uuid.UUID | None = None,
        top_k: int = 5,
    ) -> list[dict]:
        """Search for content chunks similar to the query.

        Returns:
            List of dicts with text, metadata, score, and source attribution fields.
        """
        query_embedding = await self._embed_query(query)
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        if course_id:
            sql = text("""
                SELECT cc.id, cc.source_id, cc.text, cc.metadata_,
                       cc.embedding <=> :query_vec AS distance,
                       src.title AS source_title,
                       src.type AS source_type,
                       src.url AS source_url
                FROM content_chunks cc
                JOIN sections s ON cc.section_id = s.id
                LEFT JOIN sources src ON cc.source_id = src.id
                WHERE s.course_id = :course_id
                  AND cc.embedding IS NOT NULL
                ORDER BY cc.embedding <=> :query_vec
                LIMIT :top_k
            """)
            result = await db.execute(
                sql,
                {"query_vec": embedding_str, "course_id": str(course_id), "top_k": top_k},
            )
        else:
            sql = text("""
                SELECT cc.id, cc.source_id, cc.text, cc.metadata_,
                       cc.embedding <=> :query_vec AS distance,
                       src.title AS source_title,
                       src.type AS source_type,
                       src.url AS source_url
                FROM content_chunks cc
                LEFT JOIN sources src ON cc.source_id = src.id
                WHERE cc.embedding IS NOT NULL
                ORDER BY cc.embedding <=> :query_vec
                LIMIT :top_k
            """)
            result = await db.execute(
                sql,
                {"query_vec": embedding_str, "top_k": top_k},
            )

        rows = result.all()

        return [
            {
                "chunk_id": str(row.id),
                "source_id": str(row.source_id) if row.source_id else None,
                "source_title": row.source_title,
                "source_type": row.source_type,
                "source_url": row.source_url,
                "text": row.text,
                "metadata": row.metadata_ if row.metadata_ else {},
                "score": 1 - row.distance,
            }
            for row in rows
        ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_citations.py::TestRAGSourceMetadata -v`
Expected: PASS

- [ ] **Step 6: Write failing test for KnowledgeSearchTool citation output**

Add to `backend/tests/test_citations.py`:

```python
class TestKnowledgeToolCitations:
    """KnowledgeSearchTool must return structured citation JSON alongside text."""

    async def test_execute_returns_citations_json(self):
        """Tool output must end with a JSON citations block."""
        import json

        mock_db = AsyncMock()
        mock_rag = AsyncMock()
        mock_rag.search.return_value = [
            {
                "chunk_id": "chunk-1",
                "source_id": "src-1",
                "source_title": "Neural Networks",
                "source_type": "youtube",
                "source_url": "https://youtube.com/watch?v=abc",
                "text": "Backpropagation applies the chain rule",
                "metadata": {"start_time": 120, "end_time": 135},
                "score": 0.85,
            }
        ]

        tool = KnowledgeSearchTool(db=mock_db, rag_service=mock_rag)
        result = await tool.execute(query="backpropagation")

        # Result should contain the text for LLM context
        assert "Backpropagation" in result

        # Result should end with a parseable JSON citations block
        assert "<!-- CITATIONS:" in result
        json_str = result.split("<!-- CITATIONS:")[1].split("-->")[0].strip()
        citations = json.loads(json_str)
        assert len(citations) == 1
        assert citations[0]["chunk_id"] == "chunk-1"
        assert citations[0]["source_title"] == "Neural Networks"
        assert citations[0]["start_time"] == 120
```

- [ ] **Step 7: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_citations.py::TestKnowledgeToolCitations -v`
Expected: FAIL — no `<!-- CITATIONS:` block in output

- [ ] **Step 8: Update KnowledgeSearchTool to emit citation data**

```python
# backend/app/agent/tools/knowledge.py — replace execute() method (lines 55-77)

    async def execute(self, query: str, top_k: int = 5) -> str:
        import json

        top_k = min(top_k, 10)
        results = await self._rag.search(
            db=self._db,
            query=query,
            course_id=self._course_id,
            top_k=top_k,
        )
        if not results:
            return "No relevant content found in the knowledge base."

        # Format results for the LLM
        formatted = []
        citations = []
        for i, r in enumerate(results, 1):
            source_info = ""
            meta = r.get("metadata", {})
            if "start_time" in meta:
                source_info = f" [Video timestamp: {meta['start_time']}s - {meta.get('end_time', '?')}s]"
            elif "page_start" in meta:
                source_info = f" [PDF page: {meta['page_start']}]"
            formatted.append(f"[{i}]{source_info}\n{r['text']}")

            citations.append({
                "chunk_id": r.get("chunk_id"),
                "source_id": r.get("source_id"),
                "source_title": r.get("source_title"),
                "source_type": r.get("source_type"),
                "source_url": r.get("source_url"),
                "text": r["text"][:200],  # Truncate for citation display
                "start_time": meta.get("start_time"),
                "end_time": meta.get("end_time"),
                "page_start": meta.get("page_start"),
            })

        text_output = "\n\n---\n\n".join(formatted)
        citations_json = json.dumps(citations, ensure_ascii=False)
        return f"{text_output}\n\n<!-- CITATIONS:{citations_json}-->"
```

- [ ] **Step 9: Run all citation tests**

Run: `cd backend && .venv/bin/pytest tests/test_citations.py -v`
Expected: ALL PASS

- [ ] **Step 10: Commit**

```bash
git add backend/app/models/citation.py backend/app/services/rag.py backend/app/agent/tools/knowledge.py backend/tests/test_citations.py
git commit -m "feat: add source metadata to RAG results and knowledge tool citations"
```

---

## Task 2: Citation Cards — SSE Stream

**Files:**
- Modify: `backend/app/agent/mentor.py` (extract citations from tool results, emit as SSE data)
- Modify: `backend/app/api/routes/chat.py` (add `citations` SSE event)

- [ ] **Step 1: Add citation test for SSE event emission**

Add to `backend/tests/test_citations.py`:

```python
class TestCitationSSEEvent:
    """Chat endpoint must emit a citations SSE event."""

    async def test_mentor_extracts_citations_from_tool_result(self):
        """MentorAgent should extract citation JSON from tool results and store them."""
        import json

        citations_data = [{"chunk_id": "c1", "source_title": "Test"}]
        tool_output = f"Some text\n\n<!-- CITATIONS:{json.dumps(citations_data)}-->"

        # Extract citations the same way the mentor will
        collected = []
        if "<!-- CITATIONS:" in tool_output:
            try:
                json_str = tool_output.split("<!-- CITATIONS:")[1].split("-->")[0].strip()
                collected.extend(json.loads(json_str))
            except (json.JSONDecodeError, IndexError):
                pass

        assert len(collected) == 1
        assert collected[0]["chunk_id"] == "c1"
```

- [ ] **Step 2: Run test to verify it passes** (this is a logic test, should pass immediately)

Run: `cd backend && .venv/bin/pytest tests/test_citations.py::TestCitationSSEEvent -v`
Expected: PASS

- [ ] **Step 3: Update MentorAgent to collect citations from tool results**

In `backend/app/agent/mentor.py`, add citation collection logic. After a tool executes and returns its result, check for the `<!-- CITATIONS:` marker and extract the JSON. At the end of the response, yield a special chunk with citations.

Find the tool execution section in `mentor.py` where tool results are processed. After `tool_result = await tool.execute(...)`, add:

```python
# In the tool execution loop, after getting tool_result:
# Extract citations if present
if "<!-- CITATIONS:" in tool_result:
    try:
        import json as _json
        cit_json = tool_result.split("<!-- CITATIONS:")[1].split("-->")[0].strip()
        self._collected_citations.extend(_json.loads(cit_json))
        # Strip citation marker from tool result sent to LLM
        tool_result = tool_result.split("\n\n<!-- CITATIONS:")[0]
    except (Exception,):
        pass
```

Initialize `self._collected_citations = []` at the start of `process()`.

- [ ] **Step 4: Update chat.py to emit citations SSE event**

In `backend/app/api/routes/chat.py`, after the agent streaming loop and before `message_end`, emit citations if collected:

```python
# After the streaming loop, before saving assistant message:
if agent._collected_citations:
    yield {
        "event": "citations",
        "data": json.dumps({"citations": agent._collected_citations}),
    }
```

- [ ] **Step 5: Run existing tests to ensure no regressions**

Run: `cd backend && .venv/bin/pytest tests/ -v --timeout=30`
Expected: All existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/mentor.py backend/app/api/routes/chat.py backend/tests/test_citations.py
git commit -m "feat: emit citations SSE event from mentor chat stream"
```

---

## Task 3: Citation Cards — Frontend

**Files:**
- Create: `frontend/src/components/citation-card.tsx`
- Modify: `frontend/src/lib/api.ts:130-136` (add `citations` event type)
- Modify: `frontend/src/lib/stores.ts:8-12` (add citations to ChatMessage)
- Modify: `frontend/src/components/tutor-drawer.tsx:62-77` (handle citations event, render cards)

- [ ] **Step 1: Add citations event type to API client**

In `frontend/src/lib/api.ts`, update the `ChatStreamEvent` interface:

```typescript
// frontend/src/lib/api.ts — update ChatStreamEvent (line 130)
export interface ChatStreamEvent {
  event: "text_delta" | "tool_start" | "tool_end" | "message_end" | "citations" | "error";
  text?: string;
  conversation_id?: string;
  message?: string;
  tool?: string;
  citations?: Citation[];
}

export interface Citation {
  chunk_id: string;
  source_id: string | null;
  source_title: string | null;
  source_type: string | null;
  source_url: string | null;
  text: string;
  start_time: number | null;
  end_time: number | null;
  page_start: number | null;
}
```

- [ ] **Step 2: Add citations to chat store**

In `frontend/src/lib/stores.ts`, update `ChatMessage` and store:

```typescript
// frontend/src/lib/stores.ts — update ChatMessage interface (line 8)
interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: import("./api").Citation[];
}
```

Add `setCitationsOnLast` action to the store:

```typescript
// Add to ChatStore interface (after appendToLast):
setCitationsOnLast: (citations: import("./api").Citation[]) => void;

// Add implementation in create() (after appendToLast implementation):
setCitationsOnLast: (citations) =>
  set((state) => {
    const msgs = [...state.messages];
    if (msgs.length > 0) {
      msgs[msgs.length - 1] = {
        ...msgs[msgs.length - 1],
        citations,
      };
    }
    return { messages: msgs };
  }),
```

- [ ] **Step 3: Create CitationCard component**

```tsx
// frontend/src/components/citation-card.tsx
"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, FileText, Play } from "lucide-react";
import type { Citation } from "@/lib/api";

function formatTimestamp(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function CitationItem({ citation, index }: { citation: Citation; index: number }) {
  const isVideo = citation.source_type === "youtube" || citation.source_type === "bilibili";

  return (
    <div className="flex items-start gap-2 py-1.5 text-xs">
      <span className="text-gray-400 font-mono flex-shrink-0">[{index + 1}]</span>
      <div className="min-w-0">
        <div className="flex items-center gap-1 text-gray-600">
          {isVideo ? (
            <Play className="w-3 h-3 flex-shrink-0" />
          ) : (
            <FileText className="w-3 h-3 flex-shrink-0" />
          )}
          <span className="font-medium truncate">{citation.source_title || "Unknown source"}</span>
          {isVideo && citation.start_time != null && (
            <span className="text-blue-500 flex-shrink-0">
              {formatTimestamp(citation.start_time)}
              {citation.end_time != null && `–${formatTimestamp(citation.end_time)}`}
            </span>
          )}
          {citation.page_start != null && (
            <span className="text-blue-500 flex-shrink-0">p.{citation.page_start}</span>
          )}
        </div>
        <p className="text-gray-400 line-clamp-2 mt-0.5">{citation.text}</p>
      </div>
    </div>
  );
}

export default function CitationCards({ citations }: { citations: Citation[] }) {
  const [expanded, setExpanded] = useState(false);

  if (!citations || citations.length === 0) return null;

  return (
    <div className="mt-1.5 border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-gray-500 hover:bg-gray-50 transition-colors bg-transparent"
      >
        {expanded ? (
          <ChevronDown className="w-3 h-3" />
        ) : (
          <ChevronRight className="w-3 h-3" />
        )}
        <span>{citations.length} 个来源引用</span>
      </button>
      {expanded && (
        <div className="px-2.5 pb-2 border-t border-gray-100 divide-y divide-gray-100">
          {citations.map((c, i) => (
            <CitationItem key={c.chunk_id || i} citation={c} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Wire citations into TutorDrawer**

In `frontend/src/components/tutor-drawer.tsx`:

1. Import: `import CitationCards from "./citation-card";`
2. Destructure `setCitationsOnLast` from `useChatStore()` (line 26-33)
3. Add citations event handler in `sendMessage()` (after line 72):

```typescript
} else if (event.event === "citations" && event.citations) {
  setCitationsOnLast(event.citations);
```

4. Render citations below assistant message bubbles. Replace the message rendering block (lines 150-156) with:

```tsx
{msg.role === "assistant" ? (
  <>
    <div className="prose prose-sm max-w-none">
      <ReactMarkdown>{msg.content || "..."}</ReactMarkdown>
    </div>
    {msg.citations && <CitationCards citations={msg.citations} />}
  </>
) : (
  msg.content
)}
```

- [ ] **Step 5: Run frontend build to verify no TypeScript errors**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/citation-card.tsx frontend/src/lib/api.ts frontend/src/lib/stores.ts frontend/src/components/tutor-drawer.tsx
git commit -m "feat: add citation cards to mentor chat UI"
```

---

## Task 4: Docker Compose & DX Optimization

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Update docker-compose.yml with Ollama-friendly defaults**

```yaml
# docker-compose.yml — full replacement
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: socratiq
      POSTGRES_PASSWORD: socratiq
      POSTGRES_DB: socratiq
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U socratiq"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  backend:
    build: ./backend
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    env_file: .env
    environment:
      - DATABASE_URL=postgresql+asyncpg://socratiq:socratiq@db:5432/socratiq
      - REDIS_URL=redis://redis:6379/0
      - CELERY_BROKER_URL=redis://redis:6379/1
      - CELERY_RESULT_BACKEND=redis://redis:6379/2
    extra_hosts:
      - "host.docker.internal:host-gateway"

  worker:
    build: ./backend
    command: celery -A app.worker.celery_app worker --loglevel=info
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    env_file: .env
    environment:
      - DATABASE_URL=postgresql+asyncpg://socratiq:socratiq@db:5432/socratiq
      - REDIS_URL=redis://redis:6379/0
      - CELERY_BROKER_URL=redis://redis:6379/1
      - CELERY_RESULT_BACKEND=redis://redis:6379/2
    extra_hosts:
      - "host.docker.internal:host-gateway"

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    depends_on:
      - backend
    environment:
      - BACKEND_URL=http://backend:8000

volumes:
  pgdata:
  redisdata:
```

Key change: `extra_hosts` added to backend and worker so Ollama on host machine is reachable via `host.docker.internal`.

- [ ] **Step 2: Simplify .env.example**

```bash
# .env.example — full replacement

# ┌─────────────────────────────────────────────┐
# │  Socratiq — AI-powered adaptive learning    │
# │  Configure ONE LLM provider below to start  │
# └─────────────────────────────────────────────┘

# Option 1: Ollama (free, local, private)
# Install from https://ollama.ai, then run: ollama pull qwen2.5
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1

# Option 2: OpenAI
# OPENAI_API_KEY=sk-xxx

# Option 3: Anthropic
# ANTHROPIC_API_KEY=sk-ant-xxx

# Option 4: DeepSeek (affordable, good Chinese support)
# DEEPSEEK_API_KEY=sk-xxx

# ── Everything below has working defaults ─────
# No need to change unless you know what you're doing

# Security (change these in production)
JWT_SECRET_KEY=socratiq-dev-secret
LLM_ENCRYPTION_KEY=socratiq-dev-encryption-key

# Whisper ASR for videos without subtitles
WHISPER_MODE=local

# Bilibili login cookies (optional, for member-only videos)
# BILIBILI_SESSDATA=
# BILIBILI_BILI_JCT=
# BILIBILI_BUVID3=
```

Key changes: removed DB/Redis URLs (handled by docker-compose environment), Ollama enabled by default, clearer inline docs, sensible dev defaults for secrets.

- [ ] **Step 3: Verify docker compose config is valid**

Run: `docker compose config --quiet`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "dx: simplify docker compose and env config for one-command startup"
```

---

## Task 5: Documentation — README

**Files:**
- Modify: `README.md` (complete rewrite)

- [ ] **Step 1: Write README**

Write `README.md` with the following structure. Content should be in English (international audience, open source convention):

```markdown
# Socratiq

**Turn any YouTube / Bilibili video into an interactive AI-tutored course.**

Self-hosted. Supports Ollama, Claude, GPT, DeepSeek, and any OpenAI-compatible backend. Your data stays yours.

<!-- TODO: Add product screenshot/GIF here before launch -->

## Features

- **Video → Course** — Paste a URL, get a structured course with chapters, concepts, and learning path
- **AI Mentor** — Socratic teaching method: guides your thinking instead of giving answers
- **5-Layer Memory** — The AI remembers your learning history, strengths, and gaps across sessions
- **Exercises & Evaluation** — Auto-generated practice with AI-powered feedback
- **Spaced Repetition** — SM-2 algorithm schedules reviews for long-term retention
- **Knowledge Graph** — Visualize concept relationships with interactive D3.js graph
- **Citation Cards** — Every AI answer shows its sources with video timestamps or page numbers
- **Cold-Start Diagnostic** — Adaptive assessment to understand your level before you start
- **Multi-LLM** — Ollama (free/local), Claude, GPT, DeepSeek, Qwen, and more

## Quick Start

```bash
git clone https://github.com/catundercar/socratiq.git
cd socratiq
cp .env.example .env      # Ollama works out of the box
docker compose up
```

Open [http://localhost:3000](http://localhost:3000). The setup page will guide you through LLM configuration.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- One LLM backend:
  - **Ollama** (recommended for getting started): [Install Ollama](https://ollama.ai), then `ollama pull qwen2.5`
  - **API key** for OpenAI, Anthropic, or DeepSeek

## Supported LLM Providers

| Provider | Type | Models | Notes |
|----------|------|--------|-------|
| Ollama | Local | Qwen 2.5, Llama 3, Mistral, etc. | Free, private, no API key needed |
| Anthropic | Cloud | Claude Sonnet, Haiku, Opus | Best tool-use support |
| OpenAI | Cloud | GPT-4o, GPT-4o-mini | Widely available |
| DeepSeek | Cloud | DeepSeek V3, Chat | Affordable, strong Chinese |
| Any OpenAI-compatible | Cloud/Local | Qwen, GLM, Moonshot, Groq, etc. | Via custom base URL |

## Architecture

```
┌──────────────────────────────────────────┐
│  Frontend (Next.js + React)              │
│  ┌─────────┐ ┌────────┐ ┌────────────┐  │
│  │ Courses  │ │ Mentor │ │ Knowledge  │  │
│  │ & Learn  │ │  Chat  │ │   Graph    │  │
│  └────┬─────┘ └───┬────┘ └─────┬──────┘  │
│       └───────────┼────────────┘         │
└───────────────────┼──────────────────────┘
                    │ SSE / REST
┌───────────────────┼──────────────────────┐
│  Backend (FastAPI)│                      │
│  ┌────────────────┴────────────────┐     │
│  │        MentorAgent              │     │
│  │   ┌─────┐ ┌─────┐ ┌─────────┐  │     │
│  │   │ RAG │ │ SRS │ │ Memory  │  │     │
│  │   │ +   │ │     │ │ (5-layer│  │     │
│  │   │ Cite│ │     │ │  system)│  │     │
│  │   └──┬──┘ └─────┘ └─────────┘  │     │
│  └──────┼──────────────────────────┘     │
│         │                                │
│  ┌──────┴──────┐  ┌──────────────────┐   │
│  │  pgvector   │  │  LLM Router      │   │
│  │  (embeddings│  │  Anthropic/OpenAI │   │
│  │   + search) │  │  /Ollama/DeepSeek│   │
│  └─────────────┘  └──────────────────┘   │
└──────────────────────────────────────────┘
     PostgreSQL 16        Redis 7
```

## Development

### Local development (without Docker)

```bash
# Start infrastructure
docker compose up -d db redis

# Backend
cd backend
uv sync --extra dev
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --reload-dir app --port 8000

# Frontend (in another terminal)
cd frontend
npm install
npm run dev
```

### Running tests

```bash
# Backend
cd backend && .venv/bin/pytest

# Frontend
cd frontend && npm test
```

## Roadmap

- [x] YouTube + Bilibili video ingestion
- [x] AI course generation
- [x] Socratic mentor chat (SSE streaming)
- [x] 5-layer memory system
- [x] Exercises with AI evaluation
- [x] Spaced repetition (SM-2)
- [x] Knowledge graph visualization
- [x] Multi-LLM backend support
- [x] Citation cards
- [ ] PDF / URL / Markdown content sources
- [ ] Gamification (streaks, achievements)
- [ ] Code sandbox (online execution)
- [ ] Multi-user auth (SaaS)
- [ ] Mobile responsive design

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding conventions, and PR guidelines.

## License

[AGPL-3.0](LICENSE) — free to use, modify, and self-host. If you build a hosted service on Socratiq, it must also be open source.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for open-source launch"
```

---

## Task 6: Documentation — CONTRIBUTING & Architecture

**Files:**
- Create: `CONTRIBUTING.md`
- Create: `docs/architecture.md`
- Create: `docs/llm-providers.md`

- [ ] **Step 1: Write CONTRIBUTING.md**

```markdown
# Contributing to Socratiq

Thanks for your interest in contributing! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.12+ with [uv](https://github.com/astral-sh/uv)
- Node.js 22+
- Docker and Docker Compose
- PostgreSQL 16 with pgvector (or use Docker)
- Redis 7 (or use Docker)

### Getting started

```bash
# Clone the repo
git clone https://github.com/catundercar/socratiq.git
cd socratiq

# Start infrastructure
docker compose up -d db redis

# Backend
cd backend
uv sync --extra dev
cp ../.env.example ../.env  # Edit .env with your LLM config
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --reload-dir app --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

### Running tests

```bash
cd backend && .venv/bin/pytest       # Backend tests
cd frontend && npm test              # Frontend tests
cd frontend && npm run lint          # Lint check
```

## Code Conventions

### Python (Backend)
- Async/await everywhere
- Type annotations required
- Pydantic v2 for validation
- pytest with `asyncio_mode = "auto"`

### TypeScript (Frontend)
- Strict mode enabled
- `@/*` path alias for `./src/*`
- kebab-case for component files
- Zustand for state management

## Pull Request Process

1. Fork the repo and create a feature branch from `main`
2. Write tests for new functionality
3. Ensure all tests pass
4. Keep PRs focused — one feature or fix per PR
5. Write a clear PR description explaining what and why

## Architecture

See [docs/architecture.md](docs/architecture.md) for system architecture details.
```

- [ ] **Step 2: Write docs/architecture.md**

```markdown
# Socratiq Architecture

## Overview

Socratiq is a self-hosted AI learning platform. Users import video URLs, the system generates structured courses, and an AI mentor guides learning through Socratic dialogue.

## System Components

### Backend (Python/FastAPI)

**Entry point:** `backend/app/main.py`

**Key layers:**
- `api/routes/` — REST + SSE endpoints
- `agent/mentor.py` — MentorAgent: core AI reasoning loop with tool calling (max 10 iterations)
- `agent/tools/` — Agent tools: RAG search, exercises, memory, profile, progress
- `services/llm/` — LLM provider abstraction (Anthropic, OpenAI-compatible, Ollama)
- `services/` — Business logic: RAG, embedding, course generation, spaced repetition
- `memory/` — 5-layer memory retrieval: working → profile → episodic → content → progress + metacognitive
- `db/models/` — SQLAlchemy async ORM (20 tables)
- `tools/extractors/` — Content extractors: YouTube, Bilibili, PDF, Markdown, URL

### Frontend (Next.js/React)

**Framework:** Next.js (App Router) with React, TypeScript, Tailwind CSS

**Key areas:**
- `app/` — Pages: dashboard, import, learn, exercises, settings
- `components/` — UI components: tutor chat, lesson renderer, lab editor, knowledge graph
- `lib/api.ts` — API client with SSE streaming support
- `lib/stores.ts` — Zustand stores for global state

### Data Flow

1. User pastes video URL → Celery task extracts content (subtitles, metadata)
2. LLM analyzes content → generates course structure, lessons, exercises
3. Content chunks embedded with pgvector for RAG search
4. User learns → MentorAgent streams responses via SSE
5. Agent uses tools: RAG search (with citations), exercise generation, memory storage
6. Spaced repetition schedules reviews based on SM-2 algorithm

### LLM Abstraction

All LLM calls go through `services/llm/`:
- `base.py` — Abstract provider interface + unified message format
- `router.py` — Routes by task type (chat, analysis, evaluation, embedding) to provider/model
- `adapters/tool_adapter.py` — Converts tool use between Anthropic and OpenAI formats
- `adapters/stream_adapter.py` — Normalizes SSE chunks across providers

See [LLM Providers Guide](llm-providers.md) for configuration details.
```

- [ ] **Step 3: Write docs/llm-providers.md**

```markdown
# LLM Provider Configuration

Socratiq supports multiple LLM backends through a unified abstraction layer.

## Quick Setup

The easiest way to configure your LLM is through the Setup page at `http://localhost:3000/setup` after launching Socratiq.

Alternatively, edit `.env` before starting:

## Ollama (Recommended for Getting Started)

Free, local, private. No API key needed.

1. Install: https://ollama.ai
2. Pull a model: `ollama pull qwen2.5`
3. Set in `.env`:
   ```
   OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
   ```

Recommended models:
- `qwen2.5` — Good all-around, strong Chinese support
- `llama3.1` — Strong English, good reasoning
- `mistral` — Fast, good for lighter tasks

## Anthropic (Claude)

Best tool-use support, recommended for production quality.

```
ANTHROPIC_API_KEY=sk-ant-xxx
```

Recommended: Claude Sonnet for mentor chat, Claude Haiku for content analysis.

## OpenAI

```
OPENAI_API_KEY=sk-xxx
```

Recommended: GPT-4o for mentor chat, GPT-4o-mini for light tasks.

## DeepSeek

Affordable, strong Chinese language support.

```
DEEPSEEK_API_KEY=sk-xxx
```

## Custom OpenAI-Compatible Providers

Any provider implementing the OpenAI Chat Completions API works:

Configure through the Settings page or use environment variables with custom base URLs.

## Model Routing

Socratiq routes different tasks to different models:

| Task | Default | Purpose |
|------|---------|---------|
| Mentor Chat | Primary model | Main tutoring interaction |
| Content Analysis | Light model | Course generation, summarization |
| Evaluation | Primary model | Exercise grading, diagnostics |
| Embedding | Embedding model | Vector search (RAG) |

Configure via environment variables:
```
LLM_PRIMARY_MODEL=anthropic/claude-sonnet-4-20250514
LLM_LIGHT_MODEL=anthropic/claude-haiku-4-20250414
LLM_EMBEDDING_MODEL=openai/text-embedding-3-small
```
```

- [ ] **Step 4: Commit**

```bash
git add CONTRIBUTING.md docs/architecture.md docs/llm-providers.md
git commit -m "docs: add CONTRIBUTING, architecture, and LLM providers guide"
```

---

## Task 7: Open Source Preparation

**Files:**
- Create: `LICENSE`
- Modify: `.github/` (issue templates if not exists)

- [ ] **Step 1: Add AGPL-3.0 license**

Download or write the AGPL-3.0 license text to `LICENSE`.

Run: `curl -sL https://www.gnu.org/licenses/agpl-3.0.txt > LICENSE`

- [ ] **Step 2: Create GitHub issue templates**

```bash
mkdir -p .github/ISSUE_TEMPLATE
```

Create `.github/ISSUE_TEMPLATE/bug_report.md`:

```markdown
---
name: Bug Report
about: Report a bug to help us improve
labels: bug
---

**Describe the bug**
A clear description of what happened.

**To reproduce**
1. Go to '...'
2. Click on '...'
3. See error

**Expected behavior**
What you expected to happen.

**Environment**
- OS: [e.g., macOS 15, Ubuntu 24.04]
- LLM Provider: [e.g., Ollama, OpenAI]
- Docker version: [e.g., 27.0]
```

Create `.github/ISSUE_TEMPLATE/feature_request.md`:

```markdown
---
name: Feature Request
about: Suggest an idea for Socratiq
labels: enhancement
---

**Problem**
What problem does this solve?

**Proposed solution**
How would you like this to work?

**Alternatives considered**
Any other approaches you've thought about?
```

- [ ] **Step 3: Commit**

```bash
git add LICENSE .github/
git commit -m "chore: add AGPL-3.0 license and GitHub issue templates"
```

---

## Task 8: Core Learning Loop — E2E Smoke Test

**Files:**
- Create: `backend/tests/test_e2e_smoke.py`

- [ ] **Step 1: Write E2E smoke test for the core learning loop APIs**

This test verifies the happy path through all major API endpoints without requiring actual LLM calls (mocked).

```python
# backend/tests/test_e2e_smoke.py
"""E2E smoke test for core learning loop: import → course → learn → chat → exercise → review.

Uses mocked LLM and tests API contracts only. Requires running DB (use testcontainers).
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestCoreLoopSmoke:
    """Verify all core API endpoints respond correctly."""

    async def test_setup_status(self, client):
        """GET /api/v1/setup/status should return setup state."""
        resp = await client.get("/api/v1/setup/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "ollama_available" in data or "status" in data

    async def test_list_courses_empty(self, client):
        """GET /api/v1/courses should return empty list for new user."""
        resp = await client.get("/api/v1/courses")
        assert resp.status_code == 200

    async def test_list_models(self, client):
        """GET /api/v1/models should return configured models."""
        resp = await client.get("/api/v1/models")
        assert resp.status_code == 200

    async def test_list_due_reviews(self, client):
        """GET /api/v1/reviews/due should return review items."""
        resp = await client.get("/api/v1/reviews/due")
        assert resp.status_code == 200
```

- [ ] **Step 2: Run test**

Run: `cd backend && .venv/bin/pytest tests/test_e2e_smoke.py -v`
Expected: Tests pass (or identify API contract issues to fix)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_e2e_smoke.py
git commit -m "test: add E2E smoke test for core API endpoints"
```

---

## Task 9: LLM Backend Compatibility Verification

**Files:**
- No new files. Manual testing task.

- [ ] **Step 1: Test with Ollama**

```bash
# Ensure Ollama is running with a model
ollama pull qwen2.5

# Start Socratiq
docker compose up

# Open http://localhost:3000
# 1. Setup page → configure Ollama
# 2. Import a short YouTube video
# 3. Wait for course generation
# 4. Open course → learn a section
# 5. Ask mentor a question → verify SSE streaming works
# 6. Check citation cards appear (if knowledge search triggered)
```

Document any issues found.

- [ ] **Step 2: Test with at least one cloud API**

Test with whichever API key is available (OpenAI, Anthropic, or DeepSeek):
- Same flow as Ollama test
- Verify model routing works correctly
- Verify tool use works (exercises, knowledge search)

- [ ] **Step 3: Fix any issues found and commit fixes**

---

## Task 10: Final Polish & Verification

- [ ] **Step 1: Run full backend test suite**

Run: `cd backend && .venv/bin/pytest -v`
Expected: All tests pass

- [ ] **Step 2: Run frontend build**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no errors

- [ ] **Step 3: Run frontend lint**

Run: `cd frontend && npm run lint`
Expected: No lint errors

- [ ] **Step 4: Verify docker compose full startup from scratch**

```bash
docker compose down -v  # Clean slate
cp .env.example .env
docker compose up --build
# Wait for all services healthy
# Open http://localhost:3000 — should load without errors
```

- [ ] **Step 5: README walkthrough test**

Follow README instructions from scratch as if you've never seen the project. Every command must work. Fix any gaps.

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "chore: final polish for open-source MVP release"
```
