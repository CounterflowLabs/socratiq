# Sub-project C: MentorAgent Core + Frontend

**Date**: 2026-03-24
**Status**: Approved
**Depends on**: Sub-project A (infrastructure), Sub-project B (content ingestion)
**Scope**: MentorAgent agent loop + tools + RAG + Chat API (SSE) + Next.js frontend

---

## 1. Overview

Sub-project C implements the two user-facing layers of Socratiq:

1. **MentorAgent** — the AI agent core that powers all mentor interactions (backend)
2. **Frontend** — the Next.js application users interact with (import, learn, chat, settings)

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agent tool interface | Pydantic-based `AgentTool` ABC | Clean schema generation for LLM tool_use; testable |
| SSE streaming | `sse-starlette` | FastAPI-native SSE; already in project deps |
| Chat API design | Single `POST /api/chat` with SSE response | Simplest streaming pattern; no WebSocket complexity |
| System prompt | Template string with f-string injection | Simple, debuggable; no Jinja needed for MVP |
| RAG approach | pgvector cosine similarity on content_chunks | Already have embeddings from Sub-project B |
| Profile storage | JSONB in `users.student_profile` | Already exists; Pydantic model for validation |
| Profile updates | Async background task after response | Non-blocking; uses asyncio.create_task |
| Frontend framework | Next.js 14+ App Router | Matches CLAUDE.md spec |
| Component library | shadcn/ui | Copy-paste components; no vendor lock-in |
| State management | Zustand | Lightweight; recommended in CLAUDE.md |
| SSE client | `eventsource-parser` + fetch | Works with POST requests (EventSource API only supports GET) |
| Auth | Skip for MVP | Single user; user_id hardcoded or from simple header |

---

## 2. PART 1 — MentorAgent Core (Backend)

### 2.1 Agent Architecture

#### Directory Structure (new files)

```
backend/app/
├── agent/
│   ├── __init__.py
│   ├── mentor.py              # MentorAgent class
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py            # AgentTool abstract base class
│   │   ├── knowledge.py       # RAG retrieval tool
│   │   ├── profile.py         # Student profile read/update tool
│   │   └── progress.py        # Learning progress tracking tool
│   └── prompts/
│       ├── __init__.py
│       └── mentor.py          # System prompt template
├── services/
│   ├── rag.py                 # RAG retrieval service
│   └── profile.py             # StudentProfile Pydantic model + DB ops
├── api/
│   └── routes/
│       ├── chat.py            # POST /api/chat (SSE), conversation CRUD
│       └── courses.py         # Course/section CRUD (read-only for C)
└── models/
    ├── chat.py                # Chat request/response Pydantic schemas
    ├── course.py              # Course/section response schemas
    └── profile.py             # StudentProfile schema (re-export)
```

#### AgentTool Base Class (`backend/app/agent/tools/base.py`)

```python
"""Base class for all agent tools."""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class AgentTool(ABC):
    """Abstract base for tools the MentorAgent can invoke.

    Each tool provides:
    - name/description/parameters for LLM tool_use schema generation
    - execute() to run the tool and return a string result
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name as the LLM sees it (snake_case, e.g. 'search_knowledge')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Description shown to the LLM in the tool definition."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """JSON Schema for the tool's parameters."""
        ...

    @abstractmethod
    async def execute(self, **params) -> str:
        """Execute the tool with the given parameters.

        Returns:
            A string result that will be sent back to the LLM as tool_result.
        """
        ...

    def to_tool_definition(self) -> "ToolDefinition":
        """Convert to the LLM abstraction layer's ToolDefinition format.

        Returns a ToolDefinition compatible with
        backend/app/services/llm/base.py::ToolDefinition.
        """
        from app.services.llm.base import ToolDefinition
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )
```

#### MentorAgent Core Loop (`backend/app/agent/mentor.py`)

```python
"""MentorAgent — core agent loop for mentor interactions."""

import asyncio
import json
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import AgentTool
from app.services.llm.base import (
    ContentBlock,
    LLMProvider,
    StreamChunk,
    UnifiedMessage,
)
from app.services.llm.router import ModelRouter, TaskType
from app.services.profile import StudentProfile, load_profile, save_profile
from app.agent.prompts.mentor import build_system_prompt

logger = logging.getLogger(__name__)

MAX_TOOL_LOOPS = 10  # Safety limit to prevent infinite tool call loops


class MentorAgent:
    """The primary agent that handles all mentor-student interactions.

    Lifecycle:
    1. Instantiate per-request with user context
    2. Call process() with user message
    3. Yields StreamChunk objects for SSE streaming
    4. After response, triggers async profile update
    """

    def __init__(
        self,
        model_router: ModelRouter,
        tools: list[AgentTool],
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        self._router = model_router
        self._tools = {t.name: t for t in tools}
        self._tool_list = tools
        self._user_id = user_id
        self._conversation_id = conversation_id
        self._db = db

    async def process(
        self,
        user_message: str,
        conversation_history: list[UnifiedMessage],
        course_id: uuid.UUID | None = None,
    ) -> "AsyncIterator[StreamChunk]":
        """Process a user message through the agent loop.

        Args:
            user_message: The user's text message.
            conversation_history: Previous messages in this conversation
                (loaded from DB, already in UnifiedMessage format).
            course_id: Optional course context for this conversation.

        Yields:
            StreamChunk objects — the caller (chat API route) converts
            these to SSE events.
        """
        # 1. Load student profile
        profile = await load_profile(self._db, self._user_id)

        # 2. Build system prompt
        system_prompt = build_system_prompt(
            profile=profile,
            course_id=course_id,
            tools=self._tool_list,
        )

        # 3. Build messages list
        messages = [
            UnifiedMessage(role="system", content=system_prompt),
            *conversation_history,
            UnifiedMessage(role="user", content=user_message),
        ]

        # 4. Get LLM provider
        provider = await self._router.get_provider(TaskType.MENTOR_CHAT)

        # 5. Tool definitions for the LLM
        tool_defs = [t.to_tool_definition() for t in self._tool_list]

        # 6. Agent loop
        loop_count = 0
        while loop_count < MAX_TOOL_LOOPS:
            loop_count += 1

            # Accumulate full response for tool call detection
            text_chunks: list[str] = []
            tool_calls: list[dict] = []
            current_tool_call: dict | None = None
            tool_input_json = ""

            async for chunk in provider.chat_stream(
                messages=messages,
                tools=tool_defs if self._tools else None,
                max_tokens=4096,
                temperature=0.7,
            ):
                if chunk.type == "text_delta":
                    text_chunks.append(chunk.text or "")
                    yield chunk  # Stream text to frontend immediately

                elif chunk.type == "tool_use_start":
                    current_tool_call = {
                        "id": chunk.tool_use_id,
                        "name": chunk.tool_name,
                    }
                    tool_input_json = ""

                elif chunk.type == "tool_use_delta":
                    tool_input_json += chunk.tool_input_delta or ""

                elif chunk.type == "tool_use_end":
                    if current_tool_call:
                        try:
                            parsed_input = json.loads(tool_input_json) if tool_input_json else {}
                        except json.JSONDecodeError:
                            parsed_input = {}
                        current_tool_call["input"] = parsed_input
                        tool_calls.append(current_tool_call)
                        current_tool_call = None

                elif chunk.type == "message_end":
                    yield chunk  # Forward message_end to frontend

            # 7. If tool calls were made, execute them and loop
            if tool_calls:
                # Add assistant message with tool_use blocks
                assistant_blocks = []
                if text_chunks:
                    assistant_blocks.append(
                        ContentBlock(type="text", text="".join(text_chunks))
                    )
                for tc in tool_calls:
                    assistant_blocks.append(ContentBlock(
                        type="tool_use",
                        tool_use_id=tc["id"],
                        tool_name=tc["name"],
                        tool_input=tc["input"],
                    ))
                messages.append(UnifiedMessage(
                    role="assistant",
                    content=assistant_blocks,
                ))

                # Execute each tool and add results
                for tc in tool_calls:
                    tool = self._tools.get(tc["name"])
                    if tool:
                        try:
                            result = await tool.execute(**tc["input"])
                        except Exception as e:
                            logger.warning(f"Tool {tc['name']} failed: {e}")
                            result = f"Error executing tool: {e}"
                    else:
                        result = f"Unknown tool: {tc['name']}"

                    messages.append(UnifiedMessage(
                        role="tool_result",
                        content=[ContentBlock(
                            type="tool_result",
                            tool_use_id=tc["id"],
                            tool_result_content=result,
                        )],
                    ))

                continue  # Loop back for LLM to process tool results

            # 8. No tool calls — response complete
            break

        # 9. Trigger async profile update (non-blocking)
        asyncio.create_task(
            self._update_profile_async(user_message, "".join(text_chunks))
        )

    async def _update_profile_async(
        self, user_message: str, assistant_response: str
    ) -> None:
        """Background task: analyze interaction and update student profile.

        Uses a lightweight LLM call (CONTENT_ANALYSIS task type) to infer
        profile updates from the conversation exchange.
        """
        try:
            provider = await self._router.get_provider(TaskType.CONTENT_ANALYSIS)
            profile = await load_profile(self._db, self._user_id)

            analysis_prompt = f"""Analyze this learning interaction and suggest profile updates.

Current student profile:
{profile.model_dump_json(indent=2)}

User message: {user_message}
Assistant response: {assistant_response}

Return a JSON object with ONLY the fields that should be updated.
Follow the confidence rules:
- Record observations but only update profile after 3-5 consistent signals.
- Include a "observations" list of what you noticed.
- Include "updates" dict of fields to change (empty if insufficient confidence).

Response format:
{{"observations": ["..."], "updates": {{}}}}
"""
            response = await provider.chat(
                messages=[UnifiedMessage(role="user", content=analysis_prompt)],
                max_tokens=1024,
                temperature=0.3,
            )

            # Parse and apply updates (implementation detail in services/profile.py)
            text_content = next(
                (b.text for b in response.content if b.type == "text"), None
            )
            if text_content:
                from app.services.profile import apply_profile_updates
                await apply_profile_updates(self._db, self._user_id, text_content)

        except Exception as e:
            logger.error(f"Profile update failed: {e}")
            # Non-critical — do not propagate
```

