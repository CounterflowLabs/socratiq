# LearnMentor — AI 驱动的自适应学习系统

## 系统设计文档 v1.1

> **一句话定义**：一个拥有 Agent 灵魂的学习系统——它不只是播放视频和生成题目，它是一个能理解你、记住你、陪你成长的 AI 导师。

---

## 1. 核心设计哲学

### 1.1 不是工具，是导师

| 传统平台 | LearnMentor |
|----------|-------------|
| 用户搜索课程 | 导师根据你的目标推荐学习路径 |
| 看完视频做题 | 导师发现你哪里卡住了，调整讲解方式 |
| 千人一面的习题 | 根据你的薄弱点动态生成针对性练习 |
| 学完就结束 | 导师记得你三个月前学了什么，帮你串联知识 |
| 冷冰冰的界面 | 有个性、有温度、会鼓励也会 push 你 |

### 1.2 Agent 设计哲学：LLM + 工具调用 + 循环推理

```
用户行为/消息
    ↓
导师 Agent（LLM 推理）
    ├── 观察：用户在做什么？进度如何？情绪如何？
    ├── 思考：他需要什么帮助？现在该主动还是被动？
    ├── 决策：调用哪个工具？生成什么内容？
    │     ├── 工具：内容提取（视频/PDF/Markdown/URL）
    │     ├── 工具：网络搜索补充资料
    │     ├── 工具：代码执行/验证
    │     ├── 工具：学生画像读写
    │     ├── 工具：知识库检索（RAG）
    │     └── 工具：课程/Lab/习题生成
    ├── 执行：生成回复/教案/习题/项目
    └── 反思：这次互动效果如何？更新对学生的理解
         ↓
    循环 → 等待下一次交互
```

### 1.3 知识库 = 基础设施层 | 导师 Agent + 学生画像 = 价值层

同一个概念可能出现在视频、PDF 论文、博客笔记中。知识库不存三份独立条目，而是**一个概念节点关联多个来源**。导师讲解时可以说：
> "这个概念 Karpathy 在视频第 23 分钟讲过，Diego 的博客也有不错的图解，你想从哪个角度回顾？"

### 1.4 学生画像（Student Profile）— 系统的灵魂

不是静态的用户设置，而是一个**持续演化的认知模型**：

```python
from pydantic import BaseModel, Field
from enum import Enum

class Pace(str, Enum):
    slow = "slow"
    moderate = "moderate"
    fast = "fast"

class LearningStyle(BaseModel):
    pace: Pace = Pace.moderate
    prefers_examples: bool = True          # 喜欢通过例子学还是理论先行
    prefers_code_first: bool = True        # 喜欢先看代码还是先看概念
    attention_span: str = "medium"         # 一次能集中多久
    best_time: str = "evening"             # 什么时候学习状态最好
    response_to_challenge: str = "motivated"  # 遇到难题是受挫还是来劲

class Competency(BaseModel):
    programming: dict[str, str] = {}       # {"python": "intermediate", "react": "intermediate"}
    domains: dict[str, float] = {}         # {"llm_basics": 0.7, "agent_dev": 0.2}  0-1
    weak_spots: list[str] = []             # 具体薄弱知识点
    strong_spots: list[str] = []

class LearningHistory(BaseModel):
    courses_completed: list[str] = []
    courses_in_progress: list[str] = []
    labs_completed: list[str] = []
    questions_asked: list[str] = []        # 帮助理解薄弱点
    mistakes_pattern: list[str] = []       # 常犯的错误类型
    aha_moments: list[str] = []            # 什么讲解方式对他有效
    total_study_hours: float = 0
    streak_days: int = 0

class MentorStrategy(BaseModel):
    current_approach: str = ""             # 当前教学策略
    personality: str = "encouraging"       # encouraging / direct / socratic
    push_level: str = "gentle"             # gentle / moderate / firm
    last_interaction_summary: str = ""
    next_suggested_action: str = ""

class StudentProfile(BaseModel):
    name: str = ""
    learning_goals: list[str] = []
    motivation: str = ""
    preferred_language: str = "zh-CN"
    competency: Competency = Field(default_factory=Competency)
    learning_style: LearningStyle = Field(default_factory=LearningStyle)
    history: LearningHistory = Field(default_factory=LearningHistory)
    mentor_strategy: MentorStrategy = Field(default_factory=MentorStrategy)
```

