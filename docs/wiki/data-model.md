# Data model

Every Postgres table, grouped by domain. Schemas live in `backend/app/db/models/*.py`; migrations in `backend/alembic/versions/`. All tables use UUIDv4 primary keys via `BaseMixin`, and all carry `created_at` + `updated_at` timestamps.

Common conventions:
- pgvector columns use `Vector()` with model-dependent dimensions (no fixed dim — `embed_and_store_*` adapts to whatever the embedding provider returns).
- M:N join tables use **composite primary keys** rather than surrogate IDs (`(concept_id, source_id)` on `concept_sources`).
- `metadata` collisions with SQLAlchemy's reserved name → we use `metadata_` (with the trailing underscore).

## Auth & identity

| Table | Module | Columns of note |
|---|---|---|
| `users` | `user.py` | `id`, `email`, `display_name`, `profile JSONB` (5-layer memory layer #2). Single-user dev defaults to a fixed UUID. |
| `bilibili_credentials` | `bilibili_credential.py` | `user_id`, `dedeuserid`, `cookies JSONB`, `last_verified_at`. One per user. |

## Content layer (source → analysis)

| Table | Module | Columns of note |
|---|---|---|
| `sources` | `source.py` | `id`, `user_id`, `type` (`youtube`/`bilibili`/`pdf`/`markdown`/`url`/...), `url`, `title`, `status` (`pending`/`processing`/`ready`/`error`/`cancelled`), `metadata_ JSONB` (overall_summary, concept_count, chunk_count, asset_plan, suggested_prerequisites, estimated_study_minutes). |
| `content_chunks` | `content_chunk.py` | `source_id`, `ordinal`, `raw_text`, `metadata_ JSONB` (topic, summary, concepts, difficulty, key_terms, has_code, has_formula, timestamp/page_index), `embedding pgvector`. |
| `concepts` | `concept.py` | `name` (unique, indexed, canonical English snake_case), `description`, `category`, `aliases JSONB`, `prerequisites ARRAY(UUID)` (**always `[]` today** — see [the bug](./concepts-and-graph.md#known-bug-prereqs-arent-resolved)), `embedding pgvector`. |
| `concept_sources` | `concept.py` | M:N — composite PK `(concept_id, source_id)`, plus `context` (per-source description). |
| `source_tasks` | `source_task.py` | `source_id`, `task_type` (`source_processing`/`course_generation`/`course_regeneration`), `status` (`pending`/`running`/`success`/`failure`/`cancelled`), `celery_task_id`, `stage` (latest sub-step label), `current`/`total`, `error_summary`, `course_id` (set on success of course_generation). |

## Courseware

| Table | Module | Columns of note |
|---|---|---|
| `courses` | `course.py` | `title`, `description`, `created_by`, `parent_id` (regeneration ancestry), `regeneration_directive`, `regeneration_metadata`, `active_regeneration_task_id`. `version_index` is computed on read by walking `parent_id`. |
| `course_sources` | `course.py` | M:N — `(course_id, source_id)` composite PK. Same source can power multiple courses. |
| `sections` | `course.py` | `course_id`, `title`, `order_index` (contiguous across all sources in the course), `source_id` (nullable for synthesized sections), `source_start`/`source_end` (transcript or page range), `content JSONB` (lesson blocks + graph_card + lab_mode), `difficulty`, `active_exercise_task_id`, `exercise_generation_error`. |
| `labs` | `lab.py` | `section_id`, `title`, `description`, `language` (`python`/`js`/...), `starter_code JSONB` (filename → contents), `test_code JSONB`, `run_instructions`, `confidence` (0..1, generator's self-rated). |
| `exercises` | `exercise.py` | `section_id`, `concepts ARRAY(UUID)`, `kind` (`mcq`/`short`/`open`), `prompt`, `options JSONB`, `expected_answer JSONB`, `rubric JSONB`. |
| `exercise_submissions` | `exercise_submission.py` | `user_id`, `exercise_id`, `answer JSONB`, `score` (0..100), `feedback`, `evaluated_by_model`. |

## Learning state (5-layer memory layers 3–5)

| Table | Module | Layer | Columns |
|---|---|---|---|
| `section_progress` | `section_progress.py` | Progress (4) | `user_id`, `section_id`, `lesson_read bool`, `lab_completed bool`, `exercise_best_score float`. Computed `status` column for fast filtering. |
| `review_items` | `review_item.py` | Progress (4) | SM-2 spaced repetition. `user_id`, `concept_id` (nullable; can also be section-anchored), `due_at`, `easiness` (1..5, default 2.5), `interval` (days), `repetitions`. |
| `episodic_memory` | `episodic_memory.py` | Episodic (3) | `user_id`, `summary`, `embedding pgvector`, `metadata JSONB` (course/section context). The mentor decides to write these via `EpisodicMemoryTool`. |
| `metacognitive_records` | `metacognitive_record.py` | Meta (5) | `user_id`, `observation`, `tactic`, `effectiveness float`. Mentor's notes about its own teaching choices. |
| `learning_records` | `learning_record.py` | — | Raw event log: every page read, every exercise attempt. Used to compute analytics. |

The first layer (working memory) is the in-process message list during `MentorAgent.process()`. The second (student profile) is `users.profile`.

## Conversations

| Table | Module | Columns |
|---|---|---|
| `conversations` | `conversation.py` | `user_id`, `course_id` (nullable), `section_id` (nullable), `title`. |
| `messages` | `message.py` | `conversation_id`, `role` (`user`/`assistant`/`tool_result`), `content JSONB` (the full `ContentBlock[]` from `UnifiedMessage`), `citations JSONB` (chunk_ids the mentor pulled into its response). |

The chat history persists across reloads — the front-end's TutorDrawer loads the last N messages on open, then takes over from the SSE stream.

## LLM configuration

| Table | Module | Columns |
|---|---|---|
| `model_configs` | `model_config.py` | `name` (user-chosen), `provider_type` (`anthropic`/`openai`/`openai_compatible`/`codex`), `model_id` (e.g. `claude-sonnet-4-20250514`), `base_url` (for openai_compatible), `api_key` (encrypted), `api_key_masked`, `supports_tool_use`, `supports_streaming`, `max_tokens_limit`, `model_type` (`chat`/`embedding`), `is_active`. |
| `model_routes` | `model_routes` migration; ORM in `model_config.py` | `task_type` (one of `mentor_chat`/`content_analysis`/`evaluation`/`embedding`), `model_name` (FK to `model_configs.name`). One row per task type. |
| `whisper_config` | `whisper_config.py` | Singleton row. `mode` (preset id like `groq`/`siliconflow`/`whispercpp`/`local`), `api_base_url`, `api_model`, `api_key` (encrypted), `local_model` (model size for in-process Whisper). |
| `llm_usage_logs` | `llm_usage_log.py` | `model_name`, `task_type`, `input_tokens`, `output_tokens`, `request_id`. Per-call usage record. |

See [LLM layer](./llm-layer.md) for how these tables drive provider selection.

## Translations

| Table | Module | Columns |
|---|---|---|
| `translations` | `translation.py` | `chunk_id`, `target_lang`, `translated_text`. Lazy cache of LLM-translated chunk content (the lesson UI shows side-by-side or replace-in-place). |

## Foreign-key cascade summary

| Parent | Cascades on delete to |
|---|---|
| `users` | `bilibili_credentials`, `section_progress`, `review_items`, `episodic_memory`, `metacognitive_records`, `learning_records`, `exercise_submissions`, `conversations` |
| `sources` | `content_chunks`, `concept_sources`, `source_tasks`, `course_sources` (NOT cascade — keep history) |
| `courses` | `course_sources`, `sections` |
| `sections` | `labs`, `exercises`, `section_progress` |
| `exercises` | `exercise_submissions` |
| `conversations` | `messages` |

Deleting a user removes the entire learning state. Deleting a source removes its chunks/concept links but keeps the courses (the course can survive a deleted source if other sources contribute — though it'll look thin).

## Embeddings inventory

Three tables carry pgvector columns:

| Table | Column | Dimension | Populated by |
|---|---|---|---|
| `content_chunks` | `embedding` | provider-dependent | `EmbeddingService.embed_and_store_chunks` |
| `concepts` | `embedding` | provider-dependent | `EmbeddingService.embed_and_store_concepts` |
| `episodic_memory` | `embedding` | provider-dependent | `EpisodicMemoryTool.add` |

All three are searched via cosine similarity (`<->` operator with HNSW indexes). The mentor's RAG path queries them in parallel via `KnowledgeSearchTool`.

## Migrations

```bash
cd backend
alembic upgrade head                       # apply pending
alembic revision --autogenerate -m "msg"   # generate new from model diffs
alembic downgrade -1                       # roll back one
```

Always review the autogenerated migration before committing — Alembic doesn't always pick the right column type, especially for JSONB defaults.
