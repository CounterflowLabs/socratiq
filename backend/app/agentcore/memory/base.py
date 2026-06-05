"""Memory — context assembly for an agent run.

This is the seam where Socratiq's 5-layer memory system (working / profile /
episodic / content / progress) eventually plugs in. For now agentcore ships a
``PassthroughMemory`` (no transform) plus a ``ContextWindowManager`` built on the
existing ``token_budget`` helpers, and a ``Summarizer`` protocol whose default is
a no-op. Real compaction/summarization is deferred (interface present, behavior
later) per the approved plan.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.services.llm.base import UnifiedMessage
from app.services.llm.token_budget import count_tokens

__all__ = [
    "Memory",
    "PassthroughMemory",
    "Summarizer",
    "NoopSummarizer",
    "ContextWindowManager",
]


@runtime_checkable
class Memory(Protocol):
    async def prepare(
        self, messages: list[UnifiedMessage], *, max_input_tokens: int | None = None
    ) -> list[UnifiedMessage]:
        """Return the messages to actually send to the model this turn."""
        ...


class PassthroughMemory:
    """Default: send messages unchanged."""

    async def prepare(
        self, messages: list[UnifiedMessage], *, max_input_tokens: int | None = None
    ) -> list[UnifiedMessage]:  # noqa: ARG002
        return messages


@runtime_checkable
class Summarizer(Protocol):
    async def summarize(self, messages: list[UnifiedMessage]) -> UnifiedMessage | None:
        """Compress a span of messages into a single summary message (or None)."""
        ...


class NoopSummarizer:
    """Default: no summarization (compaction deferred)."""

    async def summarize(self, messages: list[UnifiedMessage]) -> UnifiedMessage | None:  # noqa: ARG002
        return None


class ContextWindowManager:
    """Token-budget helper over the existing ``token_budget`` utilities."""

    @staticmethod
    def _text_of(msg: UnifiedMessage) -> str:
        if isinstance(msg.content, str):
            return msg.content
        return "".join(
            b.text or b.tool_result_content or "" for b in msg.content
        )

    def total_tokens(self, messages: list[UnifiedMessage]) -> int:
        return sum(count_tokens(self._text_of(m)) for m in messages)

    def fits(self, messages: list[UnifiedMessage], budget: int) -> bool:
        return self.total_tokens(messages) <= budget

    def trim(self, messages: list[UnifiedMessage], budget: int) -> list[UnifiedMessage]:
        """Drop oldest non-system messages until under ``budget``.

        Preserves the leading system message(s) and the most recent turns —
        the simplest correct trimming. Summarization (NoopSummarizer today)
        will later replace dropped spans with a summary.
        """
        if self.fits(messages, budget):
            return messages
        system = [m for m in messages if m.role == "system"]
        rest = [m for m in messages if m.role != "system"]
        # keep peeling from the front of `rest` until it fits
        while rest and not self.fits(system + rest, budget):
            rest.pop(0)
        return system + rest
