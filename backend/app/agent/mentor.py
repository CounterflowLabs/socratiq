"""MentorAgent — adaptive tutoring agent, now a thin agentcore consumer.

The hand-rolled stream/tool loop moved into ``app.agentcore`` (AgentLoop /
AgentRunner / RouterLLMClient). MentorAgent just wires Socratiq's pieces —
system prompt, tools, citation hook, MENTOR_CHAT routing — and yields AG-UI
events. Citation extraction is a ToolExecutor hook; the async profile update
fires after the run completes (unchanged behavior, own db session).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.hooks import CitationHook
from app.agent.prompts.mentor import build_system_prompt
from app.agent.tools.base import AgentTool
from app.agentcore.events import EventType, TracerEventSink
from app.agentcore.events.types import AGUIEvent
from app.agentcore.llm.router_client import RouterLLMClient
from app.agentcore.runtime import AgentLoop, AgentRunner, LoopConfig
from app.agentcore.tools.base import AgentToolAdapter, ToolContext
from app.agentcore.tools.executor import ToolExecutor
from app.prompt_template import load_prompt
from app.services.llm.base import UnifiedMessage
from app.services.llm.router import ModelRouter, TaskType
from app.services.llm.runtime import Tracer, get_default_tracer
from app.services.profile import load_profile

logger = logging.getLogger(__name__)

_PROFILE_PROMPTS_DIR = Path(__file__).parent / "prompts"
_PROFILE_ANALYSIS_SYSTEM = load_prompt(_PROFILE_PROMPTS_DIR / "profile_analysis_system.md")
_PROFILE_ANALYSIS_USER = load_prompt(_PROFILE_PROMPTS_DIR / "profile_analysis_user.md")

MAX_TOOL_LOOPS = 10  # preserved bound, now LoopConfig.max_iterations


class MentorAgent:
    """Wires Socratiq tutoring onto the agentcore runtime; yields AG-UI events."""

    def __init__(
        self,
        model_router: ModelRouter,
        db: AsyncSession,
        user_id: uuid.UUID,
        tools: list[AgentTool],
        tracer: Tracer | None = None,
    ):
        self._router = model_router
        self._db = db
        self._user_id = user_id
        self._tools = tools
        self._tracer = tracer or get_default_tracer()

    async def process(
        self,
        user_message: str,
        conversation_history: list[UnifiedMessage],
        course_id: uuid.UUID | None = None,
        system_prompt_extra: str = "",
        conversation_id: uuid.UUID | None = None,
    ) -> AsyncIterator[AGUIEvent]:
        """Run one mentor turn, yielding AG-UI events for SSE streaming."""
        profile = await load_profile(self._db, self._user_id)
        system_prompt = build_system_prompt(
            profile=profile, course_id=course_id, tools=self._tools
        )
        if system_prompt_extra:
            system_prompt += system_prompt_extra

        messages = [
            UnifiedMessage(role="system", content=system_prompt),
            *conversation_history,
            UnifiedMessage(role="user", content=user_message),
        ]

        llm = RouterLLMClient(
            self._router, primary=TaskType.MENTOR_CHAT, tracer=self._tracer
        )
        executor = ToolExecutor(
            [AgentToolAdapter(t) for t in self._tools],
            hooks=[CitationHook()],
            parallel=False,  # tools share the request db session
        )
        loop = AgentLoop(
            llm=llm,
            tools=executor,
            tool_ctx=ToolContext(db=self._db, user_id=self._user_id),
            config=LoopConfig(max_iterations=MAX_TOOL_LOOPS, max_tokens=4096, temperature=0.7),
        )
        runner = AgentRunner(
            loop=loop,
            sinks=[TracerEventSink(self._tracer)],
            thread_id=str(conversation_id) if conversation_id else None,
        )

        assistant_text_parts: list[str] = []
        async for event in runner.run(messages):
            if event.type == EventType.TEXT_MESSAGE_CONTENT and event.delta:
                assistant_text_parts.append(event.delta)
            yield event

        full_text = "".join(assistant_text_parts)
        if full_text:
            # Fire-and-forget profile update (own db session; never blocks chat).
            asyncio.create_task(self._maybe_update_profile(full_text, user_message))

    async def _maybe_update_profile(self, assistant_text: str, user_message: str) -> None:
        """Asynchronously update the student profile based on the conversation."""
        from app.db.database import async_session_factory
        from app.services.profile import apply_profile_updates, load_profile

        try:
            async with async_session_factory() as db:
                profile = await load_profile(db, self._user_id)
                provider = await self._router.get_provider(TaskType.CONTENT_ANALYSIS)
                messages = [
                    UnifiedMessage(
                        role="system", content=_PROFILE_ANALYSIS_SYSTEM.render()
                    ),
                    UnifiedMessage(
                        role="user",
                        content=_PROFILE_ANALYSIS_USER.render(
                            profile_json=profile.model_dump_json(indent=2),
                            user_message=user_message[:1000],
                            assistant_text=assistant_text[:2000],
                        ),
                    ),
                ]
                response = await provider.chat(messages, max_tokens=512, temperature=0.3)
                response_text = "".join(
                    b.text or "" for b in response.content if b.type == "text"
                )
                await apply_profile_updates(db, self._user_id, response_text)
                await db.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Profile update failed (non-critical): {e}")
