# Socratiq Wiki

Socratiq is a local-first, AI-driven learning platform. It turns long-form sources (B站/YouTube videos, PDFs, Markdown, plain notes) into Socratic learning paths: each source is decomposed into concepts and chunks, then assembled into a structured course with lessons, labs, exercises, and an always-available Socratic mentor.

The product thesis: **not a tool, a tutor**. A persistent student profile, any-content ingestion, dialogue-driven teaching, active knowledge exploration.

## Read in this order

A new engineer can be productive after reading these in sequence:

1. [Architecture](./architecture.md) — system map, where each component lives, agent collaboration
2. [Content pipeline](./content-pipeline.md) — what happens between "user pasted a URL" and "course is ready"
3. [Concepts & knowledge graph](./concepts-and-graph.md) — concept extraction, dedup, embeddings, mastery, graph endpoint
4. [LLM abstraction layer](./llm-layer.md) — provider-agnostic `UnifiedMessage` / `ModelRouter` / tool-use adapter
5. [Data model](./data-model.md) — Postgres tables grouped by domain
6. [Design system](./design-system.md) — tokens, fonts, icons, dark mode, density, i18n
7. [Frontend layout](./frontend-layout.md) — routes + sidebar + Learn shell + page-by-page

## What's in this repo

```
backend/        Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy (async) · Celery
frontend/      Next.js 16 · React 19 · TypeScript · Tailwind v4 · shadcn primitives
docker-compose.yml   Postgres 16 + pgvector · Redis 7 · MinIO · backend · worker · frontend
docs/wiki/    This wiki
```

The project ships as `docker compose up`. The frontend dev server can be run locally outside docker for HMR — see Dev quickstart below.

## Dev quickstart

```bash
# everything via docker
docker compose up -d db redis           # start the data plane only
docker compose up                        # full stack
./start.sh                                # convenience script (DB + backend + frontend)

# frontend hot-reload outside docker (run after docker compose up -d db redis backend)
cd frontend
npm install
npm run dev                              # localhost:3000, HMR on
# LAN: add -- -H 0.0.0.0 -p 3000

# backend hot-reload outside docker
cd backend
uv sync
uvicorn app.main:app --reload --reload-dir app --port 8000

# backend tests
cd backend && pytest                     # asyncio_mode = auto, no pytest.mark needed
cd backend && pytest tests/test_xxx.py   # single file
cd backend && pytest -k name             # match by name

# frontend tests
cd frontend && npm test                  # vitest run

# ARQ worker (required for async tasks: ingest, course/lesson generation).
# Without it, every import sits in "排队中" forever.
cd backend && arq app.worker.arq_app.WorkerSettings

# DB migrations
cd backend && alembic upgrade head
cd backend && alembic revision --autogenerate -m "what changed"
```

LAN access for phones / tablets on the same WiFi requires `allowedDevOrigins` in `frontend/next.config.ts` to include the host's LAN IP (see [Frontend layout](./frontend-layout.md#lan-access)).

## Operating principles enforced across the code

- **Backend never talks to LLM SDKs directly.** Everything goes through `app.services.llm.*`. See [LLM layer](./llm-layer.md).
- **Frontend never talks to the backend directly.** Goes through `frontend/src/lib/api.ts`, which calls `/api/v1/*` and is proxied by a Next route handler at `app/api/[...path]/route.ts` (10-min timeout for slow LLM calls).
- **Content ingestion is async.** The front-end fires `POST /sources`, gets a `task_id`, and polls `GET /sources/{id}/progress`. The browser stays responsive while Celery runs the extractor → analyzer → embedder pipeline.
- **State of truth is Postgres + Redis.** Celery uses Redis as the broker; the front-end never reads task state from Redis — only the database row.
- **API keys live in env vars.** Never in code, never in the repo. Per-model keys are encrypted in `model_configs.api_key` using `app.services.llm.encryption`.

## Conventions

- **Python**: async/await throughout (FastAPI native); Pydantic v2 for all I/O validation; full type annotations; Google-style docstrings.
- **TypeScript**: `strict: true`; function components + hooks; Zustand for global state; kebab-case file names; CSS variables (tokens) instead of Tailwind palette utilities for new code.
- **Commits**: conventional commits (`feat:` / `fix:` / `refactor:` / `chore:` / `docs:` / `test:`). Co-author the assistant when applicable.

## Where things live (cheat sheet)

| You want to… | Open |
|---|---|
| Change a route | `backend/app/api/routes/*.py` (FastAPI) |
| Change how a source is analyzed | `backend/app/services/content_analyzer.py` + `prompts/content_analysis.md` |
| Add a teaching block type | `backend/app/models/lesson_blocks.py` + `frontend/src/components/lesson/blocks/*.tsx` |
| Change the Socratic prompt | `backend/app/agent/prompts/*.md` |
| Change a Postgres column | `backend/app/db/models/*.py` + `alembic revision --autogenerate` |
| Adjust the design tokens | `frontend/src/app/globals.css` |
| Add a new icon | `frontend/src/components/icons.tsx` |
| Add a translation key | `frontend/src/lib/i18n.ts` |
| Change which model handles which task | Settings → Model routing (or `backend/app/services/llm/router.py`) |

For the why-and-how of each, follow the page links above.
