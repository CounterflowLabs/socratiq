# Socratiq Phase 2 — Production-Grade Full Design

**Date**: 2026-03-25
**Status**: Draft
**Scope**: 4 sub-projects (D/E/F/G), 9 feature modules, production-ready

---

## 0. Cross-Cutting Concerns

### 0.1 API Versioning

All new and existing routes move to `/api/v1/` prefix. The FastAPI app mounts a versioned router:

```python
app.include_router(v1_router, prefix="/api/v1")
# Legacy /api/* routes remain as aliases during transition, removed in Phase 3
```

### 0.2 Observability

| Layer | Tool | Scope |
|-------|------|-------|
| Structured logging | `structlog` | All backend, JSON format, correlation_id per request |
| Error tracking | Sentry SDK | Backend + Frontend, captures unhandled exceptions |
| LLM metrics | Custom middleware | Token usage, latency, error rate per task_type |
| Request tracing | correlation_id middleware | UUID per request, propagated through async flows |

Added in sub-project D since it touches every route.

### 0.3 LLM Cost Control

New table `llm_usage_logs`:

```sql
CREATE TABLE llm_usage_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    task_type VARCHAR(50) NOT NULL,  -- diagnostic, exercise_gen, grading, translation, memory
    model_name VARCHAR(100),
    tokens_in INTEGER,
    tokens_out INTEGER,
    estimated_cost_usd NUMERIC(10, 6),
    created_at TIMESTAMP DEFAULT now()
);
CREATE INDEX ix_usage_user_date ON llm_usage_logs(user_id, created_at);
```

Budget enforcement middleware:

```python
class CostGuard:
    async def check_budget(self, user_id: UUID, task_type: str) -> bool:
        """Check if user is within daily/monthly budget."""
        # Default limits: 10,000 tokens/day for light tasks, 50,000 for heavy
        # Configurable per user via user_settings JSONB

    async def log_usage(self, user_id, task_type, model, tokens_in, tokens_out): ...
```

For expensive operations (translation of full video), show estimated cost before user confirms.

### 0.4 Rate Limiting

Redis-based rate limiter on auth and LLM-triggering endpoints:

| Endpoint Group | Limit |
|---------------|-------|
| `/auth/*` | 10 req/min per IP |
| `/diagnostic/*`, `/exercises/generate` | 5 req/min per user |
| `/translate` | 3 req/min per user |
| General API | 60 req/min per user |

---

## Sub-project D: User Auth + Settings UI

### D1. Authentication Architecture

**BFF (Backend-for-Frontend) Pattern:**

```
Browser → Next.js Server (Auth.js session cookie)
    ↓
Next.js API routes proxy to FastAPI with JWT in server-side header
    ↓
FastAPI validates JWT → processes request
```

The browser NEVER touches JWT. Auth.js manages session via HttpOnly cookie. Next.js server holds the JWT and injects it when proxying API calls to FastAPI.

**Auth Flow:**

```
1. User clicks "Google 登录" / "GitHub 登录" / "邮箱登录"
    ↓
2. Auth.js handles OAuth flow or credentials verification
    ↓
3. Auth.js callback → POST /api/v1/auth/exchange
   Body: { provider: "google", id_token: "..." }
   Or:   { provider: "credentials", email: "...", password: "..." }
    ↓
4. Backend verifies token / credentials
   → Find or create User (upsert by oauth_provider + oauth_id, or email)
   → Sign JWT { user_id, email, exp }
    ↓
5. Auth.js stores JWT in encrypted server-side session
   → Sets HttpOnly session cookie for browser
    ↓
6. All subsequent API calls:
   Browser → Next.js server (cookie) → FastAPI (Authorization: Bearer <jwt>)
```

**Auth Methods (3 types):**

| Method | Provider | Notes |
|--------|----------|-------|
| Google OAuth | Auth.js GoogleProvider | 一键登录，最佳 UX |
| GitHub OAuth | Auth.js GithubProvider | 开发者用户 |
| 邮箱 + 密码 | Auth.js CredentialsProvider | 中国用户兜底，bcrypt hash |

