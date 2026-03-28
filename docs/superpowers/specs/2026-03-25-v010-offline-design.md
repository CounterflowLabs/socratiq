# Socratiq v0.1.0 开源离线版设计

**Date**: 2026-03-25
**Status**: Approved
**Branch**: offline
**定位**: 导入 B 站编程教程合集 → 生成 learn.shareai.run 质量的交互式课程

---

## 1. 核心体验

```
用户粘贴 B 站合集 URL
    ↓ (2-3 分钟)
提取全部分 P 字幕 → LLM 分析结构/概念/代码 → 生成课程
    ↓
课程页面：
├── 结构化课文（字幕重组 + Mermaid 图 + 步骤分解 + 时间戳回跳）
├── 诊断题（基于内容的 MCQ）
├── Lab（代码骨架 + TODO + 测试 + 运行说明）
└── AI 导师（苏格拉底式辅导）
```

---

## 2. Docker Compose 全容器化

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    # ...existing
  redis:
    image: redis:7-alpine
    # ...existing
  backend:
    build: ./backend
    ports: ["8000:8000"]
    depends_on: [db, redis]
    env_file: .env
  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    depends_on: [backend]
    environment:
      - BACKEND_URL=http://backend:8000
```

新增文件：
- `backend/Dockerfile`
- `frontend/Dockerfile`
- `.env.example`

用户体验：
```bash
git clone https://github.com/CounterflowLabs/socratiq
cd socratiq
cp .env.example .env   # 编辑 LLM 配置（或跳过，首次启动引导）
docker compose up
# 打开 http://localhost:3000
```

---

## 3. B 站合集支持

当前 BilibiliExtractor 只处理单个视频。扩展支持合集：

**检测逻辑：**
- URL 包含 `?p=` 或是合集页 → 调 `video.get_info()` 获取 `pages` 列表
- 每个 page 有 `cid`, `part`(标题), `duration`

**处理流程：**
```
合集 URL → get_info() → pages[]
    ↓
每个 page 并行提取字幕（复用现有单 P 逻辑）
    ↓
每个 page 生成一个 Section（标题 = page.part）
    ↓
按合集顺序排列 → 生成 Course
```

**改动：**
- `BilibiliExtractor.extract()` 检测 pages > 1 时，循环提取每个 P 的字幕
- 返回 `ExtractionResult` 时，chunks 带 `page_index` metadata
- `CourseGenerator` 根据 page_index 分组创建 sections

---

## 4. 结构化课文生成

从 60s 字幕 chunks 生成结构化课文，不是 AI 编写而是提取重组。

**数据模型：**

```python
class LessonContent(BaseModel):
    """一个 Section 的结构化课文，存入 Section.content JSONB"""
    title: str
    summary: str                        # 1-2 句概述
    sections: list[LessonSection]

class LessonSection(BaseModel):
    heading: str                        # 小节标题
    content: str                        # 正文（字幕重组为书面语）
    timestamp: float                    # 视频时间点（秒）
    code_snippets: list[CodeSnippet]    # 提取的代码片段
    key_concepts: list[str]
    diagrams: list[Diagram]             # Mermaid 图
    interactive_steps: StepByStep | None  # 步骤分解

class CodeSnippet(BaseModel):
    language: str
    code: str
    context: str                        # 讲师对这段代码的解释

class Diagram(BaseModel):
    type: str          # "mermaid" | "comparison"
    title: str
    content: str       # Mermaid 语法 或 JSON 对比数据

class StepByStep(BaseModel):
    title: str
    steps: list[Step]

class Step(BaseModel):
    label: str
    detail: str
    code: str | None
```

**LLM Prompt 策略：**

输入：一个 Section 的所有 60s chunks（原始字幕文本）

指令：
1. 从字幕中提取小节结构（识别主题切换点 → heading）
2. 将口语化字幕重组为书面语正文，保留关键信息不编造
3. 识别代码片段（讲师口述的代码 → 格式化为 code block）
4. 当内容涉及流程/架构/对比时，生成 Mermaid 图
5. 当内容是分步操作时，输出 StepByStep 结构
6. 每个小节标注对应的视频起始时间戳

输出：JSON 格式的 LessonContent

**改动：**
- 新增 `backend/app/services/lesson_generator.py` — LessonGenerator 服务
- 修改 `CourseGenerator` — 在创建 Section 后调用 LessonGenerator 生成课文
- Section.content JSONB 存储 LessonContent

---

## 5. Lab 生成

**触发条件：** Section 的课文中包含 code_snippets 时生成 lab。纯理论不生成。

**数据模型：**

新增 `labs` 表：

```sql
CREATE TABLE labs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_id UUID NOT NULL REFERENCES sections(id),
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,         -- Markdown，目标+背景
    language VARCHAR(50) NOT NULL,     -- python, go, javascript, etc.
    starter_code JSONB NOT NULL,       -- {filename: content} 骨架
    test_code JSONB NOT NULL,          -- {filename: content} 测试
    solution_code JSONB NOT NULL,      -- {filename: content} 参考答案
    run_instructions TEXT NOT NULL,    -- 如何运行测试的具体命令
    confidence NUMERIC(3,2) DEFAULT 0.5,  -- LLM 自评置信度
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

