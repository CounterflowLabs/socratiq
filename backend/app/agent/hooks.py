"""Agent tool hooks (after_tool_call transforms).

``CitationHook`` migrates MentorAgent's old ``_extract_citations`` into a reusable
``ToolHook``: it strips the ``<!-- CITATIONS:[...]-->`` markers that
``KnowledgeSearchTool`` embeds so the model never sees them, parses the citation
list, and attaches it to the ``ToolResult``. The ToolExecutor then emits the
citations as an AG-UI ``CUSTOM`` event for the UI.
"""

from __future__ import annotations

import json
import logging
import re

from app.agentcore.tools.base import ToolCall, ToolContext, ToolResult

logger = logging.getLogger(__name__)

__all__ = ["CitationHook"]


class CitationHook:
    _RE = re.compile(r"<!-- CITATIONS:(.*?)-->", re.DOTALL)

    async def before_tool_call(self, call: ToolCall, ctx: ToolContext) -> ToolCall:  # noqa: ARG002
        return call

    async def after_tool_call(
        self, call: ToolCall, result: ToolResult, ctx: ToolContext
    ) -> ToolResult:  # noqa: ARG002
        cleaned, citations = self.extract(result.content)
        result.content = cleaned
        if citations:
            result.citations = [*result.citations, *citations]
        return result

    @classmethod
    def extract(cls, text: str) -> tuple[str, list[dict]]:
        """Return (text-without-markers, parsed-citations)."""
        citations: list[dict] = []
        for match in cls._RE.finditer(text):
            try:
                parsed = json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.warning("Failed to parse citation JSON from tool result")
                continue
            if isinstance(parsed, list):
                citations.extend(parsed)
        return cls._RE.sub("", text), citations
