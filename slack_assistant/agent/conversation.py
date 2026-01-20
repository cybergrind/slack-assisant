"""Conversation history management for the agent."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any


logger = logging.getLogger(__name__)


@dataclass
class ConversationManager:
    """Manages conversation history for LLM interactions."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    max_messages: int = 100

    def add_user_message(self, content: str) -> None:
        """Add a user message to the conversation.

        Args:
            content: The user's message text.
        """
        self.messages.append({'role': 'user', 'content': content})
        self._trim_if_needed()

    def add_assistant_message(self, content: str | None = None, tool_calls: list[dict[str, Any]] | None = None) -> None:
        """Add an assistant message to the conversation.

        Args:
            content: The assistant's text response.
            tool_calls: Tool calls made by the assistant.
        """
        message: dict[str, Any] = {'role': 'assistant'}

        # Build content blocks for Anthropic format
        content_blocks: list[dict[str, Any]] = []

        if content:
            content_blocks.append({'type': 'text', 'text': content})

        if tool_calls:
            for tc in tool_calls:
                content_blocks.append(
                    {
                        'type': 'tool_use',
                        'id': tc['id'],
                        'name': tc['name'],
                        'input': tc['input'],
                    }
                )

        if content_blocks:
            message['content'] = content_blocks
        else:
            message['content'] = []

        self.messages.append(message)
        self._trim_if_needed()

    def add_tool_result(self, tool_use_id: str, result: Any, is_error: bool = False) -> None:
        """Add a tool result to the conversation.

        Args:
            tool_use_id: ID of the tool call being responded to.
            result: The result from tool execution.
            is_error: Whether the result is an error.
        """
        content = result if isinstance(result, str) else json.dumps(result, default=str, indent=2)

        self.messages.append(
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'tool_result',
                        'tool_use_id': tool_use_id,
                        'content': content,
                        'is_error': is_error,
                    }
                ],
            }
        )
        self._trim_if_needed()

    def build_messages(self) -> list[dict[str, Any]]:
        """Build messages list for LLM API call.

        Returns:
            List of messages in format suitable for LLM API.
        """
        return list(self.messages)

    def clear(self) -> None:
        """Clear conversation history."""
        self.messages.clear()

    def _trim_if_needed(self) -> None:
        """Trim old messages if we exceed max_messages."""
        if len(self.messages) > self.max_messages:
            # Keep the most recent messages
            excess = len(self.messages) - self.max_messages
            self.messages = self.messages[excess:]
            logger.debug(f'Trimmed {excess} old messages from conversation')

    def get_summary(self) -> str:
        """Get a brief summary of the conversation.

        Returns:
            Summary string.
        """
        user_count = sum(1 for m in self.messages if m.get('role') == 'user')
        assistant_count = sum(1 for m in self.messages if m.get('role') == 'assistant')
        return f'{len(self.messages)} messages ({user_count} user, {assistant_count} assistant)'
