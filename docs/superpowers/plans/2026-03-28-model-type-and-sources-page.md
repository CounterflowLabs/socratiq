# Embedding Model Separation + Sources Library Page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate embedding models from chat models in configuration, and add a sources library page showing all imported resources with their status.

**Architecture:** Feature A adds `model_type` column to `model_configs`, updates API/UI to filter by type, and validates tier assignments. Feature B creates a new `/sources` page using existing `GET /sources` API with sidebar navigation.

**Tech Stack:** Python (FastAPI, SQLAlchemy), Alembic, TypeScript (Next.js, Tailwind)

**Spec:** `docs/superpowers/specs/2026-03-28-model-type-and-sources-page-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/app/db/models/model_config.py` | Modify | Add `model_type` column |
| `backend/alembic/versions/XXXX_*.py` | Create | Migration |
| `backend/app/models/model_schemas.py` | Modify | Add `model_type` to schemas |
| `backend/app/api/routes/models.py` | Modify | Accept type on create, filter on list, fix auto-assign |
| `backend/app/api/routes/model_routes.py` | Modify | Validate tier-type matching |
| `frontend/src/lib/api.ts` | Modify | Add `model_type` to types, update `createModel` |
| `frontend/src/app/settings/page.tsx` | Modify | Type selector in add form, filter tier dropdowns |
| `frontend/src/app/sources/page.tsx` | Create | Sources library page |
| `frontend/src/components/sidebar.tsx` | Modify | Add "资料库" nav item |

---

### Task 1: Add `model_type` column to ModelConfig

**Files:**
- Modify: `backend/app/db/models/model_config.py`
- Modify: `backend/app/models/model_schemas.py`
- Create: Alembic migration

- [ ] **Step 1: Add column to ORM model**

In `backend/app/db/models/model_config.py`, add after `is_active` (line 24):

```python
model_type: Mapped[str] = mapped_column(String(20), server_default=text("'chat'"), nullable=False)
```

- [ ] **Step 2: Add to Pydantic schemas**

In `backend/app/models/model_schemas.py`, add `model_type` to `ModelConfigCreate`:

```python
class ModelConfigCreate(BaseModel):
    name: str = Field(..., description="Unique alias for this model")
    provider_type: str = Field(..., description="anthropic or openai_compatible")
    model_id: str = Field(..., description="Actual model identifier")
    api_key: str | None = Field(None, description="API key (will be encrypted)")
    base_url: str | None = Field(None, description="Custom API endpoint URL")
    model_type: str = Field("chat", description="'chat' or 'embedding'")
    supports_tool_use: bool = True
    supports_streaming: bool = True
    max_tokens_limit: int = 4096
```

Add `model_type` to `ModelConfigResponse`:

```python
class ModelConfigResponse(BaseModel):
    name: str
    provider_type: str
    model_id: str
    api_key_masked: str | None = None
    base_url: str | None = None
    model_type: str = "chat"
    supports_tool_use: bool
    supports_streaming: bool
    max_tokens_limit: int
    is_active: bool
```

- [ ] **Step 3: Generate and apply migration**

```bash
cd /home/tulip/project/socratiq/backend
uv run alembic revision --autogenerate -m "add model_type to model_configs"
uv run alembic upgrade head
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models/model_config.py backend/app/models/model_schemas.py backend/alembic/versions/*model_type*
git commit -m "feat: add model_type column to model_configs (chat/embedding)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Update models API — create with type, list with filter, fix auto-assign

**Files:**
- Modify: `backend/app/api/routes/models.py`

- [ ] **Step 1: Update list_models to support type filter**

Add `model_type` query param to `list_models`:

```python
@router.get("", response_model=list[ModelConfigResponse])
async def list_models(
    user: Annotated[User, Depends(get_local_user)],
    db: AsyncSession = Depends(get_db),
    manager: ModelConfigManager = Depends(_get_config_manager),
    model_type: str | None = None,
):
    query = select(ModelConfig).where(
        or_(ModelConfig.user_id == user.id, ModelConfig.user_id.is_(None))
    )
    if model_type:
        query = query.where(ModelConfig.model_type == model_type)
    query = query.order_by(ModelConfig.name)
    result = await db.execute(query)
    models = list(result.scalars().all())
    return [
        ModelConfigResponse(
            name=m.name,
            provider_type=m.provider_type,
            model_id=m.model_id,
            api_key_masked=manager.get_masked_api_key(m),
            base_url=m.base_url,
            model_type=m.model_type,
            supports_tool_use=m.supports_tool_use,
            supports_streaming=m.supports_streaming,
            max_tokens_limit=m.max_tokens_limit,
            is_active=m.is_active,
        )
        for m in models
    ]
