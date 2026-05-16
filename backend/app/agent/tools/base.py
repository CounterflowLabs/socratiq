"""Base class for all agent tools."""

import json
from abc import ABC, abstractmethod


def tool_error(message: str, reason: str, suggestion: str) -> str:
    """Build a structured error payload an LLM can plan recovery from.

    All tool error returns should use this helper so the model sees a
    consistent shape: ``error`` is human-readable for the chat, ``reason``
    is a snake_case category code suitable for aggregation in eval/dashboards,
    ``suggestion`` is the next action the LLM should consider.

    Returned as a JSON string (tool results are strings on the wire) — the
    LLM parses it naturally without us needing a tool_use error flag.
    """
    return json.dumps(
        {"error": message, "reason": reason, "suggestion": suggestion},
        ensure_ascii=False,
    )


def is_tool_error(result: str) -> bool:
    """Detect whether a tool result string was built by ``tool_error``.

    Used by the agent loop to tag error vs success in trace events without
    the tool having to signal status out-of-band.
    """
    if not result.startswith("{"):
        return False
    try:
        parsed = json.loads(result)
    except (json.JSONDecodeError, ValueError):
        return False
    return isinstance(parsed, dict) and "error" in parsed and "reason" in parsed


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
