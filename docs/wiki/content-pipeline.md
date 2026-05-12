# Content pipeline

The path from "user pasted a URL" to "course is ready" is one Celery task that flows through eight steps. This page walks each step and points at the code.

```
POST /sources
     │
     ▼
[1] persist Source row + enqueue ingest_source task ─► Celery (Redis)
                                                          │
                                                          ▼
[2] EXTRACT     transcript / pages from the upstream URL or file
[3] CHUNK       split raw text into ContentChunk rows
[4] ANALYZE     LLM extracts concepts + per-chunk topics/summaries
[5] STORE       upsert Concept rows, link via ConceptSource, write Chunks
[6] EMBED       pgvector embeddings for chunks AND concepts
[7] DONE        mark source ready, enqueue course_generation
                                                          │
                                                          ▼
[8] GENERATE_COURSE  assemble Section rows, lessons, labs, graph cards
```

After step 8 the user sees a populated `/path/:id` and can enter `/learn`.

## Entry: `POST /sources`

`backend/app/api/routes/sources.py` accepts either a `url` field or a `file` upload. It:

1. Sniffs the type — `youtube`, `bilibili`, `pdf`, `markdown`, `url`, etc.
2. Creates a `Source` row with `status="pending"`.
3. Inserts a `source_tasks` row with `task_type="source_processing"`, `status="pending"`.
4. Dispatches the Celery task and returns `{id, task_id, ...}` immediately. **No LLM work happens in the request lifetime** — the user gets a `task_id` and the frontend polls.

If the source is a Bilibili URL and no Bilibili credential is configured, the route raises `HTTPException(412, code="bilibili_credential_required")` — the frontend catches this and renders the credential-required banner on `/import`.

## Step 2: Extract

`backend/app/tools/extractors/*.py` is the extractor family. Each implements `BaseExtractor.extract(source) → list[RawContentChunk]`:

| Extractor | Source type | Output |
|---|---|---|
| `youtube.py` | YouTube URL | Subtitle segments (existing CCs preferred; falls back to Whisper via `asr.py`) |
| `bilibili.py` | Bilibili URL | Same approach but with `dedeuserid` auth for gated content |
| `pdf.py` | PDF upload | Page-grouped text via `pypdf`, with heading detection |
| `asr.py` | Audio fallback | Whisper-compatible API (Groq / OpenAI / SiliconFlow / whisper.cpp / in-process) |

Each `RawContentChunk` has `raw_text` + `metadata` (timestamps for video, page numbers for PDFs). Chunk boundaries match the source's natural rhythm — subtitle segments, PDF headings, markdown headings.

If extraction fails (network, no captions, paywall), the worker writes `source.status = "error"` and surfaces a message into `latest_processing_task.error_summary`. The frontend's `materials-state.ts` turns that into the red "资料处理失败" chip on the Library page.

## Step 3: Chunk (optional consolidation)

For long sources with many tiny chunks, `content_ingestion._consolidate_chunks` merges adjacent small chunks under a single heading. The unit of analysis downstream is one `content_chunks` row.

`donor reuse`: if a brand-new source has the exact same upstream URL as a source already processed, the worker **clones the donor's chunks and concept links** instead of re-extracting and re-analyzing. See `content_ingestion._clone_from_donor`. This is the difference between "re-import is free" and "re-import is a 90-second LLM call".

## Step 4: Analyze

`backend/app/services/content_analyzer.py` is the LLM stage. See [Concepts & knowledge graph](./concepts-and-graph.md) for the full prompt contract — this section just describes mechanics.

```python
analyzer = ContentAnalyzer(model_router)
analysis = await analyzer.analyze(
    title=source.title,
    chunks=raw_chunks,
    source_type=source.type,
    user_directive=source.metadata_.get("user_directive", ""),
)
```

- Short sources (<8000 chars): one LLM call.
- Long sources: `_analyze_batched` splits into ≤6000-char batches, calls the LLM per batch, then `_merge_batch_results` deduplicates concepts by `name` and unions `suggested_prerequisites`.
- Model selection: `TaskType.CONTENT_ANALYSIS` → whatever is mapped in `model_routes` (default Anthropic Claude 4.x via Settings).
- Output is a single `AnalysisResult` Pydantic object.

## Step 5: Store

`content_ingestion.py` walks the analysis result and writes:

