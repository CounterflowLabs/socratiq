# Pipeline Split: Content Ingestion vs Course Generation

## Problem

当前 ingestion pipeline 混合了两个不同层次的工作：

```
Extract → Analyze → Generate Lessons → Generate Labs → Store → Embed
```

问题：
1. **Lessons/Labs 和 Embed 无关** — Embed 的输入是 chunks/concepts（来自 Analyze），和 lessons/labs 无关，但被卡在后面
2. **Lessons/Labs 应该根据学习目标定制** — 用户选了 goal（overview/master/apply），但 pipeline 不感知 goal
3. **去重范围不对** — clone_source 克隆了整个 source.metadata_（含 lessons/labs），但 lessons/labs 应该按 goal 独立生成

## Design

### Pipeline 拆分为两层

**层 1：内容摄取 `ingest_source`（可去重/克隆）**
```
Extract → Analyze → Store chunks/concepts → Embed → DONE
```
- 确定性：同内容同结果
- 产出：chunks（含 embedding）、concepts（含 embedding）、raw_content、analysis metadata（overall_summary, difficulty, concept_count, chunk_count 等）
- `source.metadata_` 不再存 `lesson_by_page` / `labs_by_page`

**层 2：课程生成 `generate_course_task`（按 goal 独立，Celery 异步）**
```
Generate Lessons(goal) → Generate Labs(goal) → 组装 Course + Sections + Labs → DONE
```
- 输入：source_id + goal
- 读取已存储的 chunks/concepts
- 根据 goal 定制 lesson/lab prompt
- 产出：Course + Sections（含 lesson content）+ Labs

### Celery Chain

导入时用 Celery chain 串联两层，前端只看到一个连续进度：

```python
from celery import chain
pipeline = chain(
    ingest_source.s(source_id),
    generate_course_task.s(goal=goal, user_id=user_id),
)
pipeline.delay()
```

`ingest_source` 完成后自动触发 `generate_course_task`，前端轮询看到连续的阶段：
```
extracting → analyzing → storing → embedding → generating_lessons → generating_labs → SUCCESS
```

### Goal 传递

- Goal 作为 Celery task 参数在 chain 中传递
- Goal 最终存到 Course 表（新增 `goal` 字段）
- 前端 import 页面把 goal 传给 `createSourceFromURL` / `createSourceFromFile`
- API 层把 goal 写入 Source.metadata_ 或直接传给 chain

### DB 变更

**Course 表新增：**
- `goal: String, nullable=True` — 学习目标（overview/master/apply）

### 文件变更

| 文件 | 变更 |
|------|------|
| `backend/app/worker/tasks/content_ingestion.py` | 删除 steps 3-4（lessons/labs），pipeline 在 embed 后结束；调整 `update_state` 阶段；重排 store 到 embed 前面 |
| `backend/app/worker/tasks/course_generation.py` | **新建**：`generate_course_task` Celery task，包含 lessons/labs 生成 + 课程组装 |
| `backend/app/services/course_generator.py` | 重构：接收 goal 参数，内部调 LessonGenerator/LabGenerator（带 goal prompt），不再从 source.metadata_ 读 lesson/lab |
| `backend/app/services/lesson_generator.py` | 扩展：接收 goal 参数，根据 goal 调整 prompt（overview=简洁摘要，master=详细讲解，apply=实操步骤） |
| `backend/app/services/lab_generator.py` | 扩展：接收 goal 参数，overview 不生成 lab，master 生成基础练习，apply 生成完整项目式 lab |
| `backend/app/db/models/course.py` | Course 加 `goal` 字段 |
| `backend/app/models/course.py` | CourseGenerateRequest 加 `goal` 字段 |
| `backend/app/api/routes/sources.py` | `create_source` 接收 `goal` 参数，传入 Celery chain |
| `backend/app/api/routes/courses.py` | `generate_course` 接收 `goal` 参数 |
| `backend/app/worker/celery_app.py` | 注册新 task 模块 |
| `frontend/src/lib/api.ts` | `createSourceFromURL`/`createSourceFromFile` 传 goal；task status 类型更新 |
| `frontend/src/app/import/page.tsx` | 把 goal 传给 API |
| `frontend/src/app/page.tsx` | 不再手动调 `generateCourse`（chain 自动触发） |

### Goal 对 Lesson/Lab 的影响

| Goal | Lesson 风格 | Lab 行为 |
|------|------------|---------|
| `overview` | 简洁摘要，抓核心要点，跳过细节 | 不生成 lab |
| `master` | 详细讲解，逐概念展开，含示例 | 生成基础练习（填空、选择） |
| `apply` | 实操导向，步骤化，侧重 how-to | 生成完整项目式 lab（starter code + tests） |

这通过修改 LessonGenerator/LabGenerator 的 system prompt 实现，注入 goal 上下文。

### Clone 影响

`clone_source` 只克隆内容层结果：
- chunks（text + embedding + metadata_）
- concepts（via ConceptSource）
- source.raw_content
- source.metadata_（不含 lesson/lab，因为 source 上不再存）

课程生成在 clone 之后独立运行（chain 的第二步），按 User B 自己的 goal 生成。

### 前端流程变化

**当前：**
```
import(goal选了但没传) → ingest(async) → 轮询 → 成功 → generateCourse(同步API) → 跳转
```

**重构后：**
```
import(传goal) → chain(ingest → generate_course)(async) → 轮询连续进度 → 成功 → 跳转
```

Dashboard 不再手动调 `generateCourse` — chain 自动完成。ingest 成功后 chain 自动进入 course generation。

### 不改的

- LessonGenerator/LabGenerator 的核心生成逻辑（只加 goal prompt 注入）
- 去重基础设施（content_key、ref_source、Redis subscriber）
- EmbeddingService
- ContentAnalyzer
