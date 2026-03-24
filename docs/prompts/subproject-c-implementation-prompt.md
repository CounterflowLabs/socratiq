# Sub-project C 实现 Prompt

将以下内容完整粘贴给 AI，作为开发指令。

---

## 角色与任务

你是一个全栈工程师（Python + TypeScript），需要按照已有的设计文档和实现计划，为 LearnMentor 项目实现 Sub-project C（MentorAgent 核心 + Next.js 前端）。

## 前置条件

Sub-project A（基础设施）和 Sub-project B（内容摄入）必须已实现。在开始前确认：
```bash
cd backend && .venv/bin/python -m pytest -v  # 所有测试通过
```

## 开发流程要求

1. **先读设计文档**：阅读 `docs/superpowers/specs/2026-03-24-subproject-c-agent-frontend-design.md`，这是你的唯一实现规范
2. **再读现有代码**：了解 Sub-project A 和 B 已实现的内容
3. **按 Plan 分阶段执行**：设计文档末尾有 Phase C1-C6 的详细计划
4. **后端先行**：先完成 C1-C2（Agent 核心 + Chat API），再做 C3-C6（前端）
5. **TDD 优先**：每个模块先写测试，再写实现
6. **每完成一个 Phase 就运行全部测试 + commit**

## 必须阅读的文件

### 设计文档（实现规范）
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
npx create-next-app@latest frontend --typescript --tailwind --eslint --app --src-dir=false
cd frontend
npm install zustand eventsource-parser react-markdown
npx shadcn@latest init
```

## 实现顺序

**必须按此顺序**：
1. **Phase C1**: MentorAgent 核心（`agent/mentor.py` + tools + prompts）
2. **Phase C2**: Chat API + RAG 服务（SSE endpoint + pgvector 检索）
3. **Phase C3**: Next.js 前端骨架（项目初始化 + 路由 + 布局 + API client）
4. **Phase C4**: 导入页 + 课程页
5. **Phase C5**: 学习页（Bilibili 播放器 + Mentor Chat 面板）
6. **Phase C6**: Settings 页 + 端到端联调

## 验证标准

每个后端 Phase 完成后：
```bash
cd backend && .venv/bin/python -m pytest -v  # 全部测试通过
```

每个前端 Phase 完成后：
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
feat(agent): <描述>       # Phase C1-C2
feat(frontend): <描述>    # Phase C3-C6
```

每个 commit 末尾加：
```
Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

## 开始开发

请先完整阅读设计文档，然后从 Phase C1 开始。每完成一个 Phase，报告进度和测试结果。
