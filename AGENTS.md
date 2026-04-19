# Socratiq — AI 驱动的自适应学习系统

## 项目概述

Socratiq 是一个 AI Agent 驱动的个性化学习平台。核心理念：不是工具，是导师。
它拥有持续演化的学生画像、任意内容摄入、苏格拉底式教学引导和主动知识探索能力。

## 技术栈

- **Frontend**: Next.js 14+ (App Router) · React · TypeScript · Tailwind CSS · shadcn/ui · Monaco Editor · D3.js
- **Backend**: Python 3.12+ · FastAPI · Pydantic v2 · SQLAlchemy (async) · Alembic
- **AI/Agent**: 多 LLM Provider 支持 (见下方 LLM 抽象层设计) · Agent loop with multi-tool calling
- **Database**: PostgreSQL 16 + pgvector · Redis (cache + task queue)
- **Infra**: Docker Compose · Celery + Redis (async tasks) · MinIO (file storage)
- **Testing**: pytest (backend) · Vitest + Testing Library (frontend)

## 项目结构

```
socratiq/
├── frontend/                   # Next.js App Router
│   ├── app/                    # Pages & layouts
│   │   ├── (auth)/             # Auth pages
│   │   ├── (app)/              # Main app shell
│   │   │   ├── dashboard/
│   │   │   ├── courses/[id]/
│   │   │   ├── learn/[sectionId]/
│   │   │   └── settings/
│   │   ├── layout.tsx
│   │   └── page.tsx            # Landing
│   ├── components/
│   │   ├── ui/                 # shadcn/ui primitives
│   │   ├── mentor-chat/        # Tutor chat panel (SSE streaming)
│   │   ├── video-player/       # YouTube/Bilibili embed with chapter sync
│   │   ├── code-editor/        # Monaco-based lab editor
│   │   ├── knowledge-graph/    # D3.js concept visualization
│   │   └── exercises/          # Quiz/exercise components
│   ├── lib/
│   │   ├── api.ts              # API client (fetch wrapper)
│   │   └── stores/             # Zustand stores
│   ├── package.json
│   └── tsconfig.json
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI app entry
│   │   ├── api/
│   │   │   └── routes/         # courses, chat, labs, exercises, sources
│   │   ├── agent/
│   │   │   ├── mentor.py       # MentorAgent core loop
│   │   │   ├── course_agent.py
│   │   │   ├── lab_agent.py
│   │   │   ├── eval_agent.py
│   │   │   ├── explorer.py     # ProactiveExplorer
│   │   │   └── prompts/        # System prompt templates
│   │   ├── tools/
│   │   │   ├── extractors/     # YouTube, Bilibili, PDF, MD, URL
│   │   │   ├── search.py
│   │   │   ├── code_runner.py
│   │   │   ├── knowledge.py
│   │   │   └── profile.py
│   │   ├── memory/
│   │   │   ├── manager.py      # MemoryManager (5-layer retrieval)
│   │   │   ├── episodic.py
│   │   │   ├── progress.py
│   │   │   └── metacognitive.py
│   │   ├── models/             # Pydantic schemas
│   │   ├── db/                 # SQLAlchemy models + Alembic migrations
│   │   └── services/           # embedding, llm client, celery tasks
│   ├── tests/
│   ├── pyproject.toml
│   └── alembic.ini
├── sandbox/                    # Docker sandbox images for code execution
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
└── README.md
```

## 核心架构决策

1. **多 Agent 协作**：MentorAgent 是用户唯一交互入口，按需调度 CourseAgent / LabAgent / EvalAgent
2. **5 层记忆体系**：工作记忆 → 学生画像 → 情节记忆 → 内容记忆 → 进度记忆 + 元认知记忆
3. **统一内容摄入**：所有来源 → ContentChunk → LLM 结构化分析 → 知识库 (pgvector RAG)
4. **模型路由**：按任务复杂度路由到不同模型/Provider，控制成本与质量平衡
5. **流式输出**：SSE (Server-Sent Events) 实现 LLM 逐字输出到前端
6. **LLM Provider 抽象层**：不锁死任何单一供应商，支持灵活切换和混合使用