**Key design points:**

- `process()` is an async generator yielding `StreamChunk` — the chat API route wraps these as SSE events.
- The agent loop runs up to `MAX_TOOL_LOOPS` iterations. Each iteration: stream LLM output, collect tool calls, execute tools, append results, loop.
- Text is streamed immediately to the frontend. Tool execution happens between loop iterations (not visible to the user as streaming pauses briefly).
- Profile update runs as a fire-and-forget `asyncio.create_task` after the response is complete.

### 2.2 Agent Tools

#### 2.2.1 Knowledge Retrieval Tool (`backend/app/agent/tools/knowledge.py`)

```python
"""RAG knowledge retrieval tool for the MentorAgent."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import AgentTool
from app.services.rag import RAGService


class KnowledgeSearchTool(AgentTool):
    """Search the knowledge base for relevant content chunks.

    The MentorAgent uses this tool to retrieve context from ingested
    content (Bilibili transcripts, PDFs) when answering student questions.
    """

    def __init__(self, db: AsyncSession, rag_service: RAGService,
                 course_id: uuid.UUID | None = None) -> None:
        self._db = db
        self._rag = rag_service
        self._course_id = course_id

    @property
    def name(self) -> str:
        return "search_knowledge"

    @property
    def description(self) -> str:
        return (
            "Search the course knowledge base for relevant content. "
            "Use this when the student asks about a concept, needs an explanation, "
            "or when you need to reference specific content from the learning materials. "
            "Returns relevant text passages with source references (timestamps, page numbers)."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query. Use natural language describing the concept or topic to search for.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default 5, max 10).",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, top_k: int = 5) -> str:
        top_k = min(top_k, 10)
        results = await self._rag.search(
            query=query,
            course_id=self._course_id,
            top_k=top_k,
        )
        if not results:
            return "No relevant content found in the knowledge base."

        # Format results for the LLM
        formatted = []
        for i, r in enumerate(results, 1):
            source_info = ""
            meta = r.get("metadata", {})
            if "start_time" in meta:
                source_info = f" [Video timestamp: {meta['start_time']}s - {meta.get('end_time', '?')}s]"
            elif "page" in meta:
                source_info = f" [PDF page: {meta['page']}]"
            formatted.append(f"[{i}]{source_info}\n{r['text']}")

        return "\n\n---\n\n".join(formatted)
```

#### 2.2.2 Student Profile Tool (`backend/app/agent/tools/profile.py`)

```python
"""Student profile read/update tool for the MentorAgent."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import AgentTool
from app.services.profile import load_profile


class ProfileReadTool(AgentTool):
    """Read the current student profile.

    The MentorAgent calls this at the start of conversations or when it
    needs to check specific profile data (e.g. weak_spots, learning_style).
    """

    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        self._db = db
        self._user_id = user_id

    @property
    def name(self) -> str:
        return "read_student_profile"

    @property
    def description(self) -> str:
        return (
            "Read the current student profile including learning style, competency levels, "
            "weak spots, strong spots, learning history, and mentor strategy. "
            "Use this to personalize your teaching approach."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Optional: specific section to read ('competency', 'learning_style', 'history', 'mentor_strategy', or 'all'). Defaults to 'all'.",
                    "enum": ["all", "competency", "learning_style", "history", "mentor_strategy"],
                    "default": "all",
                },
            },
            "required": [],
        }

    async def execute(self, section: str = "all") -> str:
        profile = await load_profile(self._db, self._user_id)
        if section == "all":
            return profile.model_dump_json(indent=2)
        elif hasattr(profile, section):
            return getattr(profile, section).model_dump_json(indent=2)
        else:
            return f"Unknown profile section: {section}"
```

#### 2.2.3 Progress Tracking Tool (`backend/app/agent/tools/progress.py`)

```python
"""Learning progress tracking tool for the MentorAgent."""

import json
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import AgentTool
from app.db.models.learning_record import LearningRecord


class ProgressTrackTool(AgentTool):
    """Track and query learning progress.

    The MentorAgent uses this to:
    - Record that a student has completed a section or exercise
    - Query what the student has already covered
    - Check recent learning activity
    """

    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        self._db = db
        self._user_id = user_id

    @property
    def name(self) -> str:
        return "track_progress"

    @property
    def description(self) -> str:
        return (
            "Track or query student learning progress. "
            "Use action='record' to log a learning event (e.g. section completed, exercise attempted). "
            "Use action='query' to check what the student has covered in a course."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["record", "query"],
                    "description": "'record' to log a learning event, 'query' to check progress.",
                },
                "course_id": {
                    "type": "string",
                    "description": "UUID of the course.",
                },
                "section_id": {
                    "type": "string",
                    "description": "UUID of the section (optional for query, required for record).",
                },
                "record_type": {
                    "type": "string",
                    "description": "Type of learning event: 'section_complete', 'exercise_attempt', 'video_watch', 'chat'.",
                },
                "data": {
                    "type": "object",
                    "description": "Additional data for the learning event (e.g. score, time_spent).",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        course_id: str | None = None,
        section_id: str | None = None,
        record_type: str | None = None,
        data: dict | None = None,
    ) -> str:
        if action == "record":
            return await self._record(course_id, section_id, record_type, data)
        elif action == "query":
            return await self._query(course_id)
        else:
            return f"Unknown action: {action}"

    async def _record(
        self,
        course_id: str | None,
        section_id: str | None,
        record_type: str | None,
        data: dict | None,
    ) -> str:
        if not record_type:
            return "Error: record_type is required for action='record'"

        record = LearningRecord(
            user_id=self._user_id,
            course_id=uuid.UUID(course_id) if course_id else None,
            section_id=uuid.UUID(section_id) if section_id else None,
            type=record_type,
            data=data or {},
        )
        self._db.add(record)
        await self._db.flush()
        return f"Recorded learning event: {record_type}"

    async def _query(self, course_id: str | None) -> str:
        stmt = (
            select(LearningRecord)
            .where(LearningRecord.user_id == self._user_id)
            .order_by(LearningRecord.created_at.desc())
            .limit(50)
        )
        if course_id:
            stmt = stmt.where(LearningRecord.course_id == uuid.UUID(course_id))

        result = await self._db.execute(stmt)
        records = result.scalars().all()

        if not records:
            return "No learning records found."

        summary = []
        for r in records:
            summary.append({
                "type": r.type,
                "section_id": str(r.section_id) if r.section_id else None,
                "data": r.data,
                "created_at": r.created_at.isoformat(),
            })
        return json.dumps(summary, indent=2, ensure_ascii=False)
```

### 2.3 System Prompt (`backend/app/agent/prompts/mentor.py`)