**画像如何演化？** 不是让用户填表，而是从每次交互中自然推断：

- 用户问了 "context window" 的基础问题 → `domains["llm_basics"]` 下调
- 用户快速完成 Lab → `pace` 调整为 fast
- 用户连续两天没登录 → 下次导师主动关心
- 用户在 "异步编程" 题目反复出错 → 加入 `weak_spots`

**渐进式置信**：观察 1 次记录但不更新 → 3 次一致标记"可能" → 5 次确认更新 → 导师主动验证（"我注意到你对异步编程很熟，是之前有经验吗？"）

---

## 2. 系统架构

### 2.1 技术栈

```
┌─────────────────────────────────────────────────┐
│                   Frontend                       │
│             Next.js 14+ (App Router)             │
│         React · TypeScript · Tailwind CSS        │
│      Monaco Editor · YouTube/Bilibili Embed      │
│           shadcn/ui · Knowledge Graph            │
└──────────────────┬──────────────────────────────┘
                   │ REST / WebSocket / SSE
┌──────────────────▼──────────────────────────────┐
│          Backend — Python / FastAPI              │
│                                                  │
│  ┌──────────────────────────────────────────┐    │
│  │           Agent Engine                    │    │
│  │                                          │    │
│  │  MentorAgent (核心推理循环)               │    │
│  │    ├── CourseAgent (课程生成)             │    │
│  │    ├── LabAgent (Lab 设计)               │    │
│  │    ├── EvalAgent (评估判分)              │    │
│  │    └── ReviewAgent (项目 Review)         │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ┌──────────────────────────────────────────┐    │
│  │           Tools (Agent 工具集)            │    │
│  │                                          │    │
│  │  ContentExtractor  WebSearcher           │    │
│  │    ├── YouTube (youtube-transcript-api)   │    │
│  │    ├── Bilibili (bilibili-api)           │    │
│  │    ├── PDF (pymupdf / marker)            │    │
│  │    ├── Markdown (native)                 │    │
│  │    └── URL/HTML (httpx + readability)    │    │
│  │                                          │    │
│  │  CodeRunner (Docker sandbox)             │    │
│  │  ProfileManager (学生画像 CRUD)          │    │
│  │  KnowledgeBase (RAG 检索)               │    │
│  │  ContentGenerator (教案/习题/Lab)        │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  LLM Client: anthropic (Claude API)             │
│  Task Queue: Celery + Redis (异步长任务)         │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│                 Data Layer                        │
│                                                  │
│  PostgreSQL + pgvector         Redis    S3/MinIO │
│  ├── 用户/学生画像              缓存     文件存储 │
│  ├── 课程/章节/知识点           会话     生成内容 │
│  ├── 学习记录/对话历史          队列              │
│  └── 向量 embeddings (RAG)                       │
└─────────────────────────────────────────────────┘
```

### 2.2 为什么 Python + FastAPI？

| 考量 | 分析 |
|------|------|
| **LLM 生态** | anthropic SDK、openai SDK、langchain、llamaindex 全部 Python 优先 |
| **内容提取** | pymupdf、youtube-transcript-api、whisper、marker 等都是 Python 库 |
| **向量计算** | numpy、sentence-transformers 原生支持 |
| **异步能力** | FastAPI 基于 asyncio，Agent 工具调用大量并发 IO 天然适配 |
| **性能瓶颈** | 在 LLM API 延迟（1-10s），不在语言运行时。Python 够用 |
| **开发效率** | Pydantic 数据模型 + 类型提示 + 自动 API 文档，适合快速迭代 |
| **统一性** | 一个语言解决所有问题，不需要 Go ↔ Python 微服务桥接 |