```

- [ ] **Step 2: Update create_model to accept model_type and fix auto-assign**

In `create_model`, pass `model_type` through to the model. After `model.user_id = user.id`, set:

```python
    model.model_type = data.model_type
    await db.flush()
```

Replace the auto-assign block:

```python
    # Auto-assign to tiers that don't have a model yet (type-aware)
    existing_tiers = await manager.get_tier_configs(db)
    assigned_tiers = {c.tier for c in existing_tiers}

    if data.model_type == "embedding":
        if "embedding" not in assigned_tiers:
            await manager.update_tier_config(db, "embedding", model.name)
    else:
        for tier in ["primary", "light", "strong"]:
            if tier not in assigned_tiers:
                await manager.update_tier_config(db, tier, model.name)
```

Add `model_type` to the response:

```python
    return ModelConfigResponse(
        name=model.name,
        provider_type=model.provider_type,
        model_id=model.model_id,
        api_key_masked=manager.get_masked_api_key(model),
        base_url=model.base_url,
        model_type=model.model_type,
        supports_tool_use=model.supports_tool_use,
        supports_streaming=model.supports_streaming,
        max_tokens_limit=model.max_tokens_limit,
        is_active=model.is_active,
    )
```

Also add `model_type` to the response in `update_model`.

- [ ] **Step 3: Verify syntax**

```bash
uv run python -c "from app.api.routes.models import router; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/routes/models.py
git commit -m "feat: models API supports model_type filter, type-aware auto-assign

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Add tier-type validation to model_routes

**Files:**
- Modify: `backend/app/api/routes/model_routes.py`

- [ ] **Step 1: Add validation in update_tiers**

Update `update_tiers` to validate that embedding tier only gets embedding models and chat tiers only get chat models:

```python
from fastapi import HTTPException
from sqlalchemy import select
from app.db.models.model_config import ModelConfig

@router.put("", response_model=list[ModelTierResponse])
async def update_tiers(
    tiers: list[ModelTierUpdate],
    user: Annotated[User, Depends(get_local_user)],
    db: AsyncSession = Depends(get_db),
    manager: ModelConfigManager = Depends(_get_config_manager),
):
    results = []
    for t in tiers:
        # Validate model type matches tier
        model_result = await db.execute(
            select(ModelConfig).where(ModelConfig.name == t.model_name)
        )
        model = model_result.scalar_one_or_none()
        if not model:
            raise HTTPException(404, f"Model '{t.model_name}' not found")

        is_embedding_tier = t.tier == ModelTier.EMBEDDING
        is_embedding_model = model.model_type == "embedding"
        if is_embedding_tier != is_embedding_model:
            if is_embedding_tier:
                raise HTTPException(400, f"Embedding tier 只能使用向量模型，'{t.model_name}' 是对话模型")
            else:
                raise HTTPException(400, f"对话 tier 不能使用向量模型 '{t.model_name}'")

        c = await manager.update_tier_config(db, t.tier.value, t.model_name)
        results.append(ModelTierResponse(tier=c.tier, model_name=c.model_name))
    return results
```

Add `ModelTier` to the imports from model_schemas.

- [ ] **Step 2: Verify syntax**

```bash
uv run python -c "from app.api.routes.model_routes import router; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/routes/model_routes.py
git commit -m "feat: validate model type matches tier on tier assignment

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Update Settings page — type selector + filtered dropdowns

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/app/settings/page.tsx`

- [ ] **Step 1: Update frontend API types**

In `frontend/src/lib/api.ts`, add `model_type` to `ModelConfigResponse`:

```typescript
export interface ModelConfigResponse {
  name: string;
  provider_type: string;
  model_id: string;
  api_key_masked?: string;
  base_url?: string;
  model_type: string;
  supports_tool_use: boolean;
  supports_streaming: boolean;
  max_tokens_limit: number;
  is_active: boolean;
}
```

Add `model_type` to `createModel` data param:

```typescript
export async function createModel(data: {
  name: string;
  provider_type: string;
  model_id: string;
  api_key?: string;
  base_url?: string;
  model_type?: string;
}): Promise<ModelConfigResponse> {
```

- [ ] **Step 2: Update Settings page add-model form**

In `frontend/src/app/settings/page.tsx`, add `model_type` to the `newModel` state:

