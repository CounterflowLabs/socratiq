"""Base class for all agent tools."""

from abc import ABC, abstractmethod


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
