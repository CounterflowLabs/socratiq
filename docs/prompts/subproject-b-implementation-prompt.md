# Sub-project B 实现 Prompt

将以下内容完整粘贴给 AI，作为开发指令。

---

## 角色与任务

你是一个高级 Python 后端工程师，需要按照已有的设计文档和实现计划，为 LearnMentor 项目实现 Sub-project B（内容摄入管线）。

## 开发模式

**REQUIRED SUB-SKILL:** Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

## 开发流程要求

请严格按照以下流程开发：

1. **先读实现计划**：阅读 `docs/superpowers/plans/2026-03-24-subproject-b-content-ingestion.md`，这是你的 **唯一执行蓝图**
2. **再读设计文档**：阅读 `docs/superpowers/specs/2026-03-24-subproject-b-content-ingestion-design.md`，作为实现的详细参考
3. **再读现有代码**：了解 Sub-project A 已实现的基础设施，避免重复造轮子
4. **按 Plan 的 Task 顺序执行**：每个 Task 有 bite-sized 的步骤，逐步完成
5. **TDD 优先**：每个模块先写测试，再写实现
6. **每完成一个 Task 就运行全部测试**，确保不破坏已有功能
7. **每完成一个 Task 就 commit**，commit message 格式参照 Plan 中的指引

## 必须阅读的文件

### 实现计划（执行蓝图）
```
docs/superpowers/plans/2026-03-24-subproject-b-content-ingestion.md
```

### 设计文档（详细参考）
```
docs/superpowers/specs/2026-03-24-subproject-b-content-ingestion-design.md
```

### 项目约定
```
CLAUDE.md  # 技术栈、代码风格、重要注意事项
```

### 必须了解的现有代码
```
backend/app/config.py                          # Settings，你需要扩展它
backend/app/services/llm/base.py               # UnifiedMessage, LLMResponse 等类型
backend/app/services/llm/router.py             # ModelRouter, TaskType — 你必须通过它调用 LLM
backend/app/services/llm/__init__.py           # 公共导出
backend/app/db/models/source.py                # Source ORM 模型
backend/app/db/models/course.py                # Course, CourseSource, Section ORM 模型
backend/app/db/models/concept.py               # Concept, ConceptSource ORM 模型
backend/app/db/models/content_chunk.py         # ContentChunk ORM 模型
backend/app/worker/celery_app.py               # Celery 实例
backend/app/api/deps.py                        # get_db, get_redis, get_model_router 依赖注入
backend/app/main.py                            # FastAPI app，你需要注册新 router
backend/tests/conftest.py                      # 测试基础设施
```

## 核心约束

1. **所有 LLM 调用必须通过 `services/llm/` 抽象层**，不能直接 import anthropic/openai SDK
2. **使用 `ModelRouter.get_provider(TaskType.CONTENT_ANALYSIS)` 做内容分析**
3. **使用 `ModelRouter.get_provider(TaskType.EMBEDDING)` 做向量计算**
4. **异步任务通过已有的 Celery 框架** (`app/worker/celery_app.py`)
5. **Python 3.12+，完整类型注解，Google 风格 docstring，Pydantic v2**
6. **测试中 mock 所有 LLM 调用**，不发真实 API 请求
7. **API key 永远不要硬编码**

## 新增依赖

在 `backend/pyproject.toml` 中添加：
```
"bilibili-api-python>=16.0",
"pymupdf>=1.24",
"python-multipart",
```

## 验证标准

每个 Task 完成后，运行以下命令确认：
```bash
cd backend
.venv/bin/python -m pytest -v                    # 全部测试通过
.venv/bin/python -m pytest tests/ --tb=short     # 无 import 错误
.venv/bin/python -c "from app.main import app"   # FastAPI 启动无报错
```

最终完成后，运行：
```bash
.venv/bin/python -m pytest -v --tb=short  # 所有测试通过（包括 Sub-project A 的 48 个）
```

## 开始开发

请先完整阅读 **实现计划**（`docs/superpowers/plans/2026-03-24-subproject-b-content-ingestion.md`），然后从 Task 1 开始，按计划逐步实现。每完成一个 Task，报告进度和测试结果。