**生成流程：**

```
Section 的 code_snippets + 教学上下文
    ↓
LLM 生成：
  1. 分析代码片段，确定 lab 主题
  2. 生成完整参考答案 (solution_code)
  3. 从答案中挖空关键部分 → 骨架 (starter_code) + TODO 注释
  4. 生成测试 (test_code)
  5. 生成运行说明 (run_instructions)
    ↓
LLM 自审：骨架 + 测试是否自洽（把答案填回骨架，逻辑上测试应该通过）
    ↓
自评置信度 → 低于 0.3 则不生成该 lab
```

**运行说明模板（按语言自动填充）：**

```markdown
## 如何运行

### 环境准备
确保已安装 Python 3.10+（或对应语言环境）

### 运行测试
cd lab_01_xxx
pip install -r requirements.txt   # 如果有
python -m pytest tests/ -v

### 目标
让所有测试通过！TODO 标记处是你需要填写的代码。
```

**LabGenerator 服务：**
- `backend/app/services/lab_generator.py`
- 在 LessonGenerator 完成后调用
- 只在检测到代码时触发

---

## 6. 首次启动引导

**流程：**

```
用户首次访问 localhost:3000
    ↓
前端 GET /api/v1/models → 空列表
    ↓
重定向到 /setup
    ↓
Setup 页面：
  Step 1: "选择 AI 模型"
    ├── [推荐] Ollama（本地免费）
    │     → 检测 localhost:11434 是否可达
    │     → 可达：自动列出已安装模型 → 选择 → 自动配置
    │     → 不可达：显示安装教程链接
    ├── OpenAI API
    │     → 输入 API Key → 测试连接 → 配置
    └── Anthropic API
          → 输入 API Key → 测试连接 → 配置
  Step 2: "导入你的第一个教程"
    → 跳转到 /import 页面
```

**Ollama 自动检测：**
```python
# backend 新增 endpoint
GET /api/v1/setup/detect-ollama
# 尝试 GET http://localhost:11434/api/tags
# 返回 { available: true, models: ["qwen2.5:7b", ...] }
```

**改动：**
- 新增 `frontend/src/app/setup/page.tsx`
- 新增 `backend/app/api/routes/setup.py`
- 前端 Dashboard 页检测无模型时重定向到 /setup

---

## 7. 前端课程页面改造

当前 learn 页是 video + chat 分屏。改造为类似 learn.shareai.run 的课程阅读体验：

**布局：**

```
┌─────────────────────────────────────────────────┐
│ 课程标题                           [进度 3/12]   │
├──────────┬──────────────────────────────────────┤
│ 大纲导航  │  主内容区                              │
│          │  ┌──────────────────────────────────┐ │
│ ● 第1章   │  │ [课文] [视频] [Lab] [导师]       │ │
│ ○ 第2章   │  ├──────────────────────────────────┤ │
│ ○ 第3章   │  │                                  │ │
│ ...      │  │  结构化课文内容                     │ │
│          │  │  - 标题                            │ │
│          │  │  - 正文 + 时间戳链接               │ │
│          │  │  - Mermaid 流程图                  │ │
│          │  │  - 代码高亮                        │ │
│          │  │  - 步骤分解卡片                    │ │
│          │  │                                  │ │
│          │  │  [章节练习]                        │ │
│          │  └──────────────────────────────────┘ │
└──────────┴──────────────────────────────────────┘
```

**Tab 内容：**
- **课文** — 渲染 LessonContent：Markdown + Mermaid + 代码高亮 + StepByStep 卡片 + 时间戳按钮（点击跳到视频 tab 对应位置）
- **视频** — Bilibili iframe 嵌入
- **Lab** — 描述 + 只读代码预览（骨架 + 测试）+ "下载 Lab" 按钮 + 运行说明
- **导师** — 现有的 AI 对话（保持）

**新增前端组件：**
- `components/lesson/` — 课文渲染器
- `components/lesson/mermaid-diagram.tsx` — Mermaid 渲染（用 `mermaid` npm 包）
- `components/lesson/step-by-step.tsx` — 可点击展开的步骤卡片
- `components/lesson/code-block.tsx` — 语法高亮代码块
- `components/lesson/timestamp-link.tsx` — 时间戳跳转按钮
- `components/lab/lab-viewer.tsx` — Lab 预览 + 下载