---

## 3. 核心模块详细设计

### 3.1 模块一：统一内容摄入引擎

```
任意来源
  ├── YouTube URL    → youtube-transcript-api 提取字幕
  ├── Bilibili URL   → bilibili-api 提取字幕
  ├── PDF 文件       → pymupdf / marker 提取文本+结构
  ├── Markdown 文件  → 原生解析
  └── URL / HTML     → httpx + readability-lxml 提取正文
         ↓
┌─────────────────────────────┐
│ 统一文本输出 (ContentChunk)  │
│ - source_type               │
│ - raw_text                  │
│ - metadata (时间轴/页码等)   │
│ - media_url (视频/图片)      │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ LLM 结构化分析               │
│ - 按主题分段                 │
│ - 提取核心概念               │
│ - 识别代码/公式/图表          │
│ - 识别引用论文/资源           │
│ - 难度评估                   │
│ - 前置知识推断               │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 知识库写入                   │
│ - 文本分块 → embedding       │
│ - 概念节点 → 概念图谱        │
│ - 跨来源关联                 │
│   (同一概念多个来源 = 链接)   │
└─────────────────────────────┘
```

**Python 实现骨架**：

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel

class ContentChunk(BaseModel):
    source_type: str           # "youtube" | "bilibili" | "pdf" | "markdown" | "url"
    raw_text: str
    metadata: dict = {}        # {"start_time": 180, "end_time": 240} or {"page": 3}
    media_url: str | None = None

class ContentExtractor(ABC):
    @abstractmethod
    async def extract(self, source: str) -> list[ContentChunk]:
        ...

class YouTubeExtractor(ContentExtractor):
    async def extract(self, url: str) -> list[ContentChunk]:
        # youtube-transcript-api → 字幕
        # 无字幕 → whisper fallback
        ...

class PDFExtractor(ContentExtractor):
    async def extract(self, file_path: str) -> list[ContentChunk]:
        # pymupdf 或 marker → 结构化文本
        # 保留页码、标题层级、表格、图片引用
        ...

class MarkdownExtractor(ContentExtractor):
    async def extract(self, file_path: str) -> list[ContentChunk]:
        # 按 heading 分段，保留代码块和链接
        ...

# 工厂模式 — 根据输入类型自动选择提取器
EXTRACTORS: dict[str, type[ContentExtractor]] = {
    "youtube": YouTubeExtractor,
    "bilibili": BilibiliExtractor,
    "pdf": PDFExtractor,
    "markdown": MarkdownExtractor,
    "url": URLExtractor,
}
```

### 3.2 模块二：Agent Engine

```python
from anthropic import AsyncAnthropic
from pydantic import BaseModel

class Tool(BaseModel):
    name: str
    description: str           # 给 LLM 看的描述
    parameters: dict           # JSON Schema

    async def execute(self, **params) -> str:
        raise NotImplementedError

