"""Base tool class and registry."""

import logging
from abc import ABC, abstractmethod
from typing import Any


logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """Abstract base class for agent tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool identifier used by the LLM."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Description shown to the LLM."""

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for tool input parameters."""

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """Execute the tool with given parameters.

        Args:
            **kwargs: Tool-specific parameters.

        Returns:
            Tool execution result.
        """

    def to_dict(self) -> dict[str, Any]:
        """Convert tool to LLM-friendly dict format.

        Returns:
            Dict with name, description, and input_schema.
        """
        return {
            'name': self.name,
            'description': self.description,
            'input_schema': self.input_schema,
        }


class ToolRegistry:
    """Registry for managing available tools."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool.

        Args:
            tool: Tool instance to register.
        """
        self._tools[tool.name] = tool
        logger.debug(f'Registered tool: {tool.name}')

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name.

        Args:
            name: Tool name.

        Returns:
            Tool instance or None if not found.
        """
        return self._tools.get(name)

    def get_all(self) -> list[BaseTool]:
        """Get all registered tools.

        Returns:
            List of all tools.
        """
        return list(self._tools.values())

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Get tool definitions for LLM API.

        Returns:
            List of tool definitions.
        """
        return [tool.to_dict() for tool in self._tools.values()]

    async def execute(self, name: str, **kwargs: Any) -> Any:
        """Execute a tool by name.

        Args:
            name: Tool name.
            **kwargs: Tool parameters.

        Returns:
            Tool execution result.

        Raises:
            ValueError: If tool not found.
        """
        tool = self.get(name)
        if not tool:
            raise ValueError(f'Unknown tool: {name}')

        logger.debug(f'Executing tool: {name}')
        return await tool.execute(**kwargs)