### D2. Backend Auth Implementation

**New files:**

| File | Responsibility |
|------|---------------|
| `backend/app/api/routes/auth.py` | `/auth/exchange`, `/auth/refresh`, `/auth/register`, `/auth/me` |
| `backend/app/services/auth.py` | JWT signing/verification, password hashing, OAuth token validation |
| `backend/app/api/deps.py` (modify) | Add `get_current_user` dependency |

**API Endpoints:**

```
POST /api/v1/auth/register     — email + password registration
POST /api/v1/auth/exchange     — OAuth token → JWT exchange
POST /api/v1/auth/refresh      — refresh token → new access token
GET  /api/v1/auth/me           — current user profile
```

**JWT Structure:**

```python
# Access token (15 min)
{
    "sub": "user_uuid",
    "email": "user@example.com",
    "type": "access",
    "exp": 1711382400
}

# Refresh token (7 days)
{
    "sub": "user_uuid",
    "type": "refresh",
    "exp": 1711987200
}
```

**Token refresh handling:** Next.js server-side middleware intercepts 401 responses, calls `/auth/refresh`, updates session, retries the original request. The browser is unaware of token refresh.

**Dependencies:** `PyJWT`, `bcrypt`, `google-auth` (for id_token verification)

### D3. DB Changes

**User table migration:**

```sql
ALTER TABLE users ADD COLUMN oauth_provider VARCHAR(50);  -- "google", "github", NULL for email
ALTER TABLE users ADD COLUMN oauth_id VARCHAR(255);        -- provider-specific user ID
ALTER TABLE users ADD COLUMN avatar_url TEXT;
ALTER TABLE users ADD COLUMN hashed_password VARCHAR(255); -- NULL for OAuth-only users
ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT TRUE;

CREATE UNIQUE INDEX ix_users_oauth ON users(oauth_provider, oauth_id) WHERE oauth_provider IS NOT NULL;
CREATE UNIQUE INDEX ix_users_email ON users(email);
```

**Multi-tenant model_configs:**

```sql
ALTER TABLE model_configs ADD COLUMN user_id UUID REFERENCES users(id);
ALTER TABLE model_route_configs ADD COLUMN user_id UUID REFERENCES users(id);

-- System defaults have user_id = NULL
-- Per-user configs override system defaults
CREATE INDEX ix_model_configs_user ON model_configs(user_id);
```

ModelRouter resolution: user config → system default → error.

### D4. User Scoping Audit

ALL existing data-access routes must filter by `user_id`:

| Route | Current | Fix |
|-------|---------|-----|
| `GET /api/sources` | No filter | `WHERE created_by = current_user.id` |
| `GET /api/courses` | No filter | `WHERE created_by = current_user.id` |
| `GET /api/conversations` | Hardcoded DEMO_USER | `WHERE user_id = current_user.id` |
| `POST /api/chat` | Hardcoded DEMO_USER | Use `current_user.id` |
| `GET /api/models` | Global | `WHERE user_id = current_user.id OR user_id IS NULL` |
| `GET /api/model-routes` | Global | Same as models |

### D5. DEMO_USER Migration

On first real login, if only the demo user exists in the database:

```python
async def maybe_claim_demo_data(new_user_id: UUID, db: AsyncSession):
    """If demo user has data and only one user exists, offer to claim it."""
    DEMO_ID = UUID("00000000-0000-0000-0000-000000000001")
    demo_user = await db.get(User, DEMO_ID)
    if not demo_user:
        return

    # Transfer ownership of all demo data to the new user
    for table in [Source, Course, Conversation, LearningRecord]:
        await db.execute(
            update(table).where(table.user_id == DEMO_ID).values(user_id=new_user_id)
        )
    # Delete demo user
    await db.delete(demo_user)
    await db.commit()
```

Frontend shows a one-time prompt: "检测到已有学习数据，是否导入到你的账号？"

### D6. Settings UI