```python
# one ContentChunk per RawContentChunk
db.add(ContentChunk(
    source_id=sid, ordinal=i, raw_text=..., metadata_={topic, summary, concepts, difficulty, key_terms, has_code, has_formula, ...}
))

# upsert each Concept by name, then by alias
concept = await _get_or_create_concept(db, ext_concept)

# link concept ↔ source if not already linked
db.add(ConceptSource(concept_id=concept.id, source_id=sid, context=...))

# carry source-level analysis onto source.metadata_
source.metadata_ = {**source.metadata_, "overall_summary": ..., "concept_count": ..., "chunk_count": ..., "estimated_study_minutes": ..., "asset_plan": ..., "suggested_prerequisites": ...}
```

`_get_or_create_concept` is the dedup gate — same canonical English `name` reuses an existing row, otherwise tries every alias. **Known bug**: it currently writes `prerequisites=[]` and never resolves the LLM's name-based prereqs to UUIDs. See the [Concepts page](./concepts-and-graph.md#known-bug-prereqs-arent-resolved) for the fix.

## Step 6: Embed

`backend/app/services/embedding.py`:

```python
embed_and_store_chunks(db, chunk_ids, texts)    # text = chunk.raw_text
embed_and_store_concepts(db, concept_ids, texts) # text = f"{name}: {description}"
```

Both update `embedding pgvector` columns. The embedding provider is chosen via `TaskType.EMBEDDING` (default `text-embedding-3-small` or similar 1536-dim OpenAI-compatible). The RAG path (mentor `KnowledgeSearchTool`) consults these via pgvector cosine similarity.

## Step 7: Source done → enqueue course generation

`content_ingestion.finish_source_processing_and_enqueue_course`:
- Sets `source.status = "ready"`.
- Updates the existing `source_tasks` row to `status="success"`.
- Inserts a new `source_tasks` row with `task_type="course_generation"`, `status="pending"` linked to the same source.
- Dispatches the Celery task.

The frontend's poller sees the type-2 row appear and shows "课程生成中" instead of "资料处理中" — no extra API.

## Step 8: Generate course

`backend/app/services/course_generator.py` turns the analyzed source into a course:

```python
generator = CourseGenerator(model_router)
course = await generator.generate(db, source_ids=[sid], user_id=user_id)
```

Per source:
1. **TeachingAssetPlanner** decides lab/graph mode per chunk based on heuristics (has_code → lab_mode="inline", concept density → graph card visible). Result is stored in `source.metadata_.asset_plan`.
2. **Lesson generation**: one LLM call per "page" (group of chunks). Each lesson becomes a `Section.content.lesson` block array.
3. **Lab generation**: for sections planned as `lab_mode="inline"`, one LLM call produces a runnable Lab with starter code + tests + grading rubric. Stored in `labs` table linked to the section.
4. **Graph card**: per-section concept neighborhood (current concepts, prerequisites, unlocks). Stored on `Section.content.graph_card`.

The course is built one source at a time and saved as `Course` + `CourseSource` (M:N) + `Section` rows. `Section.order_index` is contiguous across all sources in the course.

Course-generation also writes the course description (`_generate_description`) using the analyzed summaries.

## Regeneration

`POST /api/v1/courses/:id/regenerate` (with optional `directive`) re-runs steps 4–8 with a different prompt directive. The old course stays; a new course is created with `parent_id=old.id`. The frontend's regenerate banner polls `GET /courses/regenerations/:task_id` until status=success and then offers "打开新版本".

## Cancel / retry

- `POST /sources/:id/cancel` flips `source_tasks.status = "cancelled"`. The worker checks `raise_if_cancelled` between every step and aborts.
- `POST /sources/:id/retry` clears the failed task row and re-dispatches.

Both UI affordances are wired in the dashboard's `SourcePipelineView` (`frontend/src/components/materials/source-pipeline-view.tsx`).

## What's stored where (table cheat sheet)

| Lifecycle event | Row |
|---|---|
| URL imported | `sources` (status=pending) + `source_tasks` (type=source_processing, status=pending) |
| Extraction done | `content_chunks` (N rows) + `source.metadata_.chunk_count` |
| Analysis done | `concepts` (upsert), `concept_sources` (link), `content_chunks.metadata_.{concepts,topic,summary}`, `source.metadata_.{overall_summary, concept_count, asset_plan}` |
| Embedding done | `content_chunks.embedding`, `concepts.embedding` |
| Source done | `source.status="ready"`, processing task `status=success` |
| Course generation done | `courses`, `course_sources`, `sections`, `labs`, generation task `status=success` |

See [Data model](./data-model.md) for the column-level breakdown.
