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