**Account Section:**
- Avatar (from OAuth provider) + display name + email
- Connected accounts (Google / GitHub) with connect/disconnect
- Password change (for email users)
- Logout button

**Model Configuration Section (enhanced):**
- "添加模型" button → modal form:
  - Provider type dropdown: Anthropic / OpenAI / OpenAI Compatible / Local (Ollama)
  - Model ID input
  - API Key input (masked, optional for local)
  - Base URL input (optional, for compatible/local)
  - "测试连接" button → inline result
  - "保存" button
- Existing model list (already implemented): test / delete
- Route configuration: each task type (主交互/内容分析/复杂推理/Embedding) has a dropdown to select from configured models

### D7. Frontend Auth Integration

**New files:**

| File | Responsibility |
|------|---------------|
| `frontend/src/app/api/auth/[...nextauth]/route.ts` | Auth.js route handler |
| `frontend/src/lib/auth.ts` | Auth.js config (providers, callbacks) |
| `frontend/src/components/auth-guard.tsx` | Protected route wrapper |
| `frontend/src/app/login/page.tsx` | Login page (OAuth buttons + email form) |

**api.ts changes:** All fetch calls go through Next.js API routes (BFF proxy) instead of directly to FastAPI:

```typescript
// Before: fetch("http://localhost:8000/api/sources")
// After:  fetch("/api/v1/sources")  ← Next.js proxies to FastAPI with JWT
```

Next.js `middleware.ts` redirects unauthenticated users to `/login`.

---

## Sub-project E: Learning Loop

### E1. Cold Start Diagnostic

**Flow:**

```
课程生成完成
    ↓
POST /api/v1/courses/{id}/diagnostic/generate
    ↓
DiagnosticAgent: LLM 根据课程 Concepts 生成 5 道选择题
    ↓
前端诊断页：卡片式答题
  - 每题 30-60 秒软计时（显示时间但不强制提交）
  - 动画过渡，进度指示器
  - 难度由浅入深（概念依赖排序）
    ↓
POST /api/v1/courses/{id}/diagnostic/submit
  Body: [{ question_id, selected_answer, time_spent_seconds }]
    ↓
LLM 评估 → 写入 StudentProfile.competency
  - 推断知识水平: beginner / intermediate / advanced
  - 标记已掌握/未掌握的概念
    ↓
302 → /path?courseId=X（学习路径已个性化排序）
```

**API:**

```
POST /api/v1/courses/{id}/diagnostic/generate → { questions: DiagnosticQuestion[] }
POST /api/v1/courses/{id}/diagnostic/submit   → { level, mastered_concepts[], gaps[] }
```

**DiagnosticQuestion schema:**

```python
class DiagnosticQuestion(BaseModel):
    id: str
    concept_id: UUID
    question: str
    options: list[str]  # 4 choices
    correct_index: int
    difficulty: int  # 1-5
```

**LLM Failure Handling:**
- Generation fails → skip diagnostic, redirect to learning path with default difficulty
- Frontend shows: "诊断题生成失败，将使用默认学习路径。你可以稍后在设置中重新诊断。"

### E2. Exercise Generation & Evaluation

**DB additions:**

```sql
CREATE TABLE exercise_submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    exercise_id UUID NOT NULL REFERENCES exercises(id),
    answer TEXT NOT NULL,          -- user's answer (JSON for MCQ, text for open/code)
    score NUMERIC(5, 2),           -- 0-100, NULL if not yet graded
    feedback TEXT,                  -- LLM-generated feedback
    graded_at TIMESTAMP,
    attempt_number INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT now()
);
CREATE INDEX ix_submissions_user ON exercise_submissions(user_id, created_at);
CREATE INDEX ix_submissions_exercise ON exercise_submissions(exercise_id);
```

**Agent Tools:**

```python
class ExerciseGenerateTool(AgentTool):
    """Generate exercises for a section based on content + student profile."""
    name = "generate_exercises"
    # Parameters: section_id, count (1-5), types (mcq/code/open)
    # Returns: list of Exercise objects saved to DB

class ExerciseEvalTool(AgentTool):
    """Evaluate a student's exercise submission."""
    name = "evaluate_exercise"
    # Parameters: submission_id
    # Returns: { score, feedback, concepts_mastered, concepts_weak }
```