```python
"""System prompt template for the MentorAgent."""

from app.agent.tools.base import AgentTool
from app.services.profile import StudentProfile


def build_system_prompt(
    profile: StudentProfile,
    course_id: str | None = None,
    tools: list[AgentTool] | None = None,
) -> str:
    """Build the system prompt for the MentorAgent.

    The system prompt injects:
    - Student profile data (personalization)
    - Teaching principles (Socratic method, adaptive)
    - Mentor personality and push level
    - Available tools description (informational; actual tool schemas
      are passed separately via the tools parameter to the LLM)
    """

    # Extract mentor strategy settings
    strategy = profile.mentor_strategy
    personality = strategy.personality if strategy.personality else "encouraging"
    push_level = strategy.push_level if strategy.push_level else "gentle"
    current_approach = strategy.current_approach if strategy.current_approach else "adaptive"

    # Build weak/strong spots section
    competency_section = ""
    if profile.competency.weak_spots:
        competency_section += f"\n薄弱点: {', '.join(profile.competency.weak_spots)}"
    if profile.competency.strong_spots:
        competency_section += f"\n强项: {', '.join(profile.competency.strong_spots)}"
    if profile.competency.domains:
        domains_str = ", ".join(f"{k}: {v:.0%}" for k, v in profile.competency.domains.items())
        competency_section += f"\n领域掌握度: {domains_str}"

    return f"""你是 Socratiq 的 AI 导师。你的角色不是一个工具，而是一个真正的导师——你了解你的学生，记得他们的进步，用最适合他们的方式教学。

## 你的学生
- 名字: {profile.name or '(未设置)'}
- 学习目标: {', '.join(profile.learning_goals) if profile.learning_goals else '(未设置)'}
- 偏好语言: {profile.preferred_language}
- 学习节奏: {profile.learning_style.pace}
- 偏好示例优先: {'是' if profile.learning_style.prefers_examples else '否'}
- 偏好代码优先: {'是' if profile.learning_style.prefers_code_first else '否'}
- 注意力持续: {profile.learning_style.attention_span}
- 面对挑战: {profile.learning_style.response_to_challenge}
{competency_section}

## 教学原则
1. **苏格拉底式引导**: 不要直接给出答案。先问问题，引导学生自己思考和发现。
2. **自适应**: 根据学生的 pace 和 learning_style 调整讲解深度和速度。
3. **代码优先**: 如果学生 prefers_code_first，先给代码示例再解释概念。
4. **关注薄弱点**: 遇到学生 weak_spots 中的相关话题时，主动多解释。
5. **利用有效方式**: 参考 aha_moments 中记录的对学生有效的讲解方式。
6. **鼓励与推进**: 不只是回答问题，要推着学生往前走。给出下一步建议。
7. **使用工具**: 当需要引用课程内容时，先用 search_knowledge 检索相关内容，基于实际材料回答。

## 你的人格
- 风格: {personality}
- 推进力度: {push_level}
- 当前教学策略: {current_approach}

## 行为规范
- 回复使用学生的偏好语言 ({profile.preferred_language})
- 如果不确定某个知识点，使用 search_knowledge 工具检索
- 回复长度适中——太长学生会失去注意力，太短无法讲清楚
- 每次回复结尾，给出一个引导思考的问题或下一步建议
- 使用 Markdown 格式，代码块标注语言
"""
```

### 2.4 Student Profile Management (`backend/app/services/profile.py`)

```python
"""Student profile Pydantic model and database operations."""

import json
import logging
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User

logger = logging.getLogger(__name__)


# --- Pydantic models matching system-design.md Section 1.4 ---

class LearningStyle(BaseModel):
    pace: str = "moderate"                       # slow | moderate | fast
    prefers_examples: bool = True
    prefers_code_first: bool = True
    attention_span: str = "medium"               # short | medium | long
    best_time: str = "evening"
    response_to_challenge: str = "motivated"     # frustrated | neutral | motivated

class Competency(BaseModel):
    programming: dict[str, str] = Field(default_factory=dict)     # {"python": "intermediate"}
    domains: dict[str, float] = Field(default_factory=dict)       # {"llm_basics": 0.7}
    weak_spots: list[str] = Field(default_factory=list)
    strong_spots: list[str] = Field(default_factory=list)

class LearningHistory(BaseModel):
    courses_completed: list[str] = Field(default_factory=list)
    courses_in_progress: list[str] = Field(default_factory=list)
    labs_completed: list[str] = Field(default_factory=list)
    questions_asked: list[str] = Field(default_factory=list)
    mistakes_pattern: list[str] = Field(default_factory=list)
    aha_moments: list[str] = Field(default_factory=list)
    total_study_hours: float = 0
    streak_days: int = 0

class MentorStrategy(BaseModel):
    current_approach: str = ""
    personality: str = "encouraging"             # encouraging | direct | socratic
    push_level: str = "gentle"                   # gentle | moderate | firm
    last_interaction_summary: str = ""
    next_suggested_action: str = ""

class StudentProfile(BaseModel):
    name: str = ""
    learning_goals: list[str] = Field(default_factory=list)
    motivation: str = ""
    preferred_language: str = "zh-CN"
    competency: Competency = Field(default_factory=Competency)
    learning_style: LearningStyle = Field(default_factory=LearningStyle)
    history: LearningHistory = Field(default_factory=LearningHistory)
    mentor_strategy: MentorStrategy = Field(default_factory=MentorStrategy)


# --- Database operations ---

async def load_profile(db: AsyncSession, user_id: uuid.UUID) -> StudentProfile:
    """Load student profile from users.student_profile JSONB field.

    Returns a default StudentProfile if the field is empty or missing.
    """
    stmt = select(User.student_profile).where(User.id == user_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row and isinstance(row, dict) and row:
        return StudentProfile(**row)
    return StudentProfile()


async def save_profile(
    db: AsyncSession, user_id: uuid.UUID, profile: StudentProfile
) -> None:
    """Save student profile to users.student_profile JSONB field."""
    stmt = (
        update(User)
        .where(User.id == user_id)
        .values(student_profile=profile.model_dump())
    )
    await db.execute(stmt)
    await db.commit()


async def apply_profile_updates(
    db: AsyncSession, user_id: uuid.UUID, llm_response_text: str
) -> None:
    """Parse LLM profile analysis response and apply updates.

    The LLM returns JSON with:
    {"observations": [...], "updates": {...}}

    Observations are stored for confidence tracking.
    Updates are merged into the profile only when confidence is sufficient.
    """
    try:
        # Extract JSON from LLM response (may be wrapped in markdown code blocks)
        text = llm_response_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        analysis = json.loads(text)
        observations = analysis.get("observations", [])
        updates = analysis.get("updates", {})

        if not updates and not observations:
            return

        profile = await load_profile(db, user_id)

        # Store observations in mentor_strategy for future reference
        if observations:
            summary = "; ".join(observations[:5])  # Keep last 5
            profile.mentor_strategy.last_interaction_summary = summary

        # Apply direct updates (the LLM should only suggest high-confidence ones)
        if updates:
            profile_dict = profile.model_dump()
            _deep_merge(profile_dict, updates)
            profile = StudentProfile(**profile_dict)

        await save_profile(db, user_id, profile)

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Failed to parse profile update: {e}")


def _deep_merge(base: dict, updates: dict) -> None:
    """Recursively merge updates into base dict (mutates base)."""
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        elif key in base and isinstance(base[key], list) and isinstance(value, list):
            # For lists, extend with new unique items
            for item in value:
                if item not in base[key]:
                    base[key].append(item)
        else:
            base[key] = value
```

### 2.5 RAG Retrieval Service (`backend/app/services/rag.py`)

```python
"""RAG (Retrieval-Augmented Generation) service using pgvector."""

import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.content_chunk import ContentChunk
from app.db.models.course import Section
from app.services.llm.base import UnifiedMessage
from app.services.llm.router import ModelRouter, TaskType


class RAGService:
    """Retrieves relevant content chunks via pgvector cosine similarity.

    Usage:
        rag = RAGService(model_router=router)
        results = await rag.search(db, query="What is attention?", course_id=..., top_k=5)
    """

    def __init__(self, model_router: ModelRouter) -> None:
        self._router = model_router

    async def search(
        self,
        db: AsyncSession,
        query: str,
        course_id: uuid.UUID | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search content_chunks for relevant passages.

        Args:
            db: Database session.
            query: Natural language search query.
            course_id: Optional — restrict to chunks belonging to this course's sections.
            top_k: Number of results to return.

        Returns:
            List of dicts with keys: text, metadata, score, chunk_id, source_id.
        """
        # 1. Compute query embedding
        query_embedding = await self._compute_embedding(query)

        # 2. Build pgvector similarity query
        # Uses cosine distance: 1 - (embedding <=> query_embedding)
        # <=> is the cosine distance operator in pgvector
        embedding_literal = f"[{','.join(str(x) for x in query_embedding)}]"

        if course_id:
            # Filter to chunks belonging to sections of this course
            stmt = text("""
                SELECT cc.id, cc.text, cc.metadata_, cc.source_id,
                       1 - (cc.embedding <=> :embedding::vector) as score
                FROM content_chunks cc
                JOIN sections s ON cc.section_id = s.id
                WHERE s.course_id = :course_id
                  AND cc.embedding IS NOT NULL
                ORDER BY cc.embedding <=> :embedding::vector
                LIMIT :top_k
            """)
            params = {
                "embedding": embedding_literal,
                "course_id": str(course_id),
                "top_k": top_k,
            }
        else:
            stmt = text("""
                SELECT cc.id, cc.text, cc.metadata_, cc.source_id,
                       1 - (cc.embedding <=> :embedding::vector) as score
                FROM content_chunks cc
                WHERE cc.embedding IS NOT NULL
                ORDER BY cc.embedding <=> :embedding::vector
                LIMIT :top_k
            """)
            params = {
                "embedding": embedding_literal,
                "top_k": top_k,
            }

        result = await db.execute(stmt, params)
        rows = result.fetchall()

        return [
            {
                "chunk_id": str(row[0]),
                "text": row[1],
                "metadata": row[2] or {},
                "source_id": str(row[3]),
                "score": float(row[4]),
            }
            for row in rows
        ]

    async def _compute_embedding(self, text: str) -> list[float]:
        """Compute embedding for the query text using the embedding model.

        Uses ModelRouter with TaskType.EMBEDDING to get the configured
        embedding provider. The embedding provider is expected to be an
        OpenAI-compatible provider that supports the embeddings endpoint.
        """
        # For MVP, we use the OpenAI embeddings API via the provider
        # The embedding provider must implement an embedding-specific method
        # For now, use a direct openai SDK call routed through our config
        provider = await self._router.get_provider(TaskType.EMBEDDING)

        # The provider's model_id tells us which embedding model to use
        # We need to call the embeddings endpoint, not the chat endpoint
        # This requires adding an embed() method to LLMProvider or using
        # the openai SDK directly with the configured API key/base_url

        # Implementation approach: use the openai SDK directly since
        # embedding is a fundamentally different API shape than chat.
        # The ModelRouter gives us the config (model_id, api_key, base_url).
        from openai import AsyncOpenAI

        # Access the provider's configuration
        # For OpenAICompatProvider, we can access its client
        if hasattr(provider, '_client'):
            client = provider._client
        else:
            # Fallback: create a client from the provider's model config
            client = AsyncOpenAI()

        response = await client.embeddings.create(
            model=provider.model_id(),
            input=text,
        )
        return response.data[0].embedding
```