class MentorAgent:
    def __init__(self, llm: AsyncAnthropic, tools: list[Tool], profile: StudentProfile):
        self.llm = llm
        self.tools = tools
        self.profile = profile
        self.conversation: list[dict] = []

    async def process(self, user_message: str) -> AsyncIterator[str]:
        """核心推理循环 — 支持 SSE 流式输出"""

        self.conversation.append({"role": "user", "content": user_message})

        while True:
            # 1. 构建 system prompt（注入学生画像 + 教学策略）
            system = self._build_system_prompt()

            # 2. 调用 LLM（带 tools 定义）
            response = await self.llm.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=system,
                messages=self.conversation,
                tools=[t.to_anthropic_schema() for t in self.tools],
                stream=True,
            )

            # 3. 处理流式响应
            tool_calls = []
            async for event in response:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        yield event.delta.text  # 流式输出给前端
                elif event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        tool_calls.append(event.content_block)

            # 4. 如果有工具调用 → 执行 → 继续循环
            if tool_calls:
                for tc in tool_calls:
                    tool = self._find_tool(tc.name)
                    result = await tool.execute(**tc.input)
                    self.conversation.append({
                        "role": "assistant",
                        "content": [tc],
                    })
                    self.conversation.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "content": result,
                        }],
                    })
                continue  # 继续循环让 LLM 处理工具结果

            # 5. 没有工具调用 → 回复完成
            break

        # 6. 异步更新学生画像（不阻塞响应）
        asyncio.create_task(self._update_profile(user_message))

    def _build_system_prompt(self) -> str:
        return f"""你是 LearnMentor 的导师。

## 你的学生
{self.profile.model_dump_json(indent=2)}

## 教学原则
- 根据学生的 pace 和 learning_style 调整讲解深度
- 如果学生 prefers_code_first，先给代码示例再解释概念
- 关注 weak_spots，遇到相关话题时主动多解释
- 利用 aha_moments 中记录的有效讲解方式
- 当前教学策略：{self.profile.mentor_strategy.current_approach}
- 人格风格：{self.profile.mentor_strategy.personality}

## 可用工具
你可以调用以下工具来帮助教学...
"""
```

### 3.3 模块三：导师交互模式

```python
class InteractionMode(str, Enum):
    QA = "qa"                    # 答疑 — 学生主动提问
    SOCRATIC = "socratic"        # 苏格拉底 — 引导式提问
    PROACTIVE = "proactive"      # 主动关怀 — 导师发起
    REVIEW = "review"            # 复习 — 艾宾浩斯提醒
    PROJECT = "project"          # 项目导师 — Review 代码和架构

# 导师根据上下文自动选择模式，也可以显式切换
# 例如：学生说"帮我 review 一下代码" → PROJECT 模式
# 例如：学生三天没来 → PROACTIVE 模式
```

**五种模式的行为差异**：

| 模式 | 导师行为 | 触发条件 |
|------|----------|----------|
| **答疑** | 直接回答，但会追问诊断理解偏差 | 学生提问 |
| **苏格拉底** | 不给答案，用问题引导思考 | 做练习时、概念性问题 |
| **主动关怀** | 主动发消息关心学习状态 | 学习中断、连续做对/做错 |
| **复习** | 基于遗忘曲线提醒复习 | 定时检查 |
| **项目导师** | Review 代码、引导定位问题 | 做项目时 |

### 3.4 模块四：代码 Lab 运行环境

```python
# MVP 方案：Docker 沙箱执行
import docker

class CodeRunner:
    def __init__(self):
        self.client = docker.from_env()

    async def run(self, code: str, language: str = "python",
                  timeout: int = 30, test_cases: list[dict] = None) -> dict:
        """在 Docker 沙箱中执行代码，返回结果"""
        container = self.client.containers.run(
            image=f"learnmentor-sandbox-{language}",
            command=["python", "-c", code],
            mem_limit="256m",
            cpu_period=100000,
            cpu_quota=50000,
            network_disabled=True,
            detach=True,
        )
        # 等待执行 + 收集输出
        result = container.wait(timeout=timeout)
        logs = container.logs().decode()
        container.remove()

        # 如果有测试用例，逐一验证
        test_results = []
        if test_cases:
            for tc in test_cases:
                # 运行测试代码...
                pass

        return {
            "stdout": logs,
            "exit_code": result["StatusCode"],
            "test_results": test_results,
        }
```

### 3.5 视频嵌入播放

```typescript
// Next.js 前端组件

// YouTube: IFrame Player API
// https://developers.google.com/youtube/iframe_api_reference
export function YouTubePlayer({ videoId, onTimeUpdate }) {
  return (
    <iframe
      src={`https://www.youtube.com/embed/${videoId}?enablejsapi=1`}
      allow="accelerometer; autoplay; encrypted-media"
      allowFullScreen
    />
  );
}

