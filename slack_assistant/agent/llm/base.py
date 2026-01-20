"""Base class for LLM clients."""

from abc import ABC, abstractmethod
from typing import Any

from slack_assistant.agent.llm.models import LLMResponse


class BaseLLMClient(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send a completion request to the LLM.

        Args:
            messages: Conversation history in provider-agnostic format.
            system: System prompt.
            tools: Tool definitions in provider-agnostic format.
            max_tokens: Maximum tokens in response.

        Returns:
            LLMResponse with text, tool calls, and metadata.
        """

    @abstractmethod
    def format_tool_result(self, tool_use_id: str, result: Any, is_error: bool = False) -> dict[str, Any]:
        """Format a tool result for this provider's API.

        Args:
            tool_use_id: ID of the tool call being responded to.
            result: The result from tool execution.
            is_error: Whether the result is an error.

        Returns:
            Provider-formatted message dict.
        """