**API:**

```
POST /api/v1/exercises/generate         → { exercises: Exercise[] }
POST /api/v1/exercises/{id}/submit      → { submission_id }
GET  /api/v1/exercises/{id}/submission   → { score, feedback, ... }
```

**Flow:**

```
MentorAgent 检测 Section 学完 → 调用 ExerciseGenerateTool
    ↓
生成 2-3 题（题型混合）→ 存入 exercises 表
    ↓
前端渲染：
  - MCQ: 选项卡片，选择后即时反馈（对/错 + 解释）
  - Code: Monaco Editor（桌面）/ 简化文本框（手机）
  - Open: 文本输入框 + 字数提示
    ↓
提交 → 先存 exercise_submissions（answer 不丢失）
    ↓
调 EvalAgent 评分 → 更新 submission.score + feedback
    ↓
更新 StudentProfile + 触发 SpacedRepetition
```

**LLM Failure Handling:**
- 生成失败 → MentorAgent 在对话中提问代替正式练习
- 评分失败 → 提交已保存，显示"评分中..."，后台重试（Celery delayed task），最多重试 3 次
- 评分超时 → 返回 "提交已保存，评分结果稍后通知"

**Frontend Exercise Page (重写):**
- 从占位页改为完整练习界面
- URL: `/exercise?courseId=X&sectionId=Y`
- 三种题型渲染组件
- 即时反馈动画（正确绿色弹出，错误红色 + 解释）
- 练习历史记录

### E3. Spaced Repetition (SM-2)

**DB:**

```sql
CREATE TABLE review_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    concept_id UUID NOT NULL REFERENCES concepts(id),
    exercise_id UUID REFERENCES exercises(id),  -- optional, linked exercise
    easiness NUMERIC(4, 2) DEFAULT 2.5,
    interval_days INTEGER DEFAULT 1,
    repetitions INTEGER DEFAULT 0,
    review_at TIMESTAMP NOT NULL DEFAULT now(),
    last_reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE(user_id, concept_id)
);
CREATE INDEX ix_review_user_due ON review_items(user_id, review_at);
```

**SM-2 Algorithm:**

```python
class SpacedRepetitionService:
    def update_review(self, item: ReviewItem, quality: int) -> ReviewItem:
        """Update review schedule after a review attempt.

        quality: 0-5 (0=complete blackout, 5=perfect recall)
        Uses optimistic locking: UPDATE ... WHERE repetitions = expected
        """
        if quality >= 3:
            if item.repetitions == 0:
                item.interval_days = 1
            elif item.repetitions == 1:
                item.interval_days = 6
            else:
                item.interval_days = round(item.interval_days * item.easiness)
            item.repetitions += 1
        else:
            item.repetitions = 0
            item.interval_days = 1

        item.easiness = max(1.3, item.easiness + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        item.review_at = now() + timedelta(days=item.interval_days)
        item.last_reviewed_at = now()
        return item

    async def get_due_reviews(self, user_id: UUID, limit: int = 20) -> list[ReviewItem]:
        """Get items due for review, ordered by urgency."""
        # SELECT ... WHERE user_id = ? AND review_at <= now() ORDER BY review_at LIMIT ?
```

**API:**

```
GET  /api/v1/reviews/due              → { items: ReviewItem[], count: int }
POST /api/v1/reviews/{id}/complete    → { quality: int } → updated ReviewItem
GET  /api/v1/reviews/stats            → { due_today, completed_today, streak_days }
```

**Concurrency:** `UPDATE review_items SET ... WHERE id = ? AND repetitions = ? RETURNING *` — if 0 rows affected, retry with fresh data.

**Frontend:**
- Dashboard 加「今日复习」卡片：显示待复习数量 + 连续天数
- 复习页面：flashcard 式 UI，翻转显示答案，自评 0-5
- MentorAgent 在对话开始时检查待复习项，主动提醒