```typescript
  const [newModel, setNewModel] = useState({
    name: "",
    provider_type: "anthropic",
    model_id: "",
    api_key: "",
    base_url: "",
    model_type: "chat",
  });
```

Add a type selector in the add-model form (before the provider_type selector). This should be two radio buttons or a simple select:

```tsx
<div>
  <label className="block text-xs font-medium text-gray-600 mb-1">模型类型</label>
  <div className="flex gap-3">
    <label className="flex items-center gap-1.5 text-sm">
      <input type="radio" name="model_type" value="chat"
        checked={newModel.model_type === "chat"}
        onChange={() => setNewModel({ ...newModel, model_type: "chat" })}
      />
      对话模型
    </label>
    <label className="flex items-center gap-1.5 text-sm">
      <input type="radio" name="model_type" value="embedding"
        checked={newModel.model_type === "embedding"}
        onChange={() => setNewModel({ ...newModel, model_type: "embedding" })}
      />
      向量模型
    </label>
  </div>
</div>
```

- [ ] **Step 3: Filter tier dropdowns by model type**

In the tier assignment section, each tier dropdown should only show models matching that tier's type. The `TIER_INFO` array already has the tier names. For the embedding tier, filter to `model_type === "embedding"`; for other tiers, filter to `model_type === "chat"` (or `model_type !== "embedding"` for backward compat with existing models that don't have the field yet):

```tsx
const modelsForTier = (tier: ModelTier) =>
  models.filter((m) =>
    tier === "embedding" ? m.model_type === "embedding" : m.model_type !== "embedding"
  );
```

Use this in the dropdown `<select>`:

```tsx
<select value={tierEdits[tier]} onChange={...}>
  <option value="">未配置</option>
  {modelsForTier(tier).map((m) => (
    <option key={m.name} value={m.name}>{m.name}</option>
  ))}
</select>
```

- [ ] **Step 4: Add visual grouping**

Add a divider between chat tiers (primary/light/strong) and the embedding tier in the tier list. A simple `<hr>` or spacing with a label like "向量模型" before the embedding row.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/app/settings/page.tsx
git commit -m "feat: Settings page separates chat and embedding models in tier assignment

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Create Sources library page

**Files:**
- Create: `frontend/src/app/sources/page.tsx`
- Modify: `frontend/src/components/sidebar.tsx`

- [ ] **Step 1: Add "资料库" to sidebar**

In `frontend/src/components/sidebar.tsx`, add `Database` to the lucide import and add a nav item:

```typescript
import { Home, BookOpen, Search, BarChart3, ChevronLeft, ChevronRight, Brain, Settings, Menu, X, Database } from "lucide-react";

const items = [
  { id: "/", label: "首页", icon: Home },
  { id: "/import", label: "导入资料", icon: Search },
  { id: "/sources", label: "资料库", icon: Database },
  { id: "/settings", label: "设置", icon: Settings },
];
```

- [ ] **Step 2: Create sources page**

Create `frontend/src/app/sources/page.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Plus, Play, FileText, Loader, AlertCircle, CheckCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { listSources, type SourceResponse } from "@/lib/api";

const STATUS_CONFIG: Record<string, { label: string; color: string; bgColor: string }> = {
  pending: { label: "排队中", color: "text-blue-700", bgColor: "bg-blue-50" },
  extracting: { label: "提取中", color: "text-blue-700", bgColor: "bg-blue-50" },
  analyzing: { label: "分析中", color: "text-blue-700", bgColor: "bg-blue-50" },
  storing: { label: "存储中", color: "text-blue-700", bgColor: "bg-blue-50" },
  embedding: { label: "向量化", color: "text-blue-700", bgColor: "bg-blue-50" },
  waiting_donor: { label: "复用中", color: "text-purple-700", bgColor: "bg-purple-50" },
  generating_lessons: { label: "生成课文", color: "text-blue-700", bgColor: "bg-blue-50" },
  generating_labs: { label: "生成 Lab", color: "text-blue-700", bgColor: "bg-blue-50" },
  assembling_course: { label: "组装课程", color: "text-blue-700", bgColor: "bg-blue-50" },
  ready: { label: "已完成", color: "text-green-700", bgColor: "bg-green-50" },
  error: { label: "失败", color: "text-red-700", bgColor: "bg-red-50" },
};

function TypeIcon({ type }: { type: string }) {
  if (type === "bilibili") return <Play className="w-5 h-5 text-blue-500" />;
  if (type === "youtube") return <Play className="w-5 h-5 text-red-500" />;
  return <FileText className="w-5 h-5 text-gray-400" />;
}

function StatusBadge({ status }: { status: string }) {
  const config = STATUS_CONFIG[status] || { label: status, color: "text-gray-700", bgColor: "bg-gray-50" };
  const isProcessing = !["ready", "error"].includes(status);
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${config.color} ${config.bgColor}`}>
      {isProcessing && <Loader className="w-3 h-3 animate-spin" />}
      {status === "ready" && <CheckCircle className="w-3 h-3" />}
      {status === "error" && <AlertCircle className="w-3 h-3" />}
      {config.label}
    </span>
  );
}