## LLM 抽象层设计（关键架构）

### 设计原则

系统必须支持多 LLM Provider，通过统一抽象层屏蔽各家 API 差异。用户可在设置中配置 Provider 和模型，系统按任务类型智能路由。

### 支持的 Provider 类型

| Provider 类型 | 协议规范 | 示例 |
|--------------|---------|------|
| **Anthropic 原生** | Anthropic Messages API | Codex Sonnet/Haiku/Opus |
| **OpenAI 原生** | OpenAI Chat Completions API | GPT-4o, GPT-4o-mini, o1/o3 |
| **OpenAI 兼容** | OpenAI API 规范的第三方实现 | DeepSeek, Qwen (通义千问), GLM (智谱), Moonshot (月之暗面), Groq, Together AI, Fireworks, Mistral |
| **本地推理** | OpenAI 兼容 endpoint | Ollama (localhost), vLLM, llama.cpp server, LM Studio |

### 项目结构（LLM 相关）

```
backend/app/services/llm/
├── __init__.py
├── base.py              # LLMProvider 抽象基类 + 统一消息格式
├── anthropic.py         # Anthropic Messages API 实现
├── openai_compat.py     # OpenAI Chat Completions API 实现（含所有兼容 Provider）
├── router.py            # 模型路由器：按任务类型 + 用户配置选择 Provider/Model
├── config.py            # Provider 配置管理（从 DB / env 加载）
└── adapters/
    ├── tool_adapter.py  # 统一 tool use：Anthropic tool_use ↔ OpenAI function_calling 双向转换
    └── stream_adapter.py # 统一流式输出：不同 Provider 的 SSE chunk 归一化
```

### 核心抽象接口

```python
class LLMProvider(ABC):
    """所有 LLM Provider 的统一接口"""

    @abstractmethod
    async def chat(self, messages, tools, stream, **kwargs) -> LLMResponse: ...

    @abstractmethod
    async def chat_stream(self, messages, tools, **kwargs) -> AsyncIterator[StreamChunk]: ...

    @abstractmethod
    def supports_tool_use(self) -> bool: ...

    @abstractmethod
    def supports_streaming(self) -> bool: ...
```

### 统一消息格式

内部使用统一的消息格式，在 Provider 边界做转换：

```python
# 内部统一格式 (不绑定任何 Provider)
class UnifiedMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool_result"]
    content: str | list[ContentBlock]
    tool_calls: list[ToolCall] | None = None
    tool_results: list[ToolResult] | None = None

# Adapter 负责双向转换
# UnifiedMessage ←→ Anthropic Messages API format
# UnifiedMessage ←→ OpenAI Chat Completions API format
```

### Tool Use 兼容策略

这是最关键的兼容难点——Anthropic 和 OpenAI 的 tool use 格式不同：

- **Anthropic**: `tools` 参数 + `tool_use` content block + `tool_result` 消息
- **OpenAI**: `functions`/`tools` 参数 + `function_call`/`tool_calls` in message + `tool` role 消息
- **不支持 tool use 的模型**: 退化为 prompt 注入（把 tool schema 写进 system prompt，解析 JSON 输出）

`tool_adapter.py` 统一处理这三种情况，Agent 层不感知差异。

### 模型路由策略

```python
class ModelRouter:
    """按任务类型和用户配置路由到最优 Provider/Model"""

    async def route(self, task_type: TaskType, user_config: UserLLMConfig) -> ProviderModel:
        # 用户可配置的优先级：
        # 1. 用户指定了特定模型 → 直接使用
        # 2. 用户配置了 Provider 偏好 → 在该 Provider 内选择
        # 3. 走默认路由策略

        # 默认路由策略示例（可被用户配置覆盖）:
        # - 主教学交互 (mentor chat)      → 用户配置的主模型
        # - 内容分析/摘要                  → 用户配置的轻量模型
        # - 复杂推理 (评估/诊断)            → 用户配置的强模型
        # - Embedding                      → 独立配置的 embedding 模型
```