**Triggers:** 练习评分完成后自动创建/更新 review_item（EvalAgent → SpacedRepetitionService）。

---

## Sub-project F: Deep Capabilities

### F1. Memory System (5-Layer)

**New tables:**

```sql
CREATE TABLE episodic_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    event_type VARCHAR(50) NOT NULL,  -- stuck, breakthrough, preference, mistake, aha_moment
    content TEXT NOT NULL,
    context JSONB DEFAULT '{}',       -- { course_id, section_id, concept_id, ... }
    importance NUMERIC(3, 2) DEFAULT 0.5,  -- 0.0 to 1.0
    embedding vector(1536),
    expires_at TIMESTAMP,             -- TTL: low-importance auto-expire after 90 days
    created_at TIMESTAMP DEFAULT now()
);
CREATE INDEX ix_episodic_user ON episodic_memories(user_id, importance DESC);
CREATE INDEX ix_episodic_expires ON episodic_memories(expires_at) WHERE expires_at IS NOT NULL;
-- Vector index for similarity search
CREATE INDEX ix_episodic_embedding ON episodic_memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE metacognitive_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    strategy VARCHAR(100) NOT NULL,     -- "code_first", "analogy", "visual", "step_by_step"
    effectiveness NUMERIC(3, 2),        -- 0.0 to 1.0
    context JSONB DEFAULT '{}',         -- { concept_category, difficulty, ... }
    evidence TEXT,                       -- what happened that suggests this
    created_at TIMESTAMP DEFAULT now()
);
CREATE INDEX ix_metacog_user ON metacognitive_records(user_id, effectiveness DESC);
```

**Memory Pruning:**
- Importance < 0.3 的情节记忆：`expires_at = created_at + 90 days`
- Importance >= 0.3 的：无过期
- Celery periodic task：每日清理过期记忆
- 录入阈值：importance < 0.2 的事件不录入

**Agent Tools:**

```python
class EpisodicMemoryTool(AgentTool):
    """Record and recall episodic memories."""
    name = "episodic_memory"
    # Actions: record(event_type, content, importance), recall(query, limit)
    # recall uses vector similarity on embedding

class MetacognitiveReflectTool(AgentTool):
    """Reflect on teaching strategy effectiveness."""
    name = "metacognitive_reflect"
    # After a learning session, LLM evaluates what worked
    # Records strategy + effectiveness to metacognitive_records
```

**MemoryManager 5-Layer Retrieval:**

```python
class MemoryManager:
    async def retrieve(self, user_id, query, context) -> MemoryContext:
        """Retrieve relevant memories across all layers."""
        return MemoryContext(
            working=self._get_recent_messages(context.conversation_id, limit=20),
            profile=await load_profile(user_id),
            episodic=await self._search_episodic(user_id, query, limit=5),
            content=await self._rag_search(query, context.course_id, limit=5),
            progress=await self._get_progress(user_id, context.course_id),
            metacognitive=await self._get_effective_strategies(user_id, context),
        )
```

MentorAgent 在每次对话开始时调 `MemoryManager.retrieve` 构建上下文，注入到 system prompt。

### F2. Subtitle Translation

**New table:**

```sql
CREATE TABLE translations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id UUID NOT NULL REFERENCES content_chunks(id),
    target_lang VARCHAR(10) NOT NULL,   -- "zh", "en", "ja"
    translated_text TEXT NOT NULL,
    model_used VARCHAR(100),
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE(chunk_id, target_lang)
);
CREATE INDEX ix_translations_chunk ON translations(chunk_id);
```

**Service:**

```python
class TranslationService:
    async def translate_section(self, section_id: UUID, target_lang: str, user_id: UUID) -> list[Translation]:
        """Translate all chunks in a section. Uses light_model for cost efficiency."""
        # 1. Check cache (translations table)
        # 2. For uncached chunks, batch translate via LLM
        # 3. Save to translations table
        # 4. Log usage to llm_usage_logs

    async def estimate_cost(self, section_id: UUID, target_lang: str) -> CostEstimate:
        """Estimate translation cost before user confirms."""
        # Count untranslated chunks, estimate tokens
```