**新增前端依赖：**
- `mermaid` — 流程图渲染
- `prismjs` 或 `shiki` — 代码语法高亮（如果 react-markdown 自带的不够）

---

## 8. 内容分析管线改造

当前管线：extract → analyze → store → embed

改造为：extract → analyze → **generate lesson** → **generate lab** → store → embed

```
Celery task: ingest_source
    ↓
1. Extract: BilibiliExtractor (合集 → 多 P 字幕)
    ↓
2. Analyze: ContentAnalyzer (概念、难度、摘要) — 已有
    ↓
3. Generate Lesson: LessonGenerator (字幕 → 结构化课文)  — 新增
    ↓
4. Generate Lab: LabGenerator (有代码时生成)  — 新增
    ↓
5. Store: 写入 DB (sections, content_chunks, labs)
    ↓
6. Embed: EmbeddingService — 已有
```

**改动：**
- `content_ingestion.py` 在 analyze 和 store 之间插入 lesson + lab 生成步骤
- 新增 `LessonGenerator` 和 `LabGenerator` 服务

---

## 9. README + LICENSE

```markdown
# 🧠 Socratiq

把 B 站编程教程变成交互式课程。导入视频合集，AI 自动生成结构化课文、
诊断测评、Lab 代码练习，配合苏格拉底式 AI 导师辅导学习。

## ✨ 特性

- **视频 → 课程**：导入 B 站/YouTube 编程教程合集，自动生成完整课程
- **结构化课文**：字幕智能重组 + 流程图 + 代码高亮 + 步骤分解
- **Lab 练习**：自动生成代码骨架 + 测试，像 MIT 课程一样动手写代码
- **AI 导师**：苏格拉底式教学，追问引导而不是直接给答案
- **学习诊断**：基于内容自动出题，测试你真正掌握了多少
- **间隔复习**：SM-2 算法安排复习，学了不会忘
- **知识图谱**：D3.js 可视化概念关系和掌握度
- **完全本地**：支持 Ollama，数据不出你的电脑

## 🚀 快速开始

git clone https://github.com/CounterflowLabs/socratiq
cd socratiq
docker compose up
# 打开 http://localhost:3000

## 📋 系统要求

- Docker + Docker Compose
- 8GB+ 内存（使用 Ollama 本地模型时推荐 16GB）
- 或：任意 OpenAI / Anthropic API Key（无本地计算要求）

## License

MIT
```

---

## 10. 新增/改动文件清单

### 新增

| 文件 | 说明 |
|------|------|
| `backend/Dockerfile` | 后端容器 |
| `frontend/Dockerfile` | 前端容器 |
| `.env.example` | 配置模板 |
| `backend/app/services/lesson_generator.py` | 字幕 → 结构化课文 |
| `backend/app/services/lab_generator.py` | 代码片段 → Lab 骨架+测试 |
| `backend/app/models/lesson.py` | LessonContent Pydantic schemas |
| `backend/app/models/lab.py` | Lab Pydantic schemas |
| `backend/app/db/models/lab.py` | Lab ORM model |
| `backend/app/api/routes/setup.py` | Onboarding + Ollama 检测 |
| `backend/app/api/routes/labs.py` | Lab CRUD + 下载 |
| `frontend/src/app/setup/page.tsx` | 首次启动引导页 |
| `frontend/src/components/lesson/*.tsx` | 课文渲染组件（mermaid, code, steps, timestamp） |
| `frontend/src/components/lab/lab-viewer.tsx` | Lab 预览+下载 |
| `README.md` | 项目说明 |
| `LICENSE` | MIT |

### 改动

| 文件 | 改动 |
|------|------|
| `docker-compose.yml` | 加 backend + frontend 服务 |
| `backend/app/tools/extractors/bilibili.py` | 合集支持（多 P 提取）|
| `backend/app/worker/tasks/content_ingestion.py` | 插入 lesson + lab 生成步骤 |
| `backend/app/services/course_generator.py` | 合集分 P → 多 section |
| `frontend/src/app/learn/page.tsx` | 改造为课程阅读布局 |
| `frontend/src/app/page.tsx` | Dashboard 检测无模型→重定向 setup |
| `frontend/src/lib/api.ts` | 加 lab, setup API functions |
| `frontend/package.json` | 加 mermaid 依赖 |

---

## 11. 不做的事（v0.1.0 范围外）

- OCR 提取屏幕代码 — 复杂且不可靠
- Docker sandbox 执行代码 — v0.3.0
- 主动探索补充材料 — v0.2.0
- 课程导出为静态网站 — v0.2.0
- 多语言 UI — 先只有中文
- SQLite 替代 PostgreSQL — v0.2.0
- GitHub 源码仓库关联
