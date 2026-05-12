# Concepts & knowledge graph

How a "concept" gets from a transcript into the graph view at `/graph`. This page is the deep version of [content pipeline §4-§6](./content-pipeline.md#step-4-analyze) plus the read path.

## What counts as a concept

The prompt at `backend/app/services/prompts/content_analysis.md` defines this in plain language. A concept is **a named teachable idea a student can understand or fail to understand independently**. `recursion`, `transformer_architecture`, `napoleonic_wars` qualify. `chapter_one`, `the_python_list_we_just_saw`, `introduction` do not.

The prompt enforces five rules on every emitted concept:

| Field | Rule |
|---|---|
| `name` | canonical English `lower_snake_case`. The widely-accepted term in the field. Never invent novel names. |
| `description` | 1–2 sentences in English. Defines what it *is*, independent of how this source covers it. |
| `aliases` | Every other surface form: source-language term, common spelling variants, abbreviations, near-synonyms. **Always include the source-language form** if the source isn't English. |
| `prerequisites` | Only `name` values that also appear in this same `concepts` array. No external refs, no cycles. Empty = foundational. |
| `category` | One of: `algorithms`, `data_structures`, `programming_language`, `system_design`, `math`, `science`, `history`, `language`, `business`, `design`, `other`. |

Cardinality: **3–15 concepts per source**. The prompt explicitly tells the LLM that fewer-but-sharper beats many-and-fuzzy.

## How the LLM is invoked

`backend/app/services/content_analyzer.py`:

```python
provider = await model_router.get_provider(TaskType.CONTENT_ANALYSIS)
system = _PROMPT.render(user_directive=user_directive)
response = await provider.chat([
    UnifiedMessage(role="system", content=system),
    UnifiedMessage(role="user", content=f'Analyze the following content from a {source_type} source titled "{title}":\n\n{content_text}'),
], max_tokens=4096, temperature=0.3)
```

`temperature=0.3` is chosen for stability — the same source should produce mostly the same concepts on re-analysis. The 4096-token cap fits 3–15 concepts plus per-chunk topic/summary easily; if a source exceeds 8000 chars of raw text, `_analyze_batched` splits into 6000-char batches and merges via `_merge_batch_results` (dedup by `name`, union prereqs).

The fallback path (`_parse_analysis_response` catches `JSONDecodeError`): if the LLM emits malformed JSON, the analyzer produces an `AnalysisResult` with empty `concepts` and one chunk per input. The course will still get built (sections will be empty-ish) — better degraded than failed.

## Pydantic shape

```python
class ExtractedConcept(BaseModel):
    name: str
    description: str = ""
    aliases: list[str] = []
    prerequisites: list[str] = []  # names, NOT UUIDs
    category: str = ""

class AnalyzedChunk(BaseModel):
    topic: str
    summary: str
    raw_text: str
    concepts: list[str] = []       # names referencing the ExtractedConcept list
    difficulty: int = 3             # 1..5
    key_terms: list[str] = []
    has_code: bool = False
    has_formula: bool = False
    metadata: dict = {}

class AnalysisResult(BaseModel):
    source_title: str
    overall_summary: str
    overall_difficulty: int = 3
    concepts: list[ExtractedConcept]
    chunks: list[AnalyzedChunk]
    suggested_prerequisites: list[str] = []
    estimated_study_minutes: int = 0
```

## Postgres schema

`backend/app/db/models/concept.py`:

```python
class Concept(BaseMixin, Base):
    __tablename__ = "concepts"
    id: UUID                    # primary key
    name: str                   # unique, indexed
    description: str | None
    category: str | None
    aliases: JSONB              # list of strings (every other surface form)
    prerequisites: list[UUID]   # ARRAY(UUID) — but see Known bug below
    embedding: pgvector         # 1536-dim by default, nullable

class ConceptSource(Base):
    __tablename__ = "concept_sources"
    concept_id: UUID            # FK -> concepts.id, primary
    source_id: UUID             # FK -> sources.id, primary
    context: str | None         # the LLM-supplied description in THIS source's context
    # composite PK = many-to-many edge
```

Concepts are **global**. `binary_search` learned from a CMU video and `binary_search` mentioned in a SRE Book PDF are one `concepts` row with two `concept_sources` rows.

## Upsert (dedup) logic

`_get_or_create_concept` in `backend/app/worker/tasks/content_ingestion.py:630`:

```python
async def _get_or_create_concept(db, ext_concept):
    # 1. exact name match
    if existing := await db.scalar(select(Concept).where(Concept.name == ext_concept.name)):
        return existing

    # 2. any alias matches an existing canonical name
    for alias in ext_concept.aliases:
        if existing := await db.scalar(select(Concept).where(Concept.name == alias)):
            return existing

    # 3. new row
    concept = Concept(
        name=ext_concept.name,
        description=ext_concept.description,
        category=ext_concept.category,
        aliases=ext_concept.aliases,
        prerequisites=[],                # ← see Known bug
    )
    db.add(concept)
    await db.flush()
    return concept
```

This is why a Chinese source about "二分查找" reuses the existing English `binary_search` row instead of creating a duplicate — `aliases` covers both directions.

## Embeddings

`backend/app/services/embedding.py:embed_and_store_concepts`:

```python
texts = [f"{c.name}: {c.description or ''}" for c in new_concepts]
embeddings = await provider.embed(texts)
UPDATE concepts SET embedding = $vec WHERE id = $id  # one per concept
```

`provider` is resolved via `TaskType.EMBEDDING`. The text format `"name: description"` is deliberate — embedding the bare name produces too few signal tokens, and embedding the full description without the name loses the anchor.

`KnowledgeSearchTool` (`backend/app/agent/tools/knowledge.py`) consults these via pgvector cosine. The mentor asks "what's most relevant to the user's question" and gets back the top-K concepts + their `ConceptSource.context` snippets.

## Read path — `GET /api/v1/courses/:id/knowledge-graph`

`backend/app/services/knowledge_graph.py:KnowledgeGraphService.get_graph`:

```python
# 1. concept_ids for this course
source_ids = SELECT source_id FROM course_sources WHERE course_id = ?
concept_ids = SELECT DISTINCT concept_id FROM concept_sources WHERE source_id IN (...)
concepts = SELECT * FROM concepts WHERE id IN (...) LIMIT 200

# 2. per-concept mastery for the current user
for concept in concepts:
    easiness = SELECT easiness FROM review_items WHERE user_id=? AND concept_id=?
    exercise_ids = SELECT id FROM exercises WHERE ? = ANY(concepts)
    scores = SELECT score FROM exercise_submissions WHERE user_id=? AND exercise_id IN (...)
    mastery = calculate_mastery_score(easiness, scores)

# 3. edges from prereqs that are present in the result set
for concept in concepts:
    for prereq_id in concept.prerequisites:
        if prereq_id in concept_ids_set:
            edges.append({source: prereq_id, target: concept.id})
```

200-concept hard limit. Beyond that the front-end isn't useful anyway — the graph becomes a hairball.

## Mastery formula

```python
review_score   = (easiness / 5.0) if easiness is not None else 0
exercise_score = mean(scores) / 100.0 if scores else 0

if review and exercise:   mastery = 0.4 * review_score + 0.6 * exercise_score
elif review:              mastery = 0.4 * review_score
elif exercise:            mastery = 0.6 * exercise_score
else:                     mastery = 0.0
```

Weights chosen so that:
- A concept with strong exercise performance and no reviews caps at 0.6 (not "fully mastered" — you might still forget it).
- A concept with strong SM-2 easiness but no exercises caps at 0.4 (you recognize it, but haven't demonstrated application).
- Together they can reach 1.0 if the user demonstrates both retention (review) and application (exercise).

The front-end then thresholds:

```ts
if (mastery >= 0.7) return "mastered";
if (mastery >= 0.3) return "learning";
return "seen";
```

See `frontend/src/app/graph/page.tsx:masteryFor` and the [Frontend layout](./frontend-layout.md#graph) page for the visual treatment.

## Known bug: prereqs aren't resolved

The LLM emits `prerequisites: ["sorted_array", "loop_invariant"]` per the prompt contract. The ingestion code at `content_ingestion.py:656` writes `prerequisites=[]`:

```python
concept = Concept(
    name=ext_concept.name,
    description=ext_concept.description,
    category=ext_concept.category,
    aliases=ext_concept.aliases,
    prerequisites=[],        # ← LLM-provided names are NEVER resolved to UUIDs
)
```

There's no later pass that translates names → UUIDs. Consequence: `concept.prerequisites` is always `[]` in production, so the graph endpoint's edge-building (`for prereq_id in concept.prerequisites: ...`) never adds an edge. **Every graph today returns `edges=[]`** — the frontend renders concept dots but no connecting lines.

### Fix sketch

After all concepts from an analysis are upserted, resolve prereqs by name:

```python
# in content_ingestion.py, after the upsert loop, BEFORE the embed step
name_to_id = {c.name: c.id for c in concepts_for_this_analysis}
for ext_concept in analysis.concepts:
    if not ext_concept.prerequisites:
        continue
    prereq_uuids = [name_to_id[n] for n in ext_concept.prerequisites if n in name_to_id]
    if not prereq_uuids:
        continue
    concept_id = name_to_id[ext_concept.name]
    await db.execute(
        update(Concept)
        .where(Concept.id == concept_id)
        .values(prerequisites=prereq_uuids)
    )
```

About 15 lines. For existing data, run a one-shot script that walks every source's `analysis` snapshot in `source.metadata_` (which we already keep) and re-resolves prereqs. Or add an Alembic data migration.

## Suggested prerequisites (different thing)

The LLM also emits `suggested_prerequisites` at the source level — concepts a *student* should know before starting this source, but that aren't IN the source. Those are stored on `source.metadata_.suggested_prerequisites` and surfaced by `course_generator._format_source_ref` into the course description.

They're not the same as concept-level `prerequisites` (which are *within* the concept graph). Don't conflate.

## Why not store mastery?

Mastery is recomputed per request. The signals it derives from (review easiness, exercise scores) change frequently and the formula is cheap. Caching it would mean:
- Stale values until invalidation runs.
- Invalidation logic on every review / exercise event.
- A new column the agent layer would have to keep in sync.

Recomputing 200 concepts costs roughly 200 small queries = under 200ms in practice. Worth it.