**Note on embedding**: The RAG service needs to compute embeddings for queries. Since the LLMProvider interface is designed for chat, and embedding is a different API, the implementation accesses the underlying OpenAI client directly. This is an acceptable pragmatic choice for MVP. A future iteration could add an `embed()` method to the `LLMProvider` ABC.

### 2.6 Chat API (`backend/app/api/routes/chat.py`)

```python
"""Chat API routes — SSE streaming mentor conversations."""

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_db, get_model_router
from app.db.models.conversation import Conversation
from app.db.models.message import Message
from app.services.llm.base import UnifiedMessage
from app.services.llm.router import ModelRouter
from app.agent.mentor import MentorAgent
from app.agent.tools.knowledge import KnowledgeSearchTool
from app.agent.tools.profile import ProfileReadTool
from app.agent.tools.progress import ProgressTrackTool
from app.services.rag import RAGService

router = APIRouter(prefix="/api", tags=["chat"])

# --- Request/Response schemas ---

class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None  # None = new conversation
    course_id: str | None = None

class ConversationResponse(BaseModel):
    id: str
    course_id: str | None
    mode: str
    created_at: str
    updated_at: str
    last_message_preview: str | None = None

class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    tool_calls: dict | None = None
    created_at: str

# --- MVP user identification ---
# No auth for MVP. Use a fixed user_id or X-User-Id header.

USER_ID_HEADER = "X-User-Id"
DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

def get_user_id(request: Request) -> uuid.UUID:
    """Extract user ID from header or return default."""
    header = request.headers.get(USER_ID_HEADER)
    if header:
        try:
            return uuid.UUID(header)
        except ValueError:
            pass
    return DEFAULT_USER_ID


# --- SSE Chat endpoint ---

@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    router: ModelRouter = Depends(get_model_router),
):
    """Send a message and receive a streaming SSE response.

    SSE event types:
    - event: text_delta    data: {"text": "..."}
    - event: tool_start    data: {"tool": "search_knowledge", "id": "..."}
    - event: tool_end      data: {"tool": "search_knowledge", "id": "..."}
    - event: message_end   data: {"conversation_id": "...", "message_id": "..."}
    - event: error         data: {"error": "..."}
    """
    user_id = get_user_id(request)

    # 1. Get or create conversation
    if body.conversation_id:
        conv_id = uuid.UUID(body.conversation_id)
        stmt = select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == user_id,
        )
        result = await db.execute(stmt)
        conversation = result.scalar_one_or_none()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = Conversation(
            user_id=user_id,
            course_id=uuid.UUID(body.course_id) if body.course_id else None,
            mode="qa",
        )
        db.add(conversation)
        await db.flush()

    conv_id = conversation.id
    course_id = conversation.course_id

    # 2. Save user message to DB
    user_msg = Message(
        conversation_id=conv_id,
        role="user",
        content=body.message,
    )
    db.add(user_msg)
    await db.flush()

    # 3. Load conversation history (last 20 messages for working memory)
    stmt = (
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
        .limit(20)
    )
    result = await db.execute(stmt)
    history_msgs = result.scalars().all()

    # Convert to UnifiedMessage format (exclude the just-added user message
    # since MentorAgent adds it)
    conversation_history = []
    for msg in history_msgs[:-1]:  # Exclude the last one (just added)
        role = msg.role
        if role == "tool_result":
            # Reconstruct tool_result format if needed
            conversation_history.append(UnifiedMessage(role=role, content=msg.content))
        else:
            conversation_history.append(UnifiedMessage(role=role, content=msg.content))

    # 4. Set up agent tools
    rag_service = RAGService(model_router=router)
    tools = [
        KnowledgeSearchTool(db=db, rag_service=rag_service, course_id=course_id),
        ProfileReadTool(db=db, user_id=user_id),
        ProgressTrackTool(db=db, user_id=user_id),
    ]

    # 5. Create agent
    agent = MentorAgent(
        model_router=router,
        tools=tools,
        user_id=user_id,
        conversation_id=conv_id,
        db=db,
    )

    # 6. Stream response via SSE
    async def event_generator():
        full_response_text = []
        try:
            async for chunk in agent.process(
                user_message=body.message,
                conversation_history=conversation_history,
                course_id=course_id,
            ):
                if chunk.type == "text_delta":
                    full_response_text.append(chunk.text or "")
                    yield {
                        "event": "text_delta",
                        "data": json.dumps({"text": chunk.text}),
                    }
                elif chunk.type == "tool_use_start":
                    yield {
                        "event": "tool_start",
                        "data": json.dumps({
                            "tool": chunk.tool_name,
                            "id": chunk.tool_use_id,
                        }),
                    }
                elif chunk.type == "message_end":
                    # Save assistant message to DB
                    assistant_msg = Message(
                        conversation_id=conv_id,
                        role="assistant",
                        content="".join(full_response_text),
                    )
                    db.add(assistant_msg)
                    await db.flush()

                    yield {
                        "event": "message_end",
                        "data": json.dumps({
                            "conversation_id": str(conv_id),
                            "message_id": str(assistant_msg.id),
                        }),
                    }

        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}),
            }

    return EventSourceResponse(event_generator())


# --- Conversation CRUD ---

@router.get("/conversations")
async def list_conversations(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[ConversationResponse]:
    """List all conversations for the current user."""
    user_id = get_user_id(request)
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
    )
    result = await db.execute(stmt)
    convs = result.scalars().all()

    responses = []
    for c in convs:
        # Get last message preview
        msg_stmt = (
            select(Message.content)
            .where(Message.conversation_id == c.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        msg_result = await db.execute(msg_stmt)
        last_msg = msg_result.scalar_one_or_none()

        responses.append(ConversationResponse(
            id=str(c.id),
            course_id=str(c.course_id) if c.course_id else None,
            mode=c.mode,
            created_at=c.created_at.isoformat(),
            updated_at=c.updated_at.isoformat(),
            last_message_preview=last_msg[:100] if last_msg else None,
        ))
    return responses


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[MessageResponse]:
    """Get all messages in a conversation."""
    user_id = get_user_id(request)

    # Verify ownership
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user_id,
    )
    result = await db.execute(stmt)
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Get messages
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()

    return [
        MessageResponse(
            id=str(m.id),
            role=m.role,
            content=m.content,
            tool_calls=m.tool_calls,
            created_at=m.created_at.isoformat(),
        )
        for m in messages
    ]
```

#### Registering Chat Routes in main.py

Add to `backend/app/main.py`:

```python
from app.api.routes import health, models, model_routes, tasks, chat

# ... existing code ...

app.include_router(chat.router)
```

#### Additional Course Read Endpoints (`backend/app/api/routes/courses.py`)

