# Embedding 模型分离 + 资料库页面

## Feature A: Embedding 模型与 Chat 模型分离

### Problem

当前 `model_configs` 表不区分模型类型。Settings 页的 tier 下拉把所有模型混在一起——embedding 模型可以被分配到 primary tier，chat 模型可以被分配到 embedding tier，这在运行时会报错。

### Design

**DB：** `model_configs` 新增 `model_type` 列（`chat` 或 `embedding`，默认 `chat`）。

**API：**
- 创建模型时传 `model_type`
- `GET /models` 支持 `?type=chat` / `?type=embedding` 过滤
- Tier 分配校验：embedding tier 只接受 embedding 模型，其他 tier 只接受 chat 模型

**自动分配：**
- 创建第一个 chat 模型 → 自动绑到 primary / light / strong（所有未分配的 chat tier）
- 创建第一个 embedding 模型 → 自动绑到 embedding tier

**Settings 页：**
- 添加模型表单增加类型选择（对话模型 / 向量模型）
- Tier 区域视觉分组：上方 3 行 chat tier（主交互/轻量/复杂推理），下方 1 行 embedding tier
- 每个 tier 的下拉只显示对应类型的模型

### 涉及文件

| 文件 | 变更 |
|------|------|
| `backend/app/db/models/model_config.py` | `ModelConfig` 加 `model_type` 列 |
| `backend/alembic/versions/XXXX_*.py` | Migration |
| `backend/app/models/model_schemas.py` | Schema 加 `model_type` |
| `backend/app/api/routes/models.py` | 创建时接受 type，列表支持过滤，自动分配按 type 分开 |
| `backend/app/api/routes/model_routes.py` | Tier 更新校验 type 匹配 |
| `frontend/src/lib/api.ts` | 模型相关类型加 `model_type` |
| `frontend/src/app/settings/page.tsx` | 添加模型选类型，tier 下拉按类型过滤 |

---

## Feature B: 资料库页面

### Problem

Dashboard 只显示正在处理的任务，刷新后通过 `listActiveSources` 恢复。已完成和失败的 source 没有地方查看。用户无法回顾导入历史、重新导入失败的资料、或查看所有资料的状态。

### Design

**新页面 `/sources`** — 展示当前用户所有已导入的 source。

**后端 API：** 已有 `GET /api/v1/sources`（带分页，按 `created_by` 过滤），只需确认返回字段足够（status, title, type, content_key, created_at）。无需新建 API。

**页面布局：**
- 顶部：标题"资料库" + "导入新资料"按钮
- 列表：每个 source 一行卡片
  - 左侧：类型图标（B站蓝/YouTube红/PDF灰）
  - 中间：标题、状态标签（彩色 badge）、导入时间
  - 右侧：操作按钮
- 状态标签颜色：
  - 蓝色（进行中）：pending / extracting / analyzing / storing / embedding / waiting_donor
  - 绿色（完成）：ready
  - 红色（失败）：error
- 操作：
  - ready → "查看课程"按钮
  - error → "重新导入"按钮
  - 进行中 → 进度文字（复用 taskStateLabel）
- 排序：创建时间倒序
- 分页：滚动加载或分页按钮

**侧边栏：** 在 "导入资料" 和 "设置" 之间加 "资料库" 入口（图标：`FolderOpen` 或 `Database`）。

**用户隔离：** 后端 `list_sources` 已按 `created_by == user.id` 过滤，天然支持多租户。

### 涉及文件

| 文件 | 变更 |
|------|------|
| `frontend/src/app/sources/page.tsx` | 新建：资料库页面 |
| `frontend/src/components/sidebar.tsx` | 加"资料库"导航项 |
| `backend/app/api/routes/sources.py` | 确认 list_sources 返回 content_key（可选），无大改 |
| `backend/app/models/source.py` | SourceResponse 检查是否需要加 content_key 字段 |

### 不做的

- 搜索/筛选（MVP 后续加）
- 批量删除
- Source 详情页（点击进课程即可）
