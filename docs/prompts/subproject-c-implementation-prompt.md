# Sub-project C 实现 Prompt

将以下内容完整粘贴给 AI，作为开发指令。

---

## 角色与任务

你是一个全栈工程师（Python + TypeScript），需要按照已有的设计文档和实现计划，为 Socratiq 项目实现 Sub-project C（MentorAgent 核心 + Next.js 前端）。

## 开发模式

**REQUIRED SUB-SKILL:** Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

## 前置条件

Sub-project A（基础设施）必须已实现。Sub-project B（内容摄入）推荐但非必须。在开始前确认：
```bash
cd backend && .venv/bin/python -m pytest -v  # 所有测试通过
```

## 开发流程要求

1. **先读实现计划**：阅读 `docs/superpowers/plans/2026-03-24-subproject-c-agent-frontend.md`，这是你的 **唯一执行蓝图**
2. **再读设计文档**：阅读 `docs/superpowers/specs/2026-03-24-subproject-c-agent-frontend-design.md`，作为实现的详细参考
3. **再读现有代码**：了解 Sub-project A 和 B 已实现的内容
4. **按 Plan 的 Task 顺序执行**：Task 1-9 后端，Task 10-18 前端
5. **后端先行**：先完成 Task 1-9（Agent 核心 + Chat API），再做 Task 10-18（前端）
6. **TDD 优先**：每个模块先写测试，再写实现
7. **每完成一个 Task 就运行全部测试 + commit**

## 必须阅读的文件

### 实现计划（执行蓝图）
```
docs/superpowers/plans/2026-03-24-subproject-c-agent-frontend.md
```

### 设计文档（详细参考）
```
docs/superpowers/specs/2026-03-24-subproject-c-agent-frontend-design.md
```

### 项目约定
```
CLAUDE.md  # 技术栈、代码风格约定、前后端规范
```

### 必须了解的后端现有代码
```
backend/app/services/llm/base.py               # UnifiedMessage, ToolDefinition, StreamChunk, LLMProvider
backend/app/services/llm/router.py             # ModelRouter, TaskType — Agent 必须通过它调用 LLM
backend/app/services/llm/__init__.py           # 公共导出
backend/app/db/models/user.py                  # User（含 student_profile JSONB）
backend/app/db/models/conversation.py          # Conversation
backend/app/db/models/message.py               # Message
backend/app/db/models/content_chunk.py         # ContentChunk（含 embedding Vector）
backend/app/db/models/concept.py               # Concept
backend/app/db/models/learning_record.py       # LearningRecord
backend/app/api/deps.py                        # get_db, get_model_router 等依赖
backend/app/main.py                            # FastAPI app
backend/app/config.py                          # Settings
backend/tests/conftest.py                      # 测试基础设施
```

### Sub-project B 的代码（如果已实现）
```
backend/app/tools/extractors/                  # 内容提取器
backend/app/services/content_analyzer.py       # 内容分析
backend/app/services/embedding.py              # Embedding 服务
backend/app/services/course_generator.py       # 课程生成
backend/app/api/routes/sources.py              # Sources API
backend/app/api/routes/courses.py              # Courses API
```

## 核心约束

### 后端
1. **MentorAgent 必须通过 `ModelRouter.get_provider(TaskType.MENTOR_CHAT)` 调用 LLM**
2. **RAG 查询通过 `ModelRouter.get_provider(TaskType.EMBEDDING)` 计算 query embedding**
3. **SSE 流式输出使用 `sse-starlette`**
4. **Agent tool 接口必须兼容 LLM 的 tool_use 格式**（通过 `ToolDefinition` 转换）
5. **学生画像存储在 `users.student_profile` JSONB 字段**，用 Pydantic 模型做验证
6. **异步画像更新用 `asyncio.create_task()`**，不阻塞响应
7. **Python 3.12+，完整类型注解，Google 风格 docstring，Pydantic v2**
8. **测试中 mock 所有 LLM 调用**

### 前端
1. **Next.js 14+ App Router**，TypeScript 严格模式
2. **Tailwind CSS + shadcn/ui**，暗色主题默认
3. **Zustand 做状态管理**（不用 Redux）
4. **API 调用统一走 `lib/api.ts`**
5. **SSE 客户端用 `eventsource-parser` + fetch**（因为需要 POST 请求）
6. **组件文件用 kebab-case**
7. **函数组件 + hooks**

## 新增依赖

后端（添加到 `backend/pyproject.toml`）：
```
"sse-starlette",
"numpy",
```

前端（在 `frontend/` 目录初始化）：
```bash
npx create-next-app@latest frontend --typescript --tailwind --eslint --app --src-dir=false --import-alias="@/*" --use-npm
cd frontend
npm install zustand eventsource-parser react-markdown remark-gfm
npx shadcn@latest init
npx shadcn@latest add button input card dialog scroll-area badge tabs separator skeleton avatar dropdown-menu sheet textarea toast
```

## 实现顺序

**必须按此顺序**（对应 Plan 中的 Task）：
1. **Task 1-5**: Agent 核心（AgentTool base + Profile service + Tools + Prompts + MentorAgent）
2. **Task 6-9**: Chat API + RAG 服务（RAG service + Chat SSE endpoint + Courses API + Routers）
3. **Task 10-12**: Next.js 前端骨架（项目初始化 + API client + SSE + 布局）
4. **Task 13-14**: 导入页 + 课程页
5. **Task 15-16**: 学习页（Bilibili 播放器 + Mentor Chat 面板）
6. **Task 17-18**: Settings 页 + 端到端验证

## 验证标准

每个后端 Task 完成后：
```bash
cd backend && .venv/bin/python -m pytest -v  # 全部测试通过
```

每个前端 Task 完成后：
```bash
cd frontend && npm run build  # 构建成功无错误
```

最终联调：
```bash
# Terminal 1: 启动后端
cd backend && .venv/bin/uvicorn app.main:app --reload

# Terminal 2: 启动前端
cd frontend && npm run dev

# 浏览器打开 http://localhost:3000，验证完整流程
```

## Commit 规范

```
feat(agent): <描述>       # Task 1-9
feat(frontend): <描述>    # Task 10-18
```

## 开始开发

请先完整阅读 **实现计划**（`docs/superpowers/plans/2026-03-24-subproject-c-agent-frontend.md`），然后从 Task 1 开始。每完成一个 Task，报告进度和测试结果。