**API:**

```
GET  /api/v1/sections/{id}/translate/estimate?target=zh → { chunks_total, chunks_cached, estimated_tokens, estimated_cost_usd }
POST /api/v1/sections/{id}/translate?target=zh          → { translations: Translation[] }
```

**Flow:**
1. 用户点击「翻译为中文」
2. 前端显示预估成本："约翻译 15 段文本，预计消耗 XX tokens"
3. 用户确认 → 开始翻译（Celery async task for long videos）
4. 前端轮询进度或 WebSocket 推送
5. 完成后双语显示：原文上方 + 译文下方

**LLM Failure Handling:**
- 单 chunk 翻译失败 → 跳过，标记为 failed，其余继续
- 前端显示已完成 / 总数 进度，失败的 chunk 显示原文

### F3. Knowledge Graph

**API:**

```
GET /api/v1/courses/{id}/knowledge-graph?max_depth=2 → { nodes: Node[], edges: Edge[] }
```

```python
class KnowledgeGraphNode(BaseModel):
    id: str  # concept UUID
    label: str  # concept name
    category: str | None
    mastery: float  # 0.0-1.0, from review_items + exercise_submissions
    section_id: str | None  # linked section for navigation

class KnowledgeGraphEdge(BaseModel):
    source: str  # concept UUID
    target: str  # prerequisite concept UUID
    relationship: str  # "prerequisite"
```

**Scope limiting:**
- 只返回该课程相关的概念（通过 ConceptSource → Source → CourseSource 关联）
- `max_depth` 参数限制前置依赖的递归深度（默认 2）
- 硬上限 200 节点，超过时按 importance/mastery 剪枝

**Mastery calculation:**

```python
async def calculate_mastery(user_id: UUID, concept_id: UUID) -> float:
    """Calculate concept mastery from review items + exercise submissions."""
    review = await get_review_item(user_id, concept_id)
    submissions = await get_submissions_for_concept(user_id, concept_id)

    if not review and not submissions:
        return 0.0  # 未接触

    review_score = review.easiness / 5.0 if review else 0.0
    exercise_score = avg(s.score for s in submissions) / 100.0 if submissions else 0.0

    return review_score * 0.4 + exercise_score * 0.6
```

**Frontend:**

```
frontend/src/components/knowledge-graph/
├── force-graph.tsx      # D3.js force-directed graph
├── graph-controls.tsx   # zoom, filter, layout toggle
└── concept-tooltip.tsx  # hover tooltip with mastery + description
```

- 节点颜色：红(0-0.3) → 黄(0.3-0.7) → 绿(0.7-1.0)
- 节点大小：按关联 section 数量
- 点击节点 → 跳转 `/learn?sectionId=X&courseId=Y`
- **手机端**：默认列表视图（概念名 + mastery bar），可选切换图谱
- **桌面端 200+ 节点**：按 category 聚类显示，点击展开

---

## Sub-project G: Mobile Responsive

### G1. Global Responsive Framework

Tailwind breakpoints:
- `< sm (640px)`: 手机竖屏
- `sm - md`: 手机横屏 / 小平板
- `md - lg`: 平板
- `lg+`: 桌面

### G2. Component Changes

| Component | Mobile (<md) | Desktop (md+) |
|-----------|-------------|----------------|
| **Sidebar** | 汉堡菜单 + slide-in overlay | 固定左侧 w-56 |
| **Learn 页** | Tab 切换（视频/聊天/笔记） | 左右分屏 3/5 + 2/5 |
| **Import 页** | 目标选项纵向排列 `grid-cols-1` | `grid-cols-3` |
| **诊断页** | 选项卡片全宽 | 卡片 2x2 grid |
| **练习页 MCQ** | 选项全宽按钮 | 选项卡片 grid |
| **练习页 Code** | 简化文本框 + 语法高亮（非 Monaco） | Monaco Editor |
| **知识图谱** | 列表视图（默认）+ 可选图谱 | D3 力导向图 |
| **Settings** | 单列表单 | 双列布局 |