// Bilibili: 嵌入播放器
// https://player.bilibili.com/player.html?bvid={bvid}
export function BilibiliPlayer({ bvid, onTimeUpdate }) {
  return (
    <iframe
      src={`//player.bilibili.com/player.html?bvid=${bvid}&page=1`}
      allowFullScreen
    />
  );
}

// 关键能力：视频播放进度与教案内容联动
// 当用户看到视频第 15 分钟 → 右侧自动滚动到对应知识点
```

---

## 4. 数据模型

```sql
-- 用户
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    student_profile JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 内容来源（视频/PDF/MD/URL）
CREATE TABLE sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT NOT NULL,  -- youtube | bilibili | pdf | markdown | url
    url TEXT,
    title TEXT,
    raw_content TEXT,
    metadata JSONB DEFAULT '{}',
    status TEXT DEFAULT 'pending',  -- pending | processing | ready | error
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 课程（由一个或多个 source 生成）
CREATE TABLE courses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    description TEXT,
    source_ids UUID[] DEFAULT '{}',
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 课程章节
CREATE TABLE sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id UUID REFERENCES courses(id),
    title TEXT NOT NULL,
    order_index INT,
    source_id UUID REFERENCES sources(id),
    source_start TEXT,  -- 视频时间戳 or PDF页码
    source_end TEXT,
    content JSONB DEFAULT '{}',
    difficulty INT DEFAULT 1  -- 1-5
);

-- 知识点 / 概念图谱
CREATE TABLE concepts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    category TEXT,
    prerequisites UUID[] DEFAULT '{}',
    embedding vector(1536)
);

-- 概念 ↔ 来源关联（多对多）
CREATE TABLE concept_sources (
    concept_id UUID REFERENCES concepts(id),
    source_id UUID REFERENCES sources(id),
    context TEXT,  -- 该来源中关于这个概念的上下文片段
    PRIMARY KEY (concept_id, source_id)
);

-- 内容块（用于 RAG 检索）
CREATE TABLE content_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES sources(id),
    section_id UUID REFERENCES sections(id),
    text TEXT NOT NULL,
    embedding vector(1536),
    metadata JSONB DEFAULT '{}'
);

-- Lab
CREATE TABLE labs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_id UUID REFERENCES sections(id),
    title TEXT NOT NULL,
    description TEXT,
    difficulty INT DEFAULT 1,
    estimated_minutes INT,
    starter_code TEXT,
    solution TEXT,
    test_cases JSONB DEFAULT '[]',
    hints JSONB DEFAULT '[]'
);

-- 习题
CREATE TABLE exercises (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_id UUID REFERENCES sections(id),
    type TEXT NOT NULL,  -- mcq | code | open
    question TEXT NOT NULL,
    options JSONB,
    answer TEXT,
    explanation TEXT,
    difficulty INT DEFAULT 1,
    concepts UUID[] DEFAULT '{}'
);

-- 学习记录
CREATE TABLE learning_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    course_id UUID REFERENCES courses(id),
    section_id UUID REFERENCES sections(id),
    type TEXT NOT NULL,  -- video_watch | lab_complete | exercise_submit | chat
    data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 对话历史
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    course_id UUID REFERENCES courses(id),
    mode TEXT DEFAULT 'qa',
    messages JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 5. 项目结构

