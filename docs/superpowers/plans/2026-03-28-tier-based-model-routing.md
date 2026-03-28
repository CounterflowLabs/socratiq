# Tier-Based Model Routing — Implementation Plan

> **Status:** COMPLETED (2026-03-28)

**Goal:** Replace task_type-based model routing with a tier-based system (primary/light/strong/embedding) so users configure models by capability tier, and the system maps task types to tiers internally.

**Branch:** `main`

---

## Context

The previous routing system mapped 4 task types (mentor_chat, content_analysis, evaluation, embedding) directly to model names via a `model_route_configs` DB table. Problems:

1. Setup page created models but never created route mappings → all tasks failed with "No model configured"
2. Users couldn't understand task_type semantics to assign models properly
3. Misaligned with CLAUDE.md's designed primary/light/strong/embedding tier model

## Design

### Tier Definitions

| Tier | Purpose | Mapped TaskTypes |
|------|---------|-----------------|
| `primary` | Main interaction, needs tool_use + streaming | MENTOR_CHAT |
| `light` | Lightweight analysis/translation/summaries | CONTENT_ANALYSIS |
| `strong` (optional) | Complex reasoning/evaluation; **falls back to primary when unconfigured** | EVALUATION |
| `embedding` | Vector computation | EMBEDDING |

### Key Decision: TaskType Preserved Internally

The `TaskType` enum is kept — 12 call sites remain unchanged. The router maps TaskType → ModelTier → model config internally via `TASK_TIER_MAP`.

---

## Completed Tasks

- [x] **Task 1: Alembic Migration**
  - `backend/alembic/versions/942f0ec50aae_migrate_task_type_to_tier_routing.py`
  - Renamed column `task_type` → `tier`
  - Data migration: mentor_chat→primary, content_analysis→light, evaluation→strong, embedding→embedding
  - Replaced unique constraint

- [x] **Task 2: DB Model**
  - `backend/app/db/models/model_config.py`
  - `ModelRouteConfig` → `ModelTierConfig` (with backwards compat alias)
  - Column `task_type` → `tier`

- [x] **Task 3: Pydantic Schemas**
  - `backend/app/models/model_schemas.py`
  - Added `ModelTier` enum (primary/light/strong/embedding)
  - `ModelRouteUpdate` → `ModelTierUpdate`, `ModelRouteResponse` → `ModelTierResponse`

- [x] **Task 4: Config Manager**
  - `backend/app/services/llm/config.py`
  - `get_route_configs()` → `get_tier_configs()`
  - `update_route_config()` → `update_tier_config()`

- [x] **Task 5: Router (core change)**
  - `backend/app/services/llm/router.py`
  - Added `ModelTier` enum and `TASK_TIER_MAP`
  - `get_provider(task_type)` resolves tier first, then queries config
  - Strong tier falls back to primary when unconfigured
  - Cache key changed to `tier:{tier.value}`

- [x] **Task 6: LLM __init__.py**
  - Exported `ModelTier`

- [x] **Task 7: API Routes**
  - `backend/app/api/routes/model_routes.py` — endpoint changed to `/api/v1/model-tiers`
  - `backend/app/api/routes/models.py` — auto-assign logic uses tiers

- [x] **Task 8: Frontend API**
  - `frontend/src/lib/api.ts`
  - Added `ModelTier` type, `ModelTierResponse` interface
  - Added `getModelTiers()` and `updateModelTiers()` functions

- [x] **Task 9: Frontend Settings Page**
  - `frontend/src/app/settings/page.tsx`
  - Replaced read-only route display with editable tier assignment UI
  - 4 dropdowns: primary/light/strong(optional)/embedding
  - Save button calls `updateModelTiers()`
  - Auto-refreshes tiers after adding a new model

## Additional Fix: Celery Event Loop Isolation

- [x] **Task 10: Fix "Future attached to a different loop"**
  - `backend/app/worker/tasks/content_ingestion.py`
  - Celery tasks now create their own `engine` + `session_factory` per invocation
  - Avoids sharing FastAPI's module-level engine across event loops
  - Engine disposed in `finally` block after task completes

## Files Modified

| File | Change |
|------|--------|
| `backend/alembic/versions/942f0ec50aae_*.py` | NEW — migration |
| `backend/app/db/models/model_config.py` | ModelRouteConfig → ModelTierConfig |
| `backend/app/models/model_schemas.py` | Added ModelTier enum, tier schemas |
| `backend/app/services/llm/config.py` | Tier-based config methods |
| `backend/app/services/llm/router.py` | TASK_TIER_MAP, tier resolution, strong fallback |
| `backend/app/services/llm/__init__.py` | Export ModelTier |
| `backend/app/api/routes/model_routes.py` | /api/v1/model-tiers endpoint |
| `backend/app/api/routes/models.py` | Auto-assign to tiers on model creation |
| `backend/app/worker/tasks/content_ingestion.py` | Isolated engine per Celery task |
| `frontend/src/lib/api.ts` | Tier types + API functions |
| `frontend/src/app/settings/page.tsx` | Editable tier assignment UI |

## TODO: Follow-up Optimizations

### TODO 1: 错误信息安全化 — 不暴露堆栈到前端

**问题：** Celery 任务失败时，完整 Python traceback 直接经 `/api/v1/tasks/{id}` 返回给前端并渲染，既是安全风险也是 UX 问题。

**改动方向：**
- **后端 `content_ingestion.py` except 块：** 区分用户可见消息和内部堆栈。`error_message` 字段只存人类可读描述（如"内容分析失败，请检查模型配置"），完整堆栈只写 `logger.error()`
- **后端 `/api/v1/tasks/{id}`：** 返回的 `error` 字段只放脱敏后的描述，开发模式下可额外返回 `error_detail`
- **前端任务状态组件：** 错误展示用友好提示框，开发模式下可折叠展示详情

**核心文件：**
- `backend/app/worker/tasks/content_ingestion.py` — except 块
- `backend/app/api/routes/tasks.py` — 任务状态返回
- `frontend/src/app/import/page.tsx`（或对应的任务状态展示组件）

### TODO 2: 导入资料时预估解析时间

**问题：** 用户导入资料后只看到 "处理中"，不知道要等多久。应根据资料大小和模型处理能力给出预估时间。

**需要调研的点：**
- 各阶段（extract / analyze / generate_lessons / embed）的耗时如何量化？是否跟 chunk 数量线性相关？
- 不同模型（本地 Ollama vs 云端 API）处理速度差异巨大，如何纳入预估？
- 预估时间应在哪个时机计算？上传时（基于文件大小粗估）还是 extract 完成后（基于 chunk 数量精估）？
- 是否需要历史数据来校准？（记录每次任务各阶段耗时，用于后续预测）
- 前端如何展示？进度条 + 预估剩余时间？分阶段进度？

**方案待讨论后确定。**

## Unchanged Files (12 call sites, zero changes)

- `backend/app/api/routes/chat.py`
- `backend/app/api/routes/diagnostic.py`
- `backend/app/api/routes/exercises.py`
- `backend/app/api/routes/translations.py`
- `backend/app/agent/mentor.py`
- `backend/app/services/content_analyzer.py`
- `backend/app/services/course_generator.py`
- `backend/app/services/embedding.py`
- `backend/app/worker/tasks/content_ingestion.py` (call sites unchanged, only infra changed)