### 用户配置方式

```python
class UserLLMConfig(BaseModel):
    """存储在用户 settings 中的 LLM 配置"""

    providers: list[ProviderConfig]  # 可配置多个 Provider

    # 按用途指定模型
    primary_model: str          # 主交互模型，如 "anthropic/Codex-sonnet-4-20250514"
    light_model: str            # 轻量任务，如 "openai/gpt-4o-mini" 或 "ollama/qwen2.5"
    strong_model: str | None    # 复杂推理（可选），如 "anthropic/Codex-opus-4-20250514"
    embedding_model: str        # Embedding，如 "openai/text-embedding-3-small"

class ProviderConfig(BaseModel):
    type: Literal["anthropic", "openai", "openai_compatible"]
    api_key: str | None         # 本地模型可为空
    base_url: str | None        # OpenAI 兼容 endpoint，如 "http://localhost:11434/v1"
    models: list[str]           # 该 Provider 下可用的模型列表
```

### 环境变量配置

```bash
# .env — 多 Provider 配置示例

# Anthropic (默认主模型)
ANTHROPIC_API_KEY=sk-ant-xxx

# OpenAI (用于 embedding + 备选)
OPENAI_API_KEY=sk-xxx

# DeepSeek (国内用户低成本选项)
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# 本地 Ollama (完全免费，隐私优先)
OLLAMA_BASE_URL=http://localhost:11434/v1

# 默认模型路由
LLM_PRIMARY_MODEL=anthropic/Codex-sonnet-4-20250514
LLM_LIGHT_MODEL=anthropic/Codex-haiku-4-20250414
LLM_STRONG_MODEL=anthropic/Codex-opus-4-20250514
LLM_EMBEDDING_MODEL=openai/text-embedding-3-small
```

### 开发优先级

1. **MVP 先实现 Anthropic + OpenAI 兼容层**（覆盖 90%+ 场景）
2. OpenAI 兼容层自动支持 DeepSeek / Qwen / Ollama 等所有 OpenAI 格式 Provider
3. Tool use adapter 是核心难点，优先做好 Anthropic ↔ OpenAI 的双向转换
4. 不支持 tool use 的小模型用 prompt 注入 fallback
5. 前端 Settings 页提供 Provider 配置 UI（Phase 2）

## MVP 开发范围 (Phase 1, 9 周)

P0 必做：
- [ ] YouTube 字幕提取 + LLM 内容分析管线
- [ ] MentorAgent 核心循环 (Codex tool use + 苏格拉底式引导)
- [ ] 学生画像 v1 (JSONB + 对话推断更新)
- [ ] 记忆体系 v1 (工作记忆 + 画像 + 基础进度)
- [ ] RAG 检索 (pgvector)
- [ ] 冷启动自适应诊断 (基于内容概念出题)
- [ ] 前端：导入 → 诊断 → 学习路径 → 视频+导师对话 → 练习 → 反馈
- [ ] 基础间隔重复

## 代码风格约定

### Python (Backend)
- 使用 async/await (FastAPI 原生异步)
- Pydantic v2 做所有数据校验
- 类型注解必须完整
- docstring 用 Google 风格
- 测试用 pytest + pytest-asyncio

### TypeScript (Frontend)
- 严格模式 (strict: true)
- 函数组件 + hooks
- Zustand 做状态管理 (非 Redux)
- API 调用统一走 lib/api.ts
- 组件文件用 kebab-case

## 重要注意事项

- **所有 API key 通过环境变量注入，永远不要硬编码**（ANTHROPIC_API_KEY, OPENAI_API_KEY, 等）
- **Agent 层和业务层不直接调用任何 Provider SDK**，必须通过 `services/llm/` 抽象层
- 所有用户数据必须隔离 (multi-tenant ready)
- LLM 调用必须有超时和重试机制（抽象层统一处理）
- 内容摄入是异步任务 (Celery)，前端轮询或 WebSocket 获取进度
- Embedding 模型可配置，默认 OpenAI text-embedding-3-small (1536 维)，也支持本地 embedding
