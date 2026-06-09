# Architecture

Socratiq is a four-process system. Three of them are stateless (frontend, backend API, worker) and the fourth (Postgres) is the source of truth. Redis is the only piece of "in-flight" state and only Celery touches it directly.

```
┌──────────────┐   HTTPS/SSE   ┌──────────────┐   gRPC/HTTP   ┌──────────────┐
│  Browser     │ ────────────► │  Next.js     │ ────────────► │  FastAPI     │
│  (Next 16)   │ ◄──────────── │  dev/prod    │ ◄──────────── │  backend     │
└──────────────┘               └──────┬───────┘               └──────┬───────┘
                                      │                              │
                                      │ proxy /api/v1/*              │ SQLAlchemy (async)
                                      ▼                              ▼
                               app/api/[...path]                ┌──────────────┐
                                 route.ts                        │  Postgres 16 │
                                                                 │  + pgvector  │
                                                                 └──────┬───────┘
                                                                        ▲
   ┌──────────────┐    Celery (Redis)     ┌──────────────┐              │
   │  Worker      │ ◄──────────────────── │  backend     │              │
   │  (Celery)    │ ─────────────────────►│  enqueues    │              │
   └──────┬───────┘                       └──────────────┘              │
          │ writes results                                              │
          └──────────────────────────────────────────────────────────────┘
```

`docker-compose.yml` wires this up. In production the backend container also runs `alembic upgrade head` before booting.

## Process responsibilities

| Process | Image / module | Owns |
|---|---|---|
| `frontend` | `frontend/` · Next.js 16 | HTML, JS bundle, client-side state, **proxy route** `app/api/[...path]/route.ts` (10-min timeout for slow LLM streaming). No direct DB access. |
| `backend` | `backend/app/main.py` · FastAPI | All HTTP routes under `/api/v1/*`, request validation (Pydantic v2), SSE streaming, agent orchestration, business logic. |
| `worker` | `backend/app/worker/arq_app.py` (ARQ `WorkerSettings`) + `worker/tasks/*` | Long-running tasks: source ingestion, course assembly, course regeneration, async exercise generation. Same Python codebase as backend; different entrypoint. |
| `db` | `pgvector/pgvector:pg16` | Source of truth. Schemas in `backend/app/db/models/*.py`, migrations in `backend/alembic/versions/`. |
| `redis` | `redis:7-alpine` | Celery broker + result backend. Nothing else. |
| `minio` | `minio/minio` | Object storage (PDFs, uploaded files). Optional in dev. |

The backend pod can't talk to the worker process directly. They communicate **only through Postgres and Redis**:
- Backend enqueues a Celery task → Redis → Worker dequeues.
- Worker writes progress into `source_tasks` table → Backend reads on next poll → Frontend sees the new state.

This is intentional. It means cancelling a task = setting `status="cancelled"` on the DB row, not signalling the worker.

## Agent collaboration pattern

The agent layer lives at `backend/app/agent/`. Only one entrypoint is exposed to the user: `MentorAgent`. Specialists are tools the mentor calls.

```
                  user message ──► MentorAgent.process()
                                       │
                       ┌───────────────┼───────────────────┐
                       │               │                   │
                       ▼               ▼                   ▼
              KnowledgeSearchTool  ExerciseGenerateTool   EpisodicMemoryTool
              ProgressTrackTool    ExerciseEvalTool       MetacognitiveReflectTool
              ProfileReadTool
                       │
                       └─► tools return UnifiedMessage[] back into the loop
```

The mentor runs a standard tool-use loop (`while finish_reason != "stop": call provider → execute tool calls → append result → loop`). The loop is in `MentorAgent.process()` (`backend/app/agent/mentor.py:55`).

The `LessonAgent` / `LabAgent` / `EvalAgent` referenced in the original PRD are not separate agents in code — they're services (`lesson_generator.py`, `lab_generator.py`, `course_generator.py`) the worker calls during course assembly. They don't run tool-use loops; they're one-shot LLM calls with structured Pydantic outputs.

## Frontend ↔ backend boundary

The frontend makes requests like `/api/v1/courses`. These hit the Next route handler at `frontend/src/app/api/[...path]/route.ts`, which proxies to `BACKEND_URL` (defaults to `http://localhost:8000` outside docker, `http://backend:8000` inside the compose network).

The proxy exists because:
1. **Timeouts**: Next.js dev's default 1-min fetch timeout truncates Ollama-backed exercise generation. The route handler sets 10-min.
2. **Single-origin**: the browser only talks to `same-origin /api/...`, sidestepping CORS in dev and in prod alike.
3. **Future auth**: planned per-request injection of auth headers will happen here.

The frontend type definitions for every endpoint live in `frontend/src/lib/api.ts`. Add a new endpoint there (`async function getX(): Promise<XResponse>`) and import it from any component — never call `fetch` directly from a component.

## Five-layer memory

The PRD's "5-layer memory" lives in `backend/app/memory/manager.py`. The layers:

| Layer | Where | What |
|---|---|---|
| Working memory | in-process | the current `process()` invocation's message list |
| Student profile | `users.profile` (JSONB) | long-term traits, learning style, declared goals |
| Episodic | `episodic_memory` table | discrete dialogue snippets the mentor chose to remember |
| Progress | `section_progress`, `exercise_submissions`, `review_items` | what the user has read, attempted, mastered |
| Metacognitive | `metacognitive_records` | the mentor's notes about *its own* teaching choices |

Each layer is exposed to the mentor as a tool (see `backend/app/agent/tools/`). The mentor decides which to consult per turn.

## Adjacent docs

- [Content pipeline](./content-pipeline.md) — what happens when you paste a URL
- [Concepts & knowledge graph](./concepts-and-graph.md) — concept extraction details
- [LLM abstraction layer](./llm-layer.md) — how providers swap without code change
- [Data model](./data-model.md) — every Postgres table and what writes to it