export default function SourcesPage() {
  const router = useRouter();
  const [sources, setSources] = useState<SourceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    loadSources();
  }, []);

  async function loadSources() {
    setLoading(true);
    try {
      const res = await listSources();
      setSources(res.items);
      setTotal(res.total);
    } catch (e) {
      console.error("Failed to load sources:", e);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 pt-14 md:pt-6 pb-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-bold text-gray-900">资料库</h1>
            <p className="text-sm text-gray-500 mt-1">
              {total > 0 ? `共 ${total} 个资源` : "暂无导入的资源"}
            </p>
          </div>
          <Link href="/import">
            <Button size="sm">
              <Plus className="w-3.5 h-3.5" /> 导入新资料
            </Button>
          </Link>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16 text-gray-400">
            <Loader className="w-5 h-5 animate-spin mr-2" />
            <span className="text-sm">加载中...</span>
          </div>
        ) : sources.length === 0 ? (
          <Card className="p-10 text-center">
            <FileText className="w-10 h-10 text-gray-300 mx-auto mb-3" />
            <h3 className="text-base font-semibold text-gray-900 mb-2">还没有导入资料</h3>
            <p className="text-sm text-gray-500 mb-4">导入视频或 PDF 开始学习</p>
            <Link href="/import">
              <Button><Plus className="w-4 h-4" /> 导入第一份资料</Button>
            </Link>
          </Card>
        ) : (
          <div className="space-y-3">
            {sources.map((source) => (
              <Card key={source.id} className="p-4">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-xl bg-gray-50 flex items-center justify-center flex-shrink-0">
                    <TypeIcon type={source.type} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-medium text-gray-900 truncate">
                      {source.title || source.url || "未命名资源"}
                    </h3>
                    <div className="flex items-center gap-2 mt-1">
                      <StatusBadge status={source.status} />
                      <span className="text-xs text-gray-400">
                        {new Date(source.created_at).toLocaleDateString("zh-CN")}
                      </span>
                    </div>
                  </div>
                  <div className="flex-shrink-0">
                    {source.status === "error" && (
                      <Link href="/import">
                        <Button size="sm" variant="ghost">
                          <RefreshCw className="w-3.5 h-3.5" /> 重新导入
                        </Button>
                      </Link>
                    )}
                  </div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/sources/page.tsx frontend/src/components/sidebar.tsx
git commit -m "feat: add sources library page with status badges and sidebar navigation

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Integration verification

- [ ] **Step 1: Run backend tests**

```bash
cd /home/tulip/project/socratiq/backend
uv run pytest tests/ -v --tb=short 2>&1 | tail -20
```

- [ ] **Step 2: Verify imports**

```bash
uv run python -c "from app.api.routes.models import router; print('models OK')"
uv run python -c "from app.api.routes.model_routes import router; print('tiers OK')"
```

- [ ] **Step 3: Test model_type filter**

```bash
curl -s http://localhost:8000/api/v1/models?model_type=chat | python3 -m json.tool | head -5
curl -s http://localhost:8000/api/v1/models?model_type=embedding | python3 -m json.tool | head -5
```

- [ ] **Step 4: Commit fixups if needed**

---

## Self-Review

**Spec coverage:**
- ✅ ModelConfig.model_type column (Task 1)
- ✅ Create model with type (Task 2)
- ✅ List models with type filter (Task 2)
- ✅ Type-aware auto-assign (Task 2)
- ✅ Tier-type validation (Task 3)
- ✅ Settings page type selector + filtered dropdowns (Task 4)
- ✅ Sources library page `/sources` (Task 5)
- ✅ Sidebar nav entry (Task 5)
- ✅ Status badges with colors (Task 5)
- ✅ User isolation (existing `created_by` filter in `list_sources`)

**Placeholder scan:** No TBD/TODO found.

**Type consistency:** `model_type` field consistent across ORM (String), Pydantic schema (str), API response, and frontend interface. `ModelConfigResponse.model_type` matches everywhere.