```python
"""Course and section read API routes (needed by frontend)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models.course import Course, Section
from app.db.models.source import Source

router = APIRouter(prefix="/api", tags=["courses"])


class SectionResponse(BaseModel):
    id: str
    title: str
    order_index: int | None
    source_start: str | None
    source_end: str | None
    difficulty: int
    content: dict

class SourceBrief(BaseModel):
    id: str
    type: str
    url: str | None
    title: str | None

class CourseDetailResponse(BaseModel):
    id: str
    title: str
    description: str | None
    sections: list[SectionResponse]
    sources: list[SourceBrief]
    created_at: str

class CourseListItem(BaseModel):
    id: str
    title: str
    description: str | None
    section_count: int
    created_at: str


@router.get("/courses")
async def list_courses(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[CourseListItem]:
    """List all courses for the current user."""
    from app.api.routes.chat import get_user_id, DEFAULT_USER_ID
    user_id = get_user_id(request)

    stmt = (
        select(Course)
        .where(Course.created_by == user_id)
        .order_by(Course.created_at.desc())
    )
    result = await db.execute(stmt)
    courses = result.scalars().all()

    items = []
    for c in courses:
        sec_stmt = select(Section).where(Section.course_id == c.id)
        sec_result = await db.execute(sec_stmt)
        section_count = len(sec_result.scalars().all())
        items.append(CourseListItem(
            id=str(c.id),
            title=c.title,
            description=c.description,
            section_count=section_count,
            created_at=c.created_at.isoformat(),
        ))
    return items


@router.get("/courses/{course_id}")
async def get_course(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> CourseDetailResponse:
    """Get course detail with sections and sources."""
    stmt = select(Course).where(Course.id == course_id)
    result = await db.execute(stmt)
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    # Load sections
    sec_stmt = (
        select(Section)
        .where(Section.course_id == course_id)
        .order_by(Section.order_index.asc())
    )
    sec_result = await db.execute(sec_stmt)
    sections = sec_result.scalars().all()

    # Load sources via course_sources join
    from app.db.models.course import CourseSource
    src_stmt = (
        select(Source)
        .join(CourseSource, CourseSource.source_id == Source.id)
        .where(CourseSource.course_id == course_id)
    )
    src_result = await db.execute(src_stmt)
    sources = src_result.scalars().all()

    return CourseDetailResponse(
        id=str(course.id),
        title=course.title,
        description=course.description,
        sections=[
            SectionResponse(
                id=str(s.id),
                title=s.title,
                order_index=s.order_index,
                source_start=s.source_start,
                source_end=s.source_end,
                difficulty=s.difficulty,
                content=s.content or {},
            )
            for s in sections
        ],
        sources=[
            SourceBrief(
                id=str(s.id),
                type=s.type,
                url=s.url,
                title=s.title,
            )
            for s in sources
        ],
        created_at=course.created_at.isoformat(),
    )
```

Register in main.py:
```python
from app.api.routes import health, models, model_routes, tasks, chat, courses

app.include_router(courses.router)
```

### 2.7 Memory System v1

For MVP, the memory system has three layers:

| Layer | Storage | Access Pattern |
|-------|---------|---------------|
| **Working memory** | Last 20 messages loaded from `messages` table | Loaded per-request in chat endpoint |
| **Profile memory** | `users.student_profile` JSONB | Loaded by MentorAgent via `load_profile()`, injected into system prompt |
| **Progress memory** | `learning_records` table | Queried by `ProgressTrackTool` when agent needs it |

No separate memory manager class is needed for MVP. The three access patterns above cover the required functionality.

---

## 3. PART 2 — Frontend (Next.js)

### 3.1 Project Setup

#### Initialize

```bash
cd socratiq/
npx create-next-app@latest frontend \
  --typescript --tailwind --eslint --app --src-dir=false \
  --import-alias="@/*" --use-npm
```

#### Install Dependencies

```bash
cd frontend/
npm install zustand eventsource-parser react-markdown remark-gfm
npx shadcn@latest init  # Choose: New York style, Zinc base, CSS variables: yes
npx shadcn@latest add button input card dialog scroll-area badge tabs separator skeleton avatar dropdown-menu sheet textarea toast
```

#### Directory Structure

```
frontend/
├── app/
│   ├── layout.tsx              # Root layout (fonts, theme, providers)
│   ├── page.tsx                # Dashboard / landing
│   ├── import/
│   │   └── page.tsx            # Content import page
│   ├── courses/
│   │   └── [id]/
│   │       └── page.tsx        # Course detail page
│   ├── learn/
│   │   └── [sectionId]/
│   │       └── page.tsx        # Learning page (video + chat)
│   └── settings/
│       └── page.tsx            # Model configuration settings
├── components/
│   ├── ui/                     # shadcn/ui primitives (auto-generated)
│   ├── layout/
│   │   ├── sidebar.tsx         # App sidebar navigation
│   │   └── header.tsx          # Top header bar
│   ├── mentor-chat/
│   │   ├── chat-panel.tsx      # Main chat container
│   │   ├── message-bubble.tsx  # Single message component
│   │   ├── chat-input.tsx      # Message input with send button
│   │   └── streaming-text.tsx  # Animated streaming text display
│   ├── video-player/
│   │   └── bilibili-player.tsx # Bilibili iframe embed
│   ├── pdf-viewer/
│   │   └── pdf-viewer.tsx      # Simple PDF display (iframe)
│   ├── course/
│   │   ├── course-card.tsx     # Course card for dashboard list
│   │   └── section-list.tsx    # Section list for course detail
│   └── import/
│       └── import-form.tsx     # URL paste / file upload form
├── lib/
│   ├── api.ts                  # Backend API client
│   ├── sse.ts                  # SSE streaming helper
│   └── stores/
│       ├── chat-store.ts       # Zustand: chat state
│       └── course-store.ts     # Zustand: course state
├── tailwind.config.ts
├── tsconfig.json
├── next.config.js
└── package.json
```

### 3.2 Root Layout (`app/layout.tsx`)

```tsx
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Socratiq",
  description: "AI-powered adaptive learning system",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN" className="dark">
      <body className={inter.className}>
        <div className="min-h-screen bg-background text-foreground">
          {children}
        </div>
      </body>
    </html>
  );
}
```

**Theme**: Dark mode by default. Tailwind CSS `dark` class on `<html>`. shadcn/ui uses CSS variables — configure in `globals.css` with dark color scheme.

### 3.3 API Client (`lib/api.ts`)

```typescript
/**
 * Backend API client.
 *
 * All backend calls go through this module.
 * Base URL defaults to http://localhost:8000 in development.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface FetchOptions extends RequestInit {
  /** If true, don't parse response as JSON */
  raw?: boolean;
}

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const { raw, ...fetchOptions } = options;
  const url = `${API_BASE}${path}`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((fetchOptions.headers as Record<string, string>) || {}),
  };

  const res = await fetch(url, {
    ...fetchOptions,
    headers,
  });

  if (!res.ok) {
    const body = await res.text();
    throw new ApiError(res.status, body);
  }

  if (raw) return res as unknown as T;
  return res.json();
}

// --- Chat API ---

export interface ChatRequest {
  message: string;
  conversation_id?: string;
  course_id?: string;
}

/**
 * Send a chat message and return the raw Response for SSE streaming.
 * The caller should use lib/sse.ts to parse the SSE stream.
 */
export async function sendChatMessage(body: ChatRequest): Promise<Response> {
  const url = `${API_BASE}/api/chat`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await res.text());
  }
  return res;
}

// --- Conversations API ---

export interface Conversation {
  id: string;
  course_id: string | null;
  mode: string;
  created_at: string;
  updated_at: string;
  last_message_preview: string | null;
}

export interface ChatMessage {
  id: string;
  role: string;
  content: string;
  tool_calls: Record<string, unknown> | null;
  created_at: string;
}

export function getConversations(): Promise<Conversation[]> {
  return request("/api/conversations");
}

export function getConversationMessages(id: string): Promise<ChatMessage[]> {
  return request(`/api/conversations/${id}/messages`);
}

// --- Courses API ---

export interface CourseListItem {
  id: string;
  title: string;
  description: string | null;
  section_count: number;
  created_at: string;
}

export interface SectionDetail {
  id: string;
  title: string;
  order_index: number | null;
  source_start: string | null;
  source_end: string | null;
  difficulty: number;
  content: Record<string, unknown>;
}

export interface SourceBrief {
  id: string;
  type: string;
  url: string | null;
  title: string | null;
}

export interface CourseDetail {
  id: string;
  title: string;
  description: string | null;
  sections: SectionDetail[];
  sources: SourceBrief[];
  created_at: string;
}

export function getCourses(): Promise<CourseListItem[]> {
  return request("/api/courses");
}

export function getCourse(id: string): Promise<CourseDetail> {
  return request(`/api/courses/${id}`);
}

// --- Import API (calls Sub-project B endpoints) ---

export interface ImportRequest {
  url?: string;
  // file upload handled separately via FormData
}

export interface ImportResponse {
  task_id: string;
  source_id: string;
}

export function importUrl(url: string): Promise<ImportResponse> {
  return request("/api/sources/import", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

export function getTaskStatus(taskId: string): Promise<{ state: string; result: unknown }> {
  return request(`/api/tasks/${taskId}/status`);
}

// --- Models API (Sub-project A) ---

export interface ModelConfig {
  name: string;
  provider_type: string;
  model_id: string;
  base_url: string | null;
  supports_tool_use: boolean;
  supports_streaming: boolean;
  max_tokens_limit: number;
  is_active: boolean;
}

export interface ModelRoute {
  task_type: string;
  model_name: string;
}

export function getModels(): Promise<ModelConfig[]> {
  return request("/api/models");
}

export function getModelRoutes(): Promise<ModelRoute[]> {
  return request("/api/model-routes");
}

export function updateModelRoutes(routes: ModelRoute[]): Promise<void> {
  return request("/api/model-routes", {
    method: "PUT",
    body: JSON.stringify(routes),
  });
}

export function testModel(name: string): Promise<{ success: boolean; message: string }> {
  return request(`/api/models/${name}/test`, { method: "POST" });
}
```