```
learnmentor/
├── frontend/                      # Next.js
│   ├── app/
│   │   ├── page.tsx               # Dashboard
│   │   ├── courses/
│   │   │   ├── new/page.tsx       # 创建课程（粘贴链接/上传文件）
│   │   │   └── [id]/page.tsx      # 课程详情
│   │   ├── learn/[id]/page.tsx    # 学习页（视频+教案+导师）
│   │   ├── lab/[id]/page.tsx      # Lab 页（编辑器+测试）
│   │   └── report/page.tsx        # 学习报告
│   ├── components/
│   │   ├── VideoPlayer/           # YouTube/Bilibili 播放器封装
│   │   ├── MentorChat/            # 导师对话面板（SSE 流式）
│   │   ├── CodeEditor/            # Monaco Editor 封装
│   │   └── KnowledgeGraph/        # 知识图谱可视化（D3.js）
│   ├── lib/
│   │   └── api.ts                 # FastAPI 客户端
│   ├── package.json
│   └── tailwind.config.ts
│
├── backend/                       # Python / FastAPI
│   ├── app/
│   │   ├── main.py                # FastAPI 入口
│   │   ├── config.py              # 配置管理
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   ├── courses.py     # 课程 CRUD
│   │   │   │   ├── chat.py        # 导师对话（SSE endpoint）
│   │   │   │   ├── labs.py        # Lab 相关
│   │   │   │   ├── exercises.py   # 习题相关
│   │   │   │   └── sources.py     # 内容来源管理
│   │   │   └── deps.py            # 依赖注入
│   │   ├── agent/
│   │   │   ├── mentor.py          # 导师 Agent（核心推理循环）
│   │   │   ├── course_agent.py    # 课程生成 Agent
│   │   │   ├── lab_agent.py       # Lab 设计 Agent
│   │   │   ├── eval_agent.py      # 评估 Agent
│   │   │   └── prompts/           # System prompts 模板
│   │   │       ├── mentor.py
│   │   │       ├── course.py
│   │   │       └── lab.py
│   │   ├── tools/
│   │   │   ├── base.py            # Tool 基类
│   │   │   ├── extractors/        # 内容提取器
│   │   │   │   ├── youtube.py
│   │   │   │   ├── bilibili.py
│   │   │   │   ├── pdf.py
│   │   │   │   ├── markdown.py
│   │   │   │   └── url.py
│   │   │   ├── search.py          # 网络搜索
│   │   │   ├── code_runner.py     # 代码沙箱
│   │   │   ├── knowledge.py       # 知识库检索（RAG）
│   │   │   └── profile.py         # 学生画像管理
│   │   ├── models/
│   │   │   ├── user.py            # 用户 + 学生画像
│   │   │   ├── course.py          # 课程/章节/知识点
│   │   │   ├── lab.py             # Lab / 习题
│   │   │   └── record.py          # 学习记录
│   │   ├── db/
│   │   │   ├── database.py        # SQLAlchemy async engine
│   │   │   ├── migrations/        # Alembic migrations
│   │   │   └── repositories/      # 数据访问层
│   │   └── services/
│   │       ├── embedding.py       # Embedding 计算
│   │       ├── llm.py             # Anthropic API 封装
│   │       └── tasks.py           # Celery 异步任务
│   ├── tests/
│   ├── pyproject.toml             # uv / poetry
│   └── Dockerfile
│
├── sandbox/                       # 代码执行沙箱 Docker 镜像
│   ├── python/Dockerfile
│   └── javascript/Dockerfile
│
├── docker-compose.yml             # 开发环境编排
├── docker-compose.prod.yml
└── README.md
```

---

## 6. 关键依赖

```toml
# pyproject.toml (部分)
[project]
dependencies = [
    # Web 框架
    "fastapi>=0.115",
    "uvicorn[standard]",
    "sse-starlette",               # SSE 流式响应

    # LLM
    "anthropic>=0.40",             # Claude API

    # 数据库
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg",                     # PostgreSQL 异步驱动
    "alembic",                     # 数据库迁移
    "pgvector",                    # 向量扩展

    # 内容提取
    "youtube-transcript-api",       # YouTube 字幕
    "pymupdf",                     # PDF 解析
    "readability-lxml",            # URL 正文提取
    "httpx",                       # 异步 HTTP

    # AI / ML
    "openai",                      # embedding 计算（text-embedding-3-small）
    "numpy",

    # 任务队列
    "celery[redis]",
    "redis",

    # 代码沙箱
    "docker",

    # 工具
    "pydantic>=2.0",
    "python-multipart",            # 文件上传
]
```

