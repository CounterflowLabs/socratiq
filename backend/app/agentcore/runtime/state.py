"""AgentState + LoopConfig — the mutable working set of an agent run.

``AgentState`` is what a ``Checkpointer`` snapshots and what the loop threads
through turns. ``LoopConfig`` carries the loop's bounds (ported from the
hand-rolled MentorAgent's ``MAX_TOOL_LOOPS`` etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.llm.base import UnifiedMessage

__all__ = ["AgentState", "LoopConfig"]


@dataclass
class AgentState:
    thread_id: str
    run_id: str
    messages: list[UnifiedMessage] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)  # active step stack
    iteration: int = 0
    scratch: dict[str, Any] = field(default_factory=dict)


@dataclass
class LoopConfig:
    max_iterations: int = 10  # was MentorAgent.MAX_TOOL_LOOPS
    parallel_tools: bool = True
    stop_on_tool_error: bool = False
    max_tokens: int = 4096
    temperature: float = 0.7
    # Tool names that terminate the loop after executing (e.g. a ReAct
    # judgment node's ``finish`` tool). Empty = no early-stop tools.
    stop_tools: frozenset[str] = frozenset()