### 3.4 SSE Helper (`lib/sse.ts`)

```typescript
/**
 * SSE streaming helper for POST-based SSE (chat API).
 *
 * The browser's native EventSource only supports GET.
 * We use fetch + ReadableStream + eventsource-parser instead.
 */

import { createParser, type ParsedEvent, type ReconnectInterval } from "eventsource-parser";

export interface SSECallbacks {
  onTextDelta?: (text: string) => void;
  onToolStart?: (tool: string, id: string) => void;
  onToolEnd?: (tool: string, id: string) => void;
  onMessageEnd?: (data: { conversation_id: string; message_id: string }) => void;
  onError?: (error: string) => void;
}

/**
 * Process an SSE response from the chat API.
 *
 * @param response - The fetch Response object (must be streaming)
 * @param callbacks - Event handlers for each SSE event type
 */
export async function processSSEResponse(
  response: Response,
  callbacks: SSECallbacks,
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Response body is not readable");

  const decoder = new TextDecoder();
  const parser = createParser((event: ParsedEvent | ReconnectInterval) => {
    if (event.type !== "event") return;

    const data = JSON.parse(event.data);

    switch (event.event) {
      case "text_delta":
        callbacks.onTextDelta?.(data.text);
        break;
      case "tool_start":
        callbacks.onToolStart?.(data.tool, data.id);
        break;
      case "tool_end":
        callbacks.onToolEnd?.(data.tool, data.id);
        break;
      case "message_end":
        callbacks.onMessageEnd?.(data);
        break;
      case "error":
        callbacks.onError?.(data.error);
        break;
    }
  });

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.feed(decoder.decode(value, { stream: true }));
    }
  } finally {
    reader.releaseLock();
  }
}
```

### 3.5 Zustand Stores

#### Chat Store (`lib/stores/chat-store.ts`)

```typescript
import { create } from "zustand";

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  isStreaming?: boolean;
  timestamp: string;
}

interface ChatState {
  messages: Message[];
  conversationId: string | null;
  isStreaming: boolean;
  currentStreamText: string;

  // Actions
  setConversationId: (id: string | null) => void;
  addMessage: (message: Message) => void;
  setMessages: (messages: Message[]) => void;
  setStreaming: (streaming: boolean) => void;
  appendStreamText: (text: string) => void;
  finalizeStream: (messageId: string) => void;
  clearChat: () => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  conversationId: null,
  isStreaming: false,
  currentStreamText: "",

  setConversationId: (id) => set({ conversationId: id }),

  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),

  setMessages: (messages) => set({ messages }),

  setStreaming: (streaming) =>
    set({ isStreaming: streaming, currentStreamText: streaming ? "" : get().currentStreamText }),

  appendStreamText: (text) =>
    set((state) => ({ currentStreamText: state.currentStreamText + text })),

  finalizeStream: (messageId) =>
    set((state) => ({
      isStreaming: false,
      messages: [
        ...state.messages,
        {
          id: messageId,
          role: "assistant",
          content: state.currentStreamText,
          timestamp: new Date().toISOString(),
        },
      ],
      currentStreamText: "",
    })),

  clearChat: () =>
    set({ messages: [], conversationId: null, isStreaming: false, currentStreamText: "" }),
}));
```

#### Course Store (`lib/stores/course-store.ts`)

```typescript
import { create } from "zustand";
import type { CourseListItem, CourseDetail } from "@/lib/api";

interface CourseState {
  courses: CourseListItem[];
  currentCourse: CourseDetail | null;
  isLoading: boolean;

  setCourses: (courses: CourseListItem[]) => void;
  setCurrentCourse: (course: CourseDetail | null) => void;
  setLoading: (loading: boolean) => void;
}

export const useCourseStore = create<CourseState>((set) => ({
  courses: [],
  currentCourse: null,
  isLoading: false,

  setCourses: (courses) => set({ courses }),
  setCurrentCourse: (course) => set({ currentCourse: course }),
  setLoading: (loading) => set({ isLoading: loading }),
}));
```

### 3.6 Pages

#### 3.6.1 Dashboard (`app/page.tsx`)

The dashboard shows:
- List of user's courses (cards with title, description, section count, progress)
- "Import new content" CTA button (links to `/import`)
- Recent activity / last conversation preview

Layout: Sidebar on left (navigation), main content area.

```tsx
// Pseudocode structure
export default function DashboardPage() {
  // Fetch courses via getCourses()
  // Fetch recent conversations via getConversations()

  return (
    <AppLayout>
      <div className="p-6 space-y-6">
        <header>
          <h1>Dashboard</h1>
          <Link href="/import"><Button>Import Content</Button></Link>
        </header>

        <section>
          <h2>My Courses</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {courses.map(c => <CourseCard key={c.id} course={c} />)}
          </div>
        </section>

        <section>
          <h2>Recent Conversations</h2>
          {/* List of conversation previews */}
        </section>
      </div>
    </AppLayout>
  );
}
```

#### 3.6.2 Import Page (`app/import/page.tsx`)

Allows users to paste a Bilibili URL or upload a PDF. Calls the Sub-project B import API, then polls task status.

```tsx
// Pseudocode structure
export default function ImportPage() {
  // State: url input, upload file, task status, polling

  // On submit URL: call importUrl() → get task_id → poll getTaskStatus()
  // On upload PDF: POST FormData to /api/sources/upload → get task_id → poll
  // When task completes: redirect to /courses/[new_course_id]

  return (
    <AppLayout>
      <div className="max-w-2xl mx-auto p-6">
        <h1>Import Learning Content</h1>

        <Tabs defaultValue="url">
          <TabsList>
            <TabsTrigger value="url">Paste URL</TabsTrigger>
            <TabsTrigger value="pdf">Upload PDF</TabsTrigger>
          </TabsList>

          <TabsContent value="url">
            <Input placeholder="Paste Bilibili video URL..." />
            <Button>Import</Button>
          </TabsContent>

          <TabsContent value="pdf">
            <input type="file" accept=".pdf" />
            <Button>Upload</Button>
          </TabsContent>
        </Tabs>

        {/* Task progress indicator */}
        {taskId && <ImportProgress taskId={taskId} />}
      </div>
    </AppLayout>
  );
}
```

#### 3.6.3 Course Detail (`app/courses/[id]/page.tsx`)

Displays course metadata, ordered section list with difficulty badges, and links to the learning page.

```tsx
// Pseudocode structure
export default function CourseDetailPage({ params }: { params: { id: string } }) {
  // Fetch course via getCourse(params.id)

  return (
    <AppLayout>
      <div className="max-w-4xl mx-auto p-6">
        <h1>{course.title}</h1>
        <p>{course.description}</p>

        <SectionList sections={course.sections} courseId={course.id} />

        {/* Source references */}
        <div>
          <h3>Sources</h3>
          {course.sources.map(s => <SourceBadge key={s.id} source={s} />)}
        </div>
      </div>
    </AppLayout>
  );
}
```

#### 3.6.4 Learning Page (`app/learn/[sectionId]/page.tsx`)

The core learning experience. Two-panel layout:
- **Left panel (60% width)**: Video player (Bilibili embed) or PDF viewer
- **Right panel (40% width)**: Mentor chat panel

```tsx
// Pseudocode structure
export default function LearnPage({ params }: { params: { sectionId: string } }) {
  // Load section data (includes source info for video/PDF)
  // Load or create conversation for this section's course

  return (
    <div className="flex h-screen">
      {/* Left: Content */}
      <div className="w-3/5 border-r border-border">
        {section.source.type === "bilibili" ? (
          <BilibiliPlayer bvid={extractBvid(section.source.url)} />
        ) : (
          <PdfViewer url={section.source.url} />
        )}

        {/* Section content / study notes below video */}
        <div className="p-4 overflow-y-auto">
          <h2>{section.title}</h2>
          {/* Rendered section content */}
        </div>
      </div>

      {/* Right: Mentor Chat */}
      <div className="w-2/5 flex flex-col">
        <ChatPanel courseId={section.courseId} />
      </div>
    </div>
  );
}
```

#### 3.6.5 Settings Page (`app/settings/page.tsx`)