### G3. Mobile Code Editor

Monaco Editor 在手机端不可用。替代方案：

```tsx
// components/code-editor/mobile-editor.tsx
// 使用 <textarea> + Prism.js 语法高亮预览
// 双面板：编辑（上）+ 预览（下）
// 用 CodeMirror 6 的移动端模式作为进阶选项
```

### G4. Network Resilience

SSE streaming 在移动网络容易中断：

```typescript
// lib/sse.ts — 增加断线重连
export async function* streamSSE(url, body) {
    let retries = 0;
    while (retries < 3) {
        try {
            // ... existing streaming logic
            break; // success, exit retry loop
        } catch (e) {
            retries++;
            if (retries < 3) {
                await new Promise(r => setTimeout(r, 1000 * retries));
            } else {
                throw e;
            }
        }
    }
}
```

### G5. Touch Optimization

- 所有可点击元素最小 44x44px 触摸区域
- Chat 输入框在移动端固定底部，键盘弹起不遮挡
- 诊断/练习选项间距加大，防止误触
- 下拉刷新支持（Dashboard 课程列表）

---

## DB Migration Summary

Phase 2 新增/修改的表：

| 表 | 操作 | Sub-project |
|----|------|-------------|
| `users` | ALTER: add oauth_provider, oauth_id, avatar_url, hashed_password, is_active | D |
| `model_configs` | ALTER: add user_id | D |
| `model_route_configs` | ALTER: add user_id | D |
| `llm_usage_logs` | CREATE | D |
| `exercise_submissions` | CREATE | E |
| `review_items` | CREATE | E |
| `episodic_memories` | CREATE | F |
| `metacognitive_records` | CREATE | F |
| `translations` | CREATE | F |

总计：3 ALTER + 6 CREATE = 9 个 migration

---

## Testing Strategy

### Backend Tests (per sub-project)

| Sub-project | Test Scope | Mock |
|-------------|-----------|------|
| D | Auth exchange, JWT verification, refresh, user scoping on all routes, model config multi-tenant | Mock OAuth token verification |
| E | Diagnostic generation + submission, exercise CRUD + submission, SM-2 calculation, concurrency | Mock LLM calls |
| F | Episodic memory CRUD + vector search, metacognitive recording, translation caching, knowledge graph query | Mock LLM + embedding |
| G | N/A (frontend only) | N/A |

### Frontend Tests

| Sub-project | Test Scope |
|-------------|-----------|
| D | Login page renders, auth guard redirects, settings form |
| E | Diagnostic card UI, exercise rendering (3 types), review flashcard |
| F | Knowledge graph renders nodes, translation toggle |
| G | Responsive breakpoints, hamburger menu, mobile learn tabs |

### Integration Tests (new)

- Full auth flow: register → login → access protected route → token refresh
- Full learning flow: import → diagnostic → learn → exercise → review

---

## Implementation Order

```
D (Auth + Settings)        → E (Learning Loop)         → F (Deep Capabilities)    → G (Mobile)
├── D1-D5: Backend auth    ├── E1: Diagnostic          ├── F1: Memory system       ├── G1-G5: CSS + components
├── D6: Settings UI        ├── E2: Exercise gen/eval   ├── F2: Translation
├── D7: Frontend auth      ├── E3: Spaced repetition   ├── F3: Knowledge graph
├── Observability setup    └── Cost guard integration   └── Memory pruning cron
└── User scoping audit
```

Each sub-project is independently deployable and testable.

---

## Phase 3 Backlog (Not in This Spec)

- ProactiveExplorer (主动知识探索 Agent)
- Code sandbox execution (Docker-based)
- Multi-user collaboration
- Mobile PWA / native app
- Analytics dashboard (learning metrics)
- Content marketplace (用户共享课程)
