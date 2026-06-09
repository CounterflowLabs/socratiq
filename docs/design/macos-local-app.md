# Localization: Single-Binary macOS App

Status: **Planning** · Owner: TBD · Last updated: 2026-06-07

Make Socratiq run as a **double-click macOS `.app`** with no Docker and no
external servers (no Postgres, no Redis, no MinIO). One local process holds the
whole stack; the only network dependency is the **platform-hosted LLM** reached
with an activation code.

This is a planning document. Nothing here is built yet. See
[Phased plan](#phased-plan) for the proposed order and acceptance criteria.

---

## 1. Goal

Today Socratiq is a 5-service Docker Compose stack (`db` pgvector · `redis` ·
`backend` · `worker` · `frontend`). The goal is to collapse it into a single
locally-launchable macOS application that a non-technical user can double-click,
with all infrastructure embedded.

**Non-goal:** fully offline. Course generation still calls a cloud LLM (by
design, see decisions). Offline = the *infrastructure* is local, not the LLM.

## 2. Decisions (locked)

| # | Decision | Choice | Consequence |
|---|---|---|---|
| A | Distribution target | **Double-click `.app` for end users** | Must bundle Python runtime, binaries, models; code-sign + notarize. |
| B | Database | **SQLite + sqlite-vec** (single file) | No DB server to bundle, but a real rewrite off Postgres/pgvector/JSONB. |
| C | Offline scope | **Hybrid: local infra + cloud LLM** | DB/queue/storage/embeddings local; generation calls the platform LLM. |

**LLM access model** (per the project's SaaS direction: *platform-hosted LLM +
activation code, not BYOK*): the `.app` does not take a user's provider key. It
points `services/llm` at the **platform LLM proxy** (`base_url = platform
endpoint`, `key = activation code`). This is config + auth, ~zero change to the
OpenAI-compatible provider. **Prerequisite:** the platform LLM proxy +
activation-code validation service must exist (out of scope of the `.app`
itself).

## 3. Current dependency footprint (verified)

| Dependency | Current usage | Localization difficulty |
|---|---|---|
| **PostgreSQL + pgvector** | All ORM models use `JSONB`; `content_chunk` uses a pgvector `Vector` column; `section_planner` + `rag` have pg-specific SQL; `asyncpg`. | **Highest** (deep lock-in → Decision B rewrite) |
| **Redis** | ARQ queue + AG-UI event streaming (SSE) + rate-limit middleware + cache, across ~15 files. | Medium (replace in-process) |
| **MinIO / S3** | **Not actually used** — only a local `upload_dir`. | None (already local fs) |
| **ollama** (embeddings) | Local process, `nomic-embed-text`; ingestion already degrades gracefully when absent. | Medium (bundle a packable embedder instead) |
| **Cloud LLM** (DeepSeek) | Needs key + network; abstraction also supports ollama / OpenAI-compat. | Becomes platform endpoint + activation code |
| **Extraction binaries** (yt-dlp / ffmpeg / whisper) | whisper default `mode="api"` (Groq); local needs ffmpeg + local whisper. | Medium (bundle) |
| **Next.js 16** | Full server (app router + a route handler proxying `/api`); **cannot static-export as-is**. | Medium (static SPA or shell) |
| **worker** | ARQ, separate process, needs Redis. (Note: `docker-compose.yml` worker `command:` still says `celery` — stale, pre-existing.) | Medium (in-process) |

## 4. Target architecture (`.app`)

One bundled local process:

- **FastAPI** serves the API **and** the static frontend.
- **In-process worker** (asyncio background tasks) — no Redis, no separate ARQ
  process.
- **In-process event bus** (asyncio pub/sub) feeding the SSE endpoints — no
  Redis streams.
- **SQLite + sqlite-vec** single file at
  `~/Library/Application Support/Socratiq/socratiq.db`.
- **Local embeddings + ASR + ffmpeg** bundled.
- **LLM → platform proxy** authenticated by an activation code (entered on first
  run).

```
double-click .app
  → init data dir + SQLite (create/migrate)
  → start uvicorn (API + in-process worker + in-memory event bus + static FE)
  → open browser / webview
  → user enters activation code → LLM calls go to the platform proxy
```

All local/in-process backends sit behind an `APP_MODE` switch (`local` vs
`server`), so the existing Docker/Redis/ARQ/Postgres path is preserved and not
broken. Use one interface per concern (`TaskBackend`, event sink, KV, DB
dialect) chosen by a factory — avoid scattering `if local:` across the codebase.

## 5. Phased plan

Each phase removes one external dependency and is independently verifiable.
Acceptance for every phase: *after this phase, one fewer external service is
required and the golden path (import → generate → learn) still works end to
end.*

### P1 — In-process runtime (drop Redis)
Cleanest, lowest-risk start; touches no DB or packaging.
- Introduce, behind `APP_MODE=local`:
  - `TaskBackend`: `LocalTaskBackend` (asyncio background tasks + in-process
    retry) vs existing ARQ; unify `enqueue / abort / get_state`.
  - Event sink: `InMemoryEventSink` (asyncio pub/sub) replacing
    `RedisEventSink`; SSE endpoints read from the in-memory bus.
  - KV: in-process dict + TTL replacing the Redis cache / rate-limiter.
  - In `local` mode the worker runs in the FastAPI `on_startup` hook.
- **Acceptance:** a single `uvicorn` with `APP_MODE=local` and **no Redis**
  runs the full golden path incl. live SSE progress; `pytest` green.

### P2 — SQLite + sqlite-vec data layer (largest, highest risk)
- Deps: `aiosqlite` + `sqlite-vec`.
- Models off-Postgres: `JSONB → JSON`, pgvector `Vector → sqlite-vec` table (or
  blob), `ARRAY → JSON`.
- Rewrite pg-specific SQL: `section_planner` (~6 spots), `rag.py` (vector
  search → sqlite-vec `vec0` MATCH, or in-memory brute-force cosine for small
  N), conftest `TRUNCATE ... RESTART IDENTITY`.
- Migrations: SQLite baseline (Alembic or first-run `create_all`); optional
  Postgres→SQLite data import script.
- Keep a single dialect-adaptation layer so prod (Postgres) / local (SQLite)
  don't fork into two divergent code paths.
- **Acceptance:** delete DB → first run auto-creates the single `.db`; `pytest`
  green on SQLite; vector search / section bucketing / course generation behave
  the same as on Postgres.

### P3 — Local embeddings / ASR / ffmpeg (the "local" half of hybrid)
- Embeddings: drop the ollama-install dependency; use a packable embedder
  (`fastembed` / onnxruntime + a small model, ~100 MB) via a
  `LocalEmbeddingProvider` on the existing embedding abstraction. (Fallback
  option: embeddings via the platform endpoint.)
- ASR: `whisper.cpp` / `faster-whisper` + a base model (bundled), replacing the
  Groq `api` mode; ship `ffmpeg` in the `.app`.
- **Acceptance:** with everything but the LLM offline, importing a local
  PDF/audio/video yields chunks + local embeddings + a course.

### P4 — Single-process shell + packable frontend + platform LLM
- Frontend: Next 16 is currently a full server (route-handler `/api` proxy) and
  **can't be packaged as-is**. Two options:
  1. **Static SPA** (`output: 'export'`, drop the server route handler, call the
     local backend same-origin) served by FastAPI — recommended, most "single
     process".
  2. **Tauri** shell loading the app.
- LLM: provider `base_url = platform proxy`, `key = activation code`; first-run
  activation-code entry. **Depends on the platform proxy existing.**
- Single entry: `uvicorn` serves API + worker + static FE + local models; opens
  browser / webview.
- **Acceptance:** one command (`APP_MODE=local`) → browser → enter activation
  code → golden path works.

### P5 — Package `.app` + sign/notarize
- Bundle the Python runtime (`briefcase` / `PyInstaller` / Tauri sidecar) +
  sqlite-vec + ffmpeg + whisper/embedding models + the static frontend.
- Data + models in `~/Library/Application Support/Socratiq/`; first-run init.
- **Code-sign + notarize** (else Gatekeeper blocks); ship a DMG.
- **Acceptance:** a clean Mac double-clicks the `.app` → auto-init → golden path
  works.

## 6. Risks / tech debt

- **P2 is the bulk:** pgvector + JSONB → SQLite is a sizeable rewrite and a
  long-term *two-dialect* maintenance burden (prod Postgres / local SQLite).
  Mitigate with a single dialect-adaptation layer, not scattered `if sqlite:`.
- **`.app` size:** bundling Python + ffmpeg + whisper/embedding models → several
  GB; signing/notarization has a learning curve.
- **Frontend static-ification:** must audit for any SSR / server-component /
  route-handler dependence (most components seen are `"use client"`, which is
  promising but unverified).
- **Platform LLM dependency:** the `.app`'s generation quality/availability
  rides on the platform endpoint; no generation offline (accepted under the
  hybrid choice).
- **Reproducibility / migration:** moving data off Docker Postgres, port/path
  conflicts, first-run init latency.

## 7. Open sub-decisions (decide at the relevant phase)

- Embeddings in the `.app`: bundled local model vs platform endpoint.
- ASR: bundled local whisper vs platform.
- Frontend packaging: static export served by FastAPI vs Tauri shell.
- Python packaging tool: `briefcase` vs `PyInstaller` vs Tauri sidecar.

## 8. Suggested starting point

**P1 (drop Redis, in-process)** is the cleanest, zero-risk entry: it touches no
DB and no packaging, removes one service immediately, and is independently
verifiable. Recommend starting there once this plan is approved.