Displays and manages LLM model configurations and routing. Uses the model management API from Sub-project A.

```tsx
// Pseudocode structure
export default function SettingsPage() {
  // Fetch models via getModels()
  // Fetch routes via getModelRoutes()

  return (
    <AppLayout>
      <div className="max-w-4xl mx-auto p-6 space-y-8">
        <h1>Settings</h1>

        <section>
          <h2>Model Configurations</h2>
          {/* Table of configured models with edit/delete/test */}
          {/* Add new model button */}
        </section>

        <section>
          <h2>Model Routing</h2>
          {/* For each task type, dropdown to select which model to use */}
          {/* Task types: Mentor Chat, Content Analysis, Evaluation, Embedding */}
        </section>
      </div>
    </AppLayout>
  );
}
```

### 3.7 Key Components

#### 3.7.1 Chat Panel (`components/mentor-chat/chat-panel.tsx`)

```tsx
// Pseudocode structure — key behaviors:

// 1. On mount: load conversation history from API (if conversationId exists)
// 2. User types message → append to local state → call sendChatMessage()
// 3. Parse SSE stream via processSSEResponse():
//    - text_delta → append to streaming display
//    - tool_start → show "Searching knowledge base..." indicator
//    - message_end → finalize message, store conversation_id
// 4. Auto-scroll to bottom on new content
// 5. Show markdown-rendered messages (react-markdown + remark-gfm)
// 6. Handle error events gracefully

interface ChatPanelProps {
  courseId?: string;
}

export function ChatPanel({ courseId }: ChatPanelProps) {
  const {
    messages, conversationId, isStreaming, currentStreamText,
    addMessage, setStreaming, appendStreamText, finalizeStream,
    setConversationId,
  } = useChatStore();

  const scrollRef = useRef<HTMLDivElement>(null);

  async function handleSend(text: string) {
    // 1. Add user message to local state
    addMessage({ id: crypto.randomUUID(), role: "user", content: text, timestamp: new Date().toISOString() });

    // 2. Start streaming
    setStreaming(true);

    // 3. Send request
    const response = await sendChatMessage({
      message: text,
      conversation_id: conversationId ?? undefined,
      course_id: courseId,
    });

    // 4. Process SSE
    await processSSEResponse(response, {
      onTextDelta: (t) => appendStreamText(t),
      onMessageEnd: (data) => {
        finalizeStream(data.message_id);
        setConversationId(data.conversation_id);
      },
      onError: (err) => {
        setStreaming(false);
        // Show error toast
      },
    });
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages area */}
      <ScrollArea className="flex-1 p-4">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {isStreaming && (
          <MessageBubble
            message={{ id: "streaming", role: "assistant", content: currentStreamText, isStreaming: true, timestamp: "" }}
          />
        )}
        <div ref={scrollRef} />
      </ScrollArea>

      {/* Input area */}
      <ChatInput onSend={handleSend} disabled={isStreaming} />
    </div>
  );
}
```

#### 3.7.2 Message Bubble (`components/mentor-chat/message-bubble.tsx`)

```tsx
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MessageBubbleProps {
  message: {
    role: string;
    content: string;
    isStreaming?: boolean;
  };
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}>
      <div
        className={`max-w-[85%] rounded-lg px-4 py-3 ${
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-foreground"
        }`}
      >
        {isUser ? (
          <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="prose prose-sm prose-invert max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
            {message.isStreaming && (
              <span className="inline-block w-2 h-4 bg-foreground animate-pulse ml-0.5" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
```

#### 3.7.3 Bilibili Player (`components/video-player/bilibili-player.tsx`)

```tsx
interface BilibiliPlayerProps {
  bvid: string;
  /** Start time in seconds */
  startTime?: number;
}

export function BilibiliPlayer({ bvid, startTime }: BilibiliPlayerProps) {
  const src = `//player.bilibili.com/player.html?bvid=${bvid}&page=1&high_quality=1&danmaku=0${
    startTime ? `&t=${startTime}` : ""
  }`;

  return (
    <div className="relative w-full" style={{ paddingBottom: "56.25%" }}>
      <iframe
        src={src}
        className="absolute inset-0 w-full h-full"
        allowFullScreen
        sandbox="allow-scripts allow-same-origin allow-popups"
      />
    </div>
  );
}
```

#### 3.7.4 App Layout (`components/layout/sidebar.tsx`)

```tsx
// Sidebar navigation matching the prototype.jsx Sidebar component
// Links: Dashboard (/), My Courses (also /), Import (/import), Settings (/settings)

interface AppLayoutProps {
  children: React.ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}
```

### 3.8 Styling

- **Dark theme** by default (class `dark` on `<html>`)
- **shadcn/ui** CSS variables for consistent theming
- **Tailwind** for all styling — no custom CSS files beyond `globals.css`
- Color palette from prototype.jsx adapted to dark mode:
  - Background: zinc-950
  - Surface: zinc-900
  - Border: zinc-800
  - Primary: blue-600
  - Success: green-600
  - Accent: violet-600
- **Responsive**: mobile-friendly with collapsible sidebar

---

## 4. Dependencies

### Backend (additions to existing pyproject.toml)

```toml
# Add to [project] dependencies:
"sse-starlette",                # SSE streaming for chat endpoint
"numpy",                        # Embedding array operations (may already be present via openai SDK)
```

### Frontend (package.json)

```json
{
  "dependencies": {
    "next": "^14.0.0",
    "react": "^18.0.0",
    "react-dom": "^18.0.0",
    "typescript": "^5.0.0",
    "tailwindcss": "^3.4.0",
    "zustand": "^5.0.0",
    "eventsource-parser": "^3.0.0",
    "react-markdown": "^9.0.0",
    "remark-gfm": "^4.0.0"
  },
  "devDependencies": {
    "@types/react": "^18.0.0",
    "@types/react-dom": "^18.0.0",
    "@types/node": "^20.0.0",
    "vitest": "^2.0.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/jest-dom": "^6.0.0",
    "jsdom": "^25.0.0"
  }
}
```

---

## 5. Testing Strategy

### Backend Tests

| Module | Type | What | Mock Strategy |
|--------|------|------|--------------|
| AgentTool base | Unit | `to_tool_definition()` output matches ToolDefinition schema | None needed |
| KnowledgeSearchTool | Unit | `.execute()` returns formatted results | Mock RAGService.search() |
| ProfileReadTool | Unit | `.execute()` returns profile JSON | Mock DB with test user |
| ProgressTrackTool | Unit | `.execute(action='record')` creates LearningRecord; `action='query'` returns history | Test DB |
| MentorAgent.process() | Unit | Full loop: text-only response; single tool call + continue; max loops safety | Mock LLMProvider (return canned StreamChunks) |
| MentorAgent profile update | Unit | `_update_profile_async()` calls LLM and updates DB | Mock LLM, test DB |
| System prompt builder | Unit | Output contains profile data, teaching principles, correct personality | None |
| RAGService.search() | Integration | Query returns relevant chunks ordered by similarity | Test DB with inserted chunks + embeddings |
| POST /api/chat | Integration | SSE events: text_delta, message_end; conversation created; messages saved | Mock LLMProvider |
| GET /api/conversations | Integration | Returns user's conversations | Test DB |
| GET /api/conversations/{id}/messages | Integration | Returns ordered messages; 404 for wrong user | Test DB |
| GET /api/courses | Integration | Returns user's courses | Test DB |
| GET /api/courses/{id} | Integration | Returns course with sections and sources | Test DB |

### Frontend Tests

| Component | Type | What |
|-----------|------|------|
| MessageBubble | Unit | Renders user/assistant messages; markdown rendering; streaming cursor |
| ChatInput | Unit | Sends on Enter; disabled during streaming |
| ChatPanel | Integration | Full flow: type → send → SSE mock → messages appear |
| BilibiliPlayer | Unit | Renders iframe with correct bvid URL |
| CourseCard | Unit | Renders course info; links to correct route |
| API client | Unit | Correct URL construction; error handling |
| SSE helper | Unit | Parses mock SSE stream; calls correct callbacks |

### Test Infrastructure

**Backend:**
- Reuse `conftest.py` from Sub-project A (test DB, test client, mock LLM providers)
- Add `mock_llm_stream` fixture that yields canned `StreamChunk` sequences
- Test SSE by consuming the response as text and parsing events manually

**Frontend:**
- Vitest + @testing-library/react + jsdom
- Mock `fetch` for API calls
- Mock SSE responses with ReadableStream

---

## 6. Implementation Plan

### Phase C1: MentorAgent Core + Tools + System Prompt

**Files to create:**

