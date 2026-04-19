"""MentorAgent — the core agent loop for adaptive tutoring."""

import json
import logging
import re
import uuid
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import AgentTool
from app.agent.prompts.mentor import build_system_prompt
from app.services.llm.base import (
    ContentBlock,
    LLMProvider,
    StreamChunk,
    ToolDefinition,
    UnifiedMessage,
)
from app.services.llm.router import ModelRouter, TaskType
from app.services.profile import StudentProfile, load_profile

logger = logging.getLogger(__name__)


class MentorAgent:
    """Core agent loop: stream LLM → detect tool_use → execute → loop.

    The MentorAgent yields StreamChunks in real-time for SSE streaming.
    When the LLM requests a tool call, the agent executes the tool,
    feeds the result back, and continues the loop.
    """

    MAX_TOOL_LOOPS = 10  # Safety limit to prevent infinite tool loops

    def __init__(
        self,
        model_router: ModelRouter,
        db: AsyncSession,
        user_id: uuid.UUID,
        tools: list[AgentTool],
    ):
        self._router = model_router
        self._db = db
        self._user_id = user_id
        self._tools = {t.name: t for t in tools}
        self._tool_definitions = [t.to_tool_definition() for t in tools]

    async def process(
        self,
        user_message: str,
        conversation_history: list[UnifiedMessage],
        course_id: uuid.UUID | None = None,
        system_prompt_extra: str = "",
    ) -> AsyncIterator[StreamChunk]:
        """Process a user message and yield streaming response chunks.

        Args:
            user_message: The user's input message.
            conversation_history: Previous messages in the conversation.
            course_id: Optional course context for RAG filtering.

        Yields:
            StreamChunk objects for SSE streaming to the frontend.
        """
        self._collected_citations: list[dict] = []

        # Load student profile for system prompt
        profile = await load_profile(self._db, self._user_id)

        # Build system prompt with profile injection
        system_prompt = build_system_prompt(
            profile=profile,
            course_id=course_id,
            tools=list(self._tools.values()),
        )
        if system_prompt_extra:
            system_prompt += system_prompt_extra

        # Build messages
        messages = [
            UnifiedMessage(role="system", content=system_prompt),
            *conversation_history,
            UnifiedMessage(role="user", content=user_message),
        ]

        # Get LLM provider
        provider = await self._router.get_provider(TaskType.MENTOR_CHAT)

        # Agent loop
        loop_count = 0
        full_assistant_text = ""

        while loop_count < self.MAX_TOOL_LOOPS:
            loop_count += 1

            # Accumulate streaming response
            current_text = ""
            tool_calls: list[dict] = []
            current_tool_input_json = ""
            current_tool_name = ""
            current_tool_id = ""

            async for chunk in provider.chat_stream(
                messages,
                tools=self._tool_definitions if self._tools else None,
                max_tokens=4096,
                temperature=0.7,
            ):
                if chunk.type == "text_delta":
                    current_text += chunk.text or ""
                    full_assistant_text += chunk.text or ""
                    yield chunk  # Stream text to client immediately

                elif chunk.type == "tool_use_start":
                    current_tool_name = chunk.tool_name or ""
                    current_tool_id = chunk.tool_use_id or ""
                    current_tool_input_json = ""

                elif chunk.type == "tool_use_delta":
                    current_tool_input_json += chunk.tool_input_delta or ""

                elif chunk.type == "tool_use_end":
                    # Parse tool input
                    try:
                        tool_input = json.loads(current_tool_input_json) if current_tool_input_json else {}
                    except json.JSONDecodeError:
                        tool_input = {}

                    tool_calls.append({
                        "id": current_tool_id,
                        "name": current_tool_name,
                        "input": tool_input,
                    })

                elif chunk.type == "message_end":
                    yield chunk

            # If no tool calls, we're done
            if not tool_calls:
                break

            # Execute tool calls and build tool_result messages
            # First, add assistant response with tool_use blocks
            content_blocks: list[ContentBlock] = []
            if current_text:
                content_blocks.append(ContentBlock(type="text", text=current_text))
            for tc in tool_calls:
                content_blocks.append(ContentBlock(
                    type="tool_use",
                    tool_use_id=tc["id"],
                    tool_name=tc["name"],
                    tool_input=tc["input"],
                ))

            messages.append(UnifiedMessage(
                role="assistant",
                content=content_blocks,
            ))

            # Execute each tool and add results
            for tc in tool_calls:
                tool_result = await self._execute_tool(tc["name"], tc["input"])
                tool_result = self._extract_citations(tool_result)
                messages.append(UnifiedMessage(
                    role="tool_result",
                    content=[ContentBlock(
                        type="tool_result",
                        tool_use_id=tc["id"],
                        tool_result_content=tool_result,
                    )],
                ))

        # Async profile update (don't block the response)
        if full_assistant_text:
            import asyncio
            asyncio.create_task(self._maybe_update_profile(full_assistant_text, user_message))

    _CITATION_RE = re.compile(r"<!-- CITATIONS:(.*?)-->", re.DOTALL)

    def _extract_citations(self, tool_result: str) -> str:
        """Extract citation markers from a tool result and collect them.

        Returns the tool result with citation markers stripped.
        """
        for match in self._CITATION_RE.finditer(tool_result):
            try:
                citations = json.loads(match.group(1))
                if isinstance(citations, list):
                    self._collected_citations.extend(citations)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Failed to parse citation JSON from tool result")
        return self._CITATION_RE.sub("", tool_result)

    async def _execute_tool(self, tool_name: str, params: dict) -> str:
        """Execute a tool and return its result string."""
        tool = self._tools.get(tool_name)
        if not tool:
            return f"Error: Unknown tool '{tool_name}'"

        try:
            result = await tool.execute(**params)
            return result
        except Exception as e:
            logger.error(f"Tool '{tool_name}' execution error: {e}", exc_info=True)
            return f"Error executing tool '{tool_name}': {str(e)}"

    async def _maybe_update_profile(self, assistant_text: str, user_message: str) -> None:
        """Asynchronously update student profile based on conversation.

        Uses its own database session since the request session may be closed.
        """
        from app.db.database import async_session_factory
        from app.services.profile import load_profile, apply_profile_updates

        try:
            async with async_session_factory() as db:
                # Load current profile for context
                profile = await load_profile(db, self._user_id)

                provider = await self._router.get_provider(TaskType.CONTENT_ANALYSIS)
                messages = [
                    UnifiedMessage(
                        role="system",
                        content=(
                            "You are a student profile analysis engine. Based on the following "
                            "conversation between a mentor and student, identify any updates "
                            "to the student profile. Respond with JSON:\n"
                            '{"observations": ["..."], "updates": {"field": "value"}}\n'
                            "If no updates are needed, return empty updates."
                        ),
                    ),
                    UnifiedMessage(
                        role="user",
                        content=(
                            f"Current student profile:\n{profile.model_dump_json(indent=2)}\n\n"
                            f"Student's message:\n{user_message[:1000]}\n\n"
                            f"Mentor's response:\n{assistant_text[:2000]}"
                        ),
                    ),
                ]
                response = await provider.chat(messages, max_tokens=512, temperature=0.3)
                response_text = "".join(
                    b.text or "" for b in response.content if b.type == "text"
                )
                await apply_profile_updates(db, self._user_id, response_text)
                await db.commit()
        except Exception as e:
            logger.warning(f"Profile update failed (non-critical): {e}")
