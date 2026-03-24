# LearnMentor — AI 驱动的自适应学习系统

## 项目概述

LearnMentor 是一个 AI Agent 驱动的个性化学习平台。核心理念：不是工具，是导师。
它拥有持续演化的学生画像、任意内容摄入、苏格拉底式教学引导和主动知识探索能力。

## 技术栈

- **Frontend**: Next.js 14+ (App Router) · React · TypeScript · Tailwind CSS · shadcn/ui · Monaco Editor · D3.js
- **Backend**: Python 3.12+ · FastAPI · Pydantic v2 · SQLAlchemy (async) · Alembic
- **AI/Agent**: Anthropic Claude API (tool use + streaming) · Agent loop with multi-tool calling
- **Database**: PostgreSQL 16 + pgvector · Redis (cache + task queue)
- **Infra**: Docker Compose · Celery + Redis (async tasks) · MinIO (file storage)
- **Testing**: pytest (backend) · Vitest + Testing Library (frontend)

## 项目结构

```
learnmentor/
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
4. **模型路由**：70% Haiku (轻量任务) / 20% Sonnet (主交互) / 10% Opus (复杂推理) 控制成本
5. **流式输出**：SSE (Server-Sent Events) 实现 LLM 逐字输出到前端

## MVP 开发范围 (Phase 1, 9 周)

P0 必做：
- [ ] YouTube 字幕提取 + LLM 内容分析管线
- [ ] MentorAgent 核心循环 (Claude tool use + 苏格拉底式引导)
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

- Claude API key 通过环境变量 `ANTHROPIC_API_KEY` 注入，永远不要硬编码
- 所有用户数据必须隔离 (multi-tenant ready)
- LLM 调用必须有超时和重试机制
- 内容摄入是异步任务 (Celery)，前端轮询或 WebSocket 获取进度
- 向量 embedding 使用 OpenAI text-embedding-3-small (1536 维)
