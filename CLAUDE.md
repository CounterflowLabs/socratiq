# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Socratiq 是一个 AI Agent 驱动的个性化学习平台。核心理念：不是工具，是导师。
它拥有持续演化的学生画像、任意内容摄入、苏格拉底式教学引导和主动知识探索能力。

## 技术栈

- **Frontend**: Next.js 14+ (App Router) · React · TypeScript · Tailwind CSS · shadcn/ui · Monaco Editor · D3.js
- **Backend**: Python 3.12+ · FastAPI · Pydantic v2 · SQLAlchemy (async) · Alembic
- **AI/Agent**: 多 LLM Provider 支持 · Agent loop with multi-tool calling
- **Database**: PostgreSQL 16 + pgvector · Redis (cache + task queue)
- **Infra**: Docker Compose · Celery + Redis (async tasks) · MinIO (file storage)
- **Testing**: pytest + pytest-asyncio (backend) · Vitest + Testing Library (frontend)

## 常用开发命令

### Frontend (在 `frontend/` 目录下)

```bash
npm run dev          # Next.js dev server on :3000
npm run build        # Production build
npm run lint         # ESLint
npm run test         # Vitest (vitest run)
```

### Backend (在 `backend/` 目录下)

```bash
uv sync                                           # 安装依赖
uvicorn app.main:app --reload --reload-dir app --port 8000  # 开发服务器
pytest                                            # 运行全部测试
pytest tests/test_xxx.py                          # 运行单个测试文件
pytest -k "test_name"                             # 按名称匹配运行测试
celery -A app.worker.celery_app worker --loglevel=info  # Celery worker
alembic upgrade head                              # 应用数据库迁移
alembic revision --autogenerate -m "message"      # 生成新迁移
```

Backend pytest 配置了 `asyncio_mode = "auto"`，无需手动标注 async 测试。

### Docker (在仓库根目录)

```bash
docker compose up -d db redis   # 启动数据库+缓存
docker compose up               # 启动全部服务
./start.sh                      # 一键开发环境启动
```

## 项目结构

```
frontend/src/
├── app/                    # Next.js App Router pages
│   ├── (auth)/             # 认证页面
│   ├── sources/            # 素材管理 (Materials Hub)
│   ├── learn/              # 学习主界面 (Learn Shell)
│   ├── diagnostic/         # 诊断评估
│   ├── exercise/           # 练习界面
│   ├── path/               # 学习路径
│   ├── import/             # 来源导入
│   └── settings/           # LLM 配置等
├── components/
│   ├── ui/                 # shadcn/ui 基础组件
│   ├── learn/              # Learn Shell 组件 (learn-shell, course-outline, study-aside)
│   ├── lesson/             # 课程渲染
│   │   ├── blocks/         # Block 类型专属渲染器
│   │   ├── lesson-block-renderer.tsx   # Block-based 课程渲染主入口
│   │   ├── mermaid-diagram.tsx         # Mermaid 图表 (动态导入, SSR=false)
│   │   └── mermaid-flow.ts             # 流程图解析工具
│   ├── materials/          # 素材管理组件
│   ├── lab/                # 实验编辑器
│   ├── knowledge-graph/    # D3.js 知识图谱
│   ├── mentor-chat/        # 导师对话 (SSE streaming)
│   └── video-player/       # YouTube/Bilibili 播放器
├── lib/
│   ├── api.ts              # 统一 API client + 类型定义
│   └── theme.ts            # 主题切换
└── __tests__/              # Vitest 测试

backend/app/
├── api/routes/             # FastAPI 路由 (courses, chat, labs, exercises, sources, knowledge_graph 等)
├── services/
│   ├── llm/                # LLM Provider 抽象层 (见下方详述)
│   ├── course_generator.py     # 课程组装 (从 sources 组装 course)
│   ├── lesson_generator.py     # 课时内容生成
│   ├── lab_generator.py        # 实验生成
│   ├── teaching_asset_planner.py  # 教学资产规划 (启发式匹配决定 lab_mode/graph_mode)
│   ├── content_analyzer.py     # LLM 内容结构化分析
│   ├── source_tasks.py         # 来源处理编排
│   ├── embedding.py / rag.py   # Embedding + RAG
│   └── spaced_repetition.py    # SM-2 间隔重复
├── agent/                  # Agent 系统 (mentor, course, lab, eval, explorer)
├── models/                 # Pydantic schemas (含 lesson_blocks.py 定义 block 类型)
├── db/models/              # SQLAlchemy ORM
├── worker/tasks/           # Celery 异步任务 (content_ingestion, course_generation)
├── tools/extractors/       # 内容提取器 (youtube, bilibili, pdf, markdown, url)
├── memory/                 # 5 层记忆体系 (manager, episodic, progress, metacognitive)
└── main.py                 # FastAPI 入口
```

