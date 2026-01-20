"""Anthropic Claude LLM client."""

import json
import logging
from typing import Any

from anthropic import AsyncAnthropic

from slack_assistant.agent.llm.base import BaseLLMClient
from slack_assistant.agent.llm.models import LLMResponse, ToolCall
from slack_assistant.config import get_config


logger = logging.getLogger(__name__)


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude API client."""

    def __init__(self):
        config = get_config()
        self.client = AsyncAnthropic(api_key=config.anthropic_api_key)
        self.model = config.llm_model

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send a completion request to Claude.

        Args:
            messages: Conversation history.
            system: System prompt.
            tools: Tool definitions.
            max_tokens: Maximum tokens in response.

        Returns:
            LLMResponse with text, tool calls, and metadata.
        """
        # Build request kwargs
        kwargs: dict[str, Any] = {
            'model': self.model,
            'max_tokens': max_tokens,
            'messages': messages,
        }

        if system:
            kwargs['system'] = system

        if tools:
            kwargs['tools'] = self._format_tools(tools)

        logger.debug(f'Sending request to Anthropic: {len(messages)} messages')

        response = await self.client.messages.create(**kwargs)

        return self._parse_response(response)

    def format_tool_result(self, tool_use_id: str, result: Any, is_error: bool = False) -> dict[str, Any]:
        """Format a tool result for Anthropic's API.

        Args:
            tool_use_id: ID of the tool call.
            result: The result from tool execution.
            is_error: Whether the result is an error.

        Returns:
            Anthropic-formatted tool result message.
        """
        content = result if isinstance(result, str) else json.dumps(result, default=str)

        return {
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

    def _format_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Format tools for Anthropic's API.

        Args:
            tools: Provider-agnostic tool definitions.

        Returns:
            Anthropic-formatted tool definitions.
        """
        anthropic_tools = []
        for tool in tools:
            anthropic_tools.append(
                {
                    'name': tool['name'],
                    'description': tool['description'],
                    'input_schema': tool['input_schema'],
                }
            )
        return anthropic_tools

    def _parse_response(self, response) -> LLMResponse:
        """Parse Anthropic response into common format.

        Args:
            response: Raw Anthropic response.

        Returns:
            Unified LLMResponse.
        """
        text_parts = []
        tool_calls = []

        for block in response.content:
            if block.type == 'text':
                text_parts.append(block.text)
            elif block.type == 'tool_use':
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        input=block.input,
                    )
                )

        return LLMResponse(
            text='\n'.join(text_parts) if text_parts else None,
            tool_calls=tool_calls if tool_calls else None,
            stop_reason=response.stop_reason,
            usage={
                'input_tokens': response.usage.input_tokens,
                'output_tokens': response.usage.output_tokens,
            },
            raw_response=response,
        )
