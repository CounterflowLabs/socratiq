# Sub-project F: Deep Capabilities — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the 5-layer memory system (episodic + metacognitive), add LLM-powered subtitle translation with caching, and build D3.js knowledge graph visualization with mastery tracking.

**Architecture:** Two new DB tables for episodic/metacognitive memory with vector search + TTL pruning. Translation uses a separate `translations` table with chunk-level caching and cost estimation. Knowledge graph API aggregates concepts from CourseSource chain with mastery calculated from review_items + exercise_submissions. Frontend gets a D3.js force-directed graph component and translation toggle on the learn page.

**Tech Stack:** pgvector (existing), D3.js (new frontend dep), Celery periodic tasks (pruning)

---

## Tasks

### Task 1: DB migration — episodic_memories + metacognitive_records + translations

Create 3 new ORM models and Alembic migration:

**Files:**
- Create: `backend/app/db/models/episodic_memory.py`
- Create: `backend/app/db/models/metacognitive_record.py`
- Create: `backend/app/db/models/translation.py`
- Modify: `backend/app/db/models/__init__.py`

EpisodicMemory: user_id FK, event_type VARCHAR(50), content TEXT, context JSONB, importance NUMERIC(3,2) default 0.5, embedding Vector(1536), expires_at TIMESTAMP nullable. Indexes: (user_id, importance DESC), partial on expires_at, ivfflat on embedding.

MetacognitiveRecord: user_id FK, strategy VARCHAR(100), effectiveness NUMERIC(3,2), context JSONB, evidence TEXT. Index: (user_id, effectiveness DESC).

Translation: chunk_id FK to content_chunks, target_lang VARCHAR(10), translated_text TEXT, model_used VARCHAR(100). Unique(chunk_id, target_lang). Index on chunk_id.

Generate + apply Alembic migration. Commit.

### Task 2: MemoryManager 5-layer retrieval + agent tools

**Files:**
- Rewrite: `backend/app/memory/manager.py`
- Create: `backend/app/agent/tools/memory.py` (EpisodicMemoryTool + MetacognitiveReflectTool)
- Create: `backend/tests/test_memory.py`

MemoryManager.retrieve(user_id, query, context) returns MemoryContext with all 5 layers:
1. Working memory: recent messages from conversation (limit 20)
2. Profile: load_profile(user_id)
3. Episodic: vector similarity search on episodic_memories
4. Content: RAG search (existing RAGService)
5. Progress + Metacognitive: learning records + effective strategies

EpisodicMemoryTool: actions "record" (save event with auto importance/TTL) and "recall" (vector search).
MetacognitiveReflectTool: after session, LLM reflects on strategy effectiveness, saves record.

Importance < 0.2 → don't record. Importance < 0.3 → expires_at = created_at + 90 days.

Wire both tools into chat.py MentorAgent tools list.

Tests: MemoryManager retrieve with mocked layers, EpisodicMemory record/recall, pruning threshold.

### Task 3: Memory pruning Celery task

**Files:**
- Create: `backend/app/worker/tasks/memory_pruning.py`

Celery periodic task (daily) that deletes episodic_memories where expires_at < now().

Register in Celery beat schedule. Test with direct function call.

### Task 4: TranslationService + API routes

**Files:**
- Create: `backend/app/services/translation.py`
- Create: `backend/app/api/routes/translations.py`
- Create: `backend/tests/test_translation.py`

TranslationService:
- `estimate_cost(section_id, target_lang)`: count untranslated chunks, estimate tokens
- `translate_section(section_id, target_lang, user_id)`: check cache → batch LLM translate → save → log usage

API:
- `GET /api/v1/sections/{id}/translate/estimate?target=zh`
- `POST /api/v1/sections/{id}/translate?target=zh`

Both require auth. POST uses CostGuard before proceeding. Single chunk failure doesn't block others.

Register router in main.py.

### Task 5: Knowledge graph API + mastery calculation

**Files:**
- Create: `backend/app/services/knowledge_graph.py`
- Create: `backend/app/api/routes/knowledge_graph.py`
- Create: `backend/tests/test_knowledge_graph.py`

KnowledgeGraphService:
- `get_graph(course_id, user_id, max_depth=2)`: query concepts via CourseSource chain, calculate mastery per concept, build nodes + edges, limit 200 nodes
- `calculate_mastery(user_id, concept_id)`: 0.4 * review_score + 0.6 * exercise_score

API: `GET /api/v1/courses/{id}/knowledge-graph?max_depth=2` → {nodes, edges}

Register router in main.py.

### Task 6: Frontend — translation toggle on learn page

**Files:**
- Modify: `frontend/src/lib/api.ts` (add translation APIs)
- Modify: `frontend/src/app/learn/page.tsx` (add translate button + dual-language display)

Add to api.ts: `estimateTranslation(sectionId, target)`, `translateSection(sectionId, target)`.

On learn page: add "翻译为中文" toggle button. When clicked, show cost estimate → confirm → call translate → display dual-language (original above, translation below).

### Task 7: Frontend — D3.js knowledge graph component

**Files:**
- Create: `frontend/src/components/knowledge-graph/force-graph.tsx`
- Create: `frontend/src/components/knowledge-graph/concept-tooltip.tsx`
- Modify: `frontend/src/lib/api.ts` (add knowledge graph API)
- Modify: `frontend/src/app/learn/page.tsx` (render graph in "概念" tab)

Install d3: `npm install d3 @types/d3`

Add `getKnowledgeGraph(courseId)` to api.ts.

ForceGraph component: D3 force-directed graph with:
- Nodes colored by mastery (red→yellow→green)
- Edges for prerequisite relationships
- Click node → navigate to section
- Tooltip on hover showing concept name + mastery %
- Mobile: list view fallback

Render in learn page's "概念" tab (currently placeholder).

### Task 8: Final verification

Run all backend tests, frontend build + tests. Verify new endpoints respond.