## 核心架构

### Agent 协作模式
MentorAgent 是用户唯一交互入口，按需调度 CourseAgent / LabAgent / EvalAgent。Agent 层通过 `services/llm/` 抽象层调用 LLM，不直接使用任何 Provider SDK。

### 内容摄入 → 课程生成管线
1. 来源导入 → Extractor 提取内容 → ContentChunk
2. LLM 内容分析 (content_analyzer) → 结构化知识
3. TeachingAssetPlanner 规划教学资产 (lab_mode, graph_mode)
4. 课时/实验/图谱 在来源处理阶段一次性生成并持久化到 source metadata
5. course_generator 组装时直接复用已生成的资产

### Block-Based 课程渲染
课程内容以 block 数组组织，block 类型包括：`intro_card`, `prose`, `diagram`, `code_example`, `concept_relation`, `practice_trigger`, `recap`, `next_step`。旧版 section-based 课时通过 fallback adapter 自动转换为 block 格式。

### Learn Shell 布局
3 栏布局：outline (课程大纲) + lesson (课程内容) + study-aside (学习资源/进度)。移动端 aside 作为 overlay 展示。

### LLM 抽象层 (`services/llm/`)

统一接口屏蔽 Provider 差异：
- `LLMProvider` 抽象基类：`chat()`, `chat_stream()`, `embed()`
- `AnthropicProvider`: Anthropic Messages API
- `OpenAICompatProvider`: 覆盖 OpenAI / DeepSeek / Qwen / Ollama / Groq 等所有 OpenAI 兼容 Provider
- `CodexProvider`: Codex SDK wrapper
- `ModelRouter`: 按 TaskType (MENTOR_CHAT, CONTENT_ANALYSIS, EVALUATION, EMBEDDING) 路由
- Tool use adapter 处理 Anthropic tool_use ↔ OpenAI function_calling 双向转换
- 不支持 tool use 的模型退化为 prompt 注入 fallback
- 内部统一消息格式 `UnifiedMessage`，在 Provider 边界做转换

### 5 层记忆体系
工作记忆 → 学生画像 → 情节记忆 → 内容记忆 → 进度记忆 + 元认知记忆

## 代码风格约定

### Python (Backend)
- async/await (FastAPI 原生异步)
- Pydantic v2 做所有数据校验
- 类型注解必须完整
- docstring 用 Google 风格

### TypeScript (Frontend)
- 严格模式 (strict: true)
- 函数组件 + hooks
- Zustand 做状态管理
- API 调用统一走 `lib/api.ts`
- 组件文件用 kebab-case

## 重要约束

- **所有 API key 通过环境变量注入，不硬编码**
- **Agent 层和业务层不直接调用 Provider SDK**，必须通过 `services/llm/` 抽象层
- 所有用户数据必须隔离 (multi-tenant ready)
- LLM 调用必须有超时和重试（抽象层统一处理）
- 内容摄入是异步任务 (Celery)，前端轮询获取进度
- Mermaid 图表必须动态导入 (SSR=false)，渲染失败时 fallback 到原始语法展示