---

## 7. MVP 开发计划

### Phase 0：基础设施（1 周）

```
- [ ] 初始化 Next.js + Tailwind + shadcn/ui
- [ ] 初始化 FastAPI 项目 + 项目结构
- [ ] PostgreSQL + pgvector + Redis (Docker Compose)
- [ ] Anthropic Claude API 对接
- [ ] SQLAlchemy models + Alembic migration
- [ ] 基础 API：用户注册/登录

产出：前后端能跑通，能调用 Claude API
```

### Phase 1：内容摄入 → 课程生成（2 周）

```
- [ ] YouTube 字幕提取器
- [ ] Markdown 提取器
- [ ] PDF 提取器（pymupdf）
- [ ] LLM 内容分析管线（分段 → 概念提取 → 难度评估）
- [ ] Embedding 计算 + pgvector 存储
- [ ] 概念图谱（概念节点 + 跨来源关联）
- [ ] 课程 CRUD API
- [ ] 前端：课程创建页 + 视频嵌入 + 教案展示
- [ ] 视频进度与教案联动

产出：输入视频/PDF/MD → 生成结构化课程 → 可以学习
```

### Phase 2：导师对话（2 周）

```
- [ ] Agent Engine 核心循环（MentorAgent）
- [ ] 学生画像 Pydantic model + DB
- [ ] 导师 System Prompt（画像注入 + 教学策略）
- [ ] 对话历史管理
- [ ] RAG 检索工具（从知识库查询相关内容）
- [ ] SSE 流式对话 endpoint
- [ ] 前端：MentorChat 组件
- [ ] 交互模式：答疑 + 苏格拉底

产出：能和导师对话，导师了解你并据此调整回答
```

### Phase 3：Lab + 习题（2 周）

```
- [ ] Lab 生成 Agent
- [ ] 习题生成 Agent
- [ ] Docker 代码沙箱
- [ ] Monaco Editor 集成
- [ ] 自动判分 + 错误分析
- [ ] 画像根据做题结果自动更新
- [ ] 分级提示系统（hint 1 → hint 2 → hint 3）

产出：完整学习闭环 — 看内容 → 做 Lab → 答题 → 导师反馈
```

### Phase 4：打磨体验（2 周）

```
- [ ] 导师主动关怀（定时检查学习状态）
- [ ] 复习提醒（艾宾浩斯遗忘曲线）
- [ ] 学习报告 + 知识图谱可视化
- [ ] 实战项目设计 + Review 流程
- [ ] Bilibili 视频支持
- [ ] URL/HTML 内容提取
- [ ] UI 打磨 + 深色主题

产出：一个你自己想每天使用的学习系统
```

**总计：约 9 周**

---

## 8. 成本估算（个人使用）

| 项目 | 月成本 |
|------|--------|
| LLM API（Claude Sonnet 为主，Haiku 辅助） | $20-50 |
| Embedding API（text-embedding-3-small） | $1-5 |
| 服务器（小型 VPS / 本地 Docker） | $0-20 |
| PostgreSQL（本地 Docker） | $0 |
| **总计** | **$20-75/月** |

成本控制策略：非关键路径用 Claude Haiku（快且便宜），只在导师对话等核心场景用 Sonnet。Embedding 可以用本地模型（sentence-transformers）完全免费。

---

## 9. 未来扩展

- **多人学习小组**：同课程学生组队，导师管理小组讨论
- **课程市场**：用户生成的课程可分享
- **导师人格定制**：严格型 / 鼓励型 / 幽默型
- **MCP 集成**：通过 Model Context Protocol 连接更多外部工具
- **移动端**：React Native 或 PWA
- **离线学习**：下载课程到本地
- **更多来源**：Coursera、edX、本地视频文件、Notion 导出

---

*LearnMentor v1.1 — 技术栈：Next.js + Python (FastAPI) + PostgreSQL + Claude API*