| File | Description |
|------|-------------|
| `backend/app/agent/__init__.py` | Empty |
| `backend/app/agent/mentor.py` | MentorAgent class (see Section 2.1) |
| `backend/app/agent/tools/__init__.py` | Empty |
| `backend/app/agent/tools/base.py` | AgentTool ABC (see Section 2.1) |
| `backend/app/agent/tools/knowledge.py` | KnowledgeSearchTool (see Section 2.2.1) |
| `backend/app/agent/tools/profile.py` | ProfileReadTool (see Section 2.2.2) |
| `backend/app/agent/tools/progress.py` | ProgressTrackTool (see Section 2.2.3) |
| `backend/app/agent/prompts/__init__.py` | Empty |
| `backend/app/agent/prompts/mentor.py` | `build_system_prompt()` (see Section 2.3) |
| `backend/app/services/profile.py` | StudentProfile model + DB ops (see Section 2.4) |

**Files to modify:**

| File | Change |
|------|--------|
| `backend/pyproject.toml` | Add `sse-starlette` to dependencies |

**Verification:**
```bash
cd backend
python -c "from app.agent.mentor import MentorAgent; print('OK')"
python -c "from app.agent.tools.knowledge import KnowledgeSearchTool; print('OK')"
python -c "from app.services.profile import StudentProfile, load_profile; print('OK')"
pytest tests/agent/ -v  # (after writing tests)
```

### Phase C2: Chat API (SSE) + RAG

**Files to create:**

| File | Description |
|------|-------------|
| `backend/app/services/rag.py` | RAGService with pgvector search (see Section 2.5) |
| `backend/app/api/routes/chat.py` | Chat SSE endpoint + conversation CRUD (see Section 2.6) |
| `backend/app/api/routes/courses.py` | Course/section read endpoints (see Section 2.6) |
| `backend/app/models/chat.py` | Pydantic schemas (ChatRequest, ConversationResponse, MessageResponse) |

**Files to modify:**

| File | Change |
|------|--------|
| `backend/app/main.py` | Add `app.include_router(chat.router)` and `app.include_router(courses.router)` |

**Verification:**
```bash
# Start backend
uvicorn app.main:app --reload

# Test chat SSE (requires DB + configured model)
curl -N -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, mentor!"}'
# Should see SSE events streaming

# Test conversations
curl http://localhost:8000/api/conversations

# Test courses
curl http://localhost:8000/api/courses
```

### Phase C3: Frontend Skeleton (Next.js + Routing + Tailwind + shadcn)

**Setup commands:**
```bash
cd socratiq/
npx create-next-app@latest frontend --typescript --tailwind --eslint --app --src-dir=false --import-alias="@/*" --use-npm
cd frontend/
npm install zustand eventsource-parser react-markdown remark-gfm
npx shadcn@latest init
npx shadcn@latest add button input card dialog scroll-area badge tabs separator skeleton avatar dropdown-menu sheet textarea toast
```

**Files to create:**

| File | Description |
|------|-------------|
| `frontend/app/layout.tsx` | Root layout with dark theme, Inter font (see Section 3.2) |
| `frontend/app/globals.css` | Tailwind + shadcn CSS variables (dark palette) |
| `frontend/lib/api.ts` | Backend API client (see Section 3.3) |
| `frontend/lib/sse.ts` | SSE streaming helper (see Section 3.4) |
| `frontend/lib/stores/chat-store.ts` | Zustand chat state (see Section 3.5) |
| `frontend/lib/stores/course-store.ts` | Zustand course state (see Section 3.5) |
| `frontend/components/layout/sidebar.tsx` | App sidebar navigation (see Section 3.7.4) |
| `frontend/components/layout/header.tsx` | Top header bar |
| `frontend/app/page.tsx` | Dashboard page (see Section 3.6.1) |

**Verification:**
```bash
cd frontend
npm run build  # Must succeed with no errors
npm run dev    # Open http://localhost:3000 — sidebar + dashboard visible
```

### Phase C4: Import Page + Course Pages

**Files to create:**

| File | Description |
|------|-------------|
| `frontend/app/import/page.tsx` | Import page with URL/PDF tabs (see Section 3.6.2) |
| `frontend/components/import/import-form.tsx` | Import form component |
| `frontend/app/courses/[id]/page.tsx` | Course detail page (see Section 3.6.3) |
| `frontend/components/course/course-card.tsx` | Course card component |
| `frontend/components/course/section-list.tsx` | Section list component |

**Verification:**
```bash
npm run build  # Must succeed
# Navigate to /import — form renders
# Navigate to /courses/[id] — course detail renders (needs backend data)
```

### Phase C5: Learning Page with Mentor Chat + Video Player

**Files to create:**

| File | Description |
|------|-------------|
| `frontend/app/learn/[sectionId]/page.tsx` | Learning page — two-panel layout (see Section 3.6.4) |
| `frontend/components/mentor-chat/chat-panel.tsx` | Chat container with SSE (see Section 3.7.1) |
| `frontend/components/mentor-chat/message-bubble.tsx` | Message rendering with markdown (see Section 3.7.2) |
| `frontend/components/mentor-chat/chat-input.tsx` | Message input + send button |
| `frontend/components/mentor-chat/streaming-text.tsx` | Streaming text display with cursor |
| `frontend/components/video-player/bilibili-player.tsx` | Bilibili embed (see Section 3.7.3) |
| `frontend/components/pdf-viewer/pdf-viewer.tsx` | PDF iframe viewer |

**Verification:**
```bash
npm run build  # Must succeed
# Navigate to /learn/[sectionId] — two-panel layout renders
# Type a message in chat — SSE stream connects to backend
# Bilibili video renders in left panel (if section has bilibili source)
```

### Phase C6: Settings Page + Integration Testing

**Files to create:**

| File | Description |
|------|-------------|
| `frontend/app/settings/page.tsx` | Settings page with model config UI (see Section 3.6.5) |

**Backend test files to create:**

| File | Description |
|------|-------------|
| `backend/tests/agent/__init__.py` | Empty |
| `backend/tests/agent/test_mentor.py` | MentorAgent unit tests |
| `backend/tests/agent/test_tools.py` | Agent tools unit tests |
| `backend/tests/agent/test_prompts.py` | System prompt tests |
| `backend/tests/services/test_rag.py` | RAG service integration tests |
| `backend/tests/services/test_profile.py` | Profile service tests |
| `backend/tests/api/test_chat.py` | Chat API integration tests (SSE) |
| `backend/tests/api/test_courses.py` | Course API integration tests |

**Frontend test files to create:**

| File | Description |
|------|-------------|
| `frontend/vitest.config.ts` | Vitest configuration |
| `frontend/__tests__/components/message-bubble.test.tsx` | MessageBubble tests |
| `frontend/__tests__/components/chat-input.test.tsx` | ChatInput tests |
| `frontend/__tests__/lib/sse.test.ts` | SSE helper tests |
| `frontend/__tests__/lib/api.test.ts` | API client tests |

**Verification:**
```bash
# Backend
cd backend && pytest tests/ -v

# Frontend
cd frontend && npm test

# Full integration: start backend + frontend
# Import a Bilibili video (Sub-project B must be done)
# Open course → navigate to section → chat with mentor
# Verify: streaming works, tool calls happen, profile updates
```

---

## 7. API Summary

All endpoints created or consumed in Sub-project C:

| Method | Path | Created in | Description |
|--------|------|-----------|-------------|
| POST | `/api/chat` | C (chat.py) | Send message, receive SSE stream |
| GET | `/api/conversations` | C (chat.py) | List user conversations |
| GET | `/api/conversations/{id}/messages` | C (chat.py) | Get conversation messages |
| GET | `/api/courses` | C (courses.py) | List user courses |
| GET | `/api/courses/{id}` | C (courses.py) | Get course with sections |
| POST | `/api/sources/import` | B (consumed by frontend) | Import URL content |
| GET | `/api/tasks/{id}/status` | A (consumed by frontend) | Poll task status |
| GET | `/api/models` | A (consumed by settings page) | List model configs |
| PUT | `/api/model-routes` | A (consumed by settings page) | Update model routing |
| POST | `/api/models/{name}/test` | A (consumed by settings page) | Test model connectivity |

---

## 8. Cross-Cutting Concerns

### Error Handling

- **Backend**: All LLM errors (`LLMError` hierarchy) caught in MentorAgent and streamed as SSE `error` events. FastAPI exception handlers for 4xx/5xx.
- **Frontend**: SSE `error` event triggers toast notification. API errors shown inline.

### Security (MVP)

- No auth — single user assumed. `X-User-Id` header for multi-user testing.
- CORS allows `localhost:3000` only.
- All API keys encrypted in DB (Sub-project A infrastructure).

### Performance

- Working memory limited to 20 messages (prevents token overflow).
- RAG returns top-5 results by default (configurable).
- LLM provider cache in ModelRouter (5-min TTL) prevents per-request DB lookups.
- Frontend: `react-markdown` is heavy — lazy-load or memoize for large conversations.

### Observability

- Python `logging` module for all backend components.
- Log all LLM calls (model, token usage, latency) at INFO level.
- Log tool executions (name, params, duration) at INFO level.
- Log profile updates at DEBUG level.
