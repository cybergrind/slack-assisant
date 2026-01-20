"""Common models for LLM responses."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A tool call requested by the LLM."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""

    text: str | None
    tool_calls: list[ToolCall] | None
    stop_reason: str
    usage: dict[str, int] | None = None
    raw_response: Any = field(default=None, repr=False)

    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return bool(self.tool_calls)
