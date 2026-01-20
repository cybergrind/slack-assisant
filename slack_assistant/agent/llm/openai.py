"""OpenAI LLM client (stub for future implementation)."""

import json
import logging
from typing import Any

from slack_assistant.agent.llm.base import BaseLLMClient
from slack_assistant.agent.llm.models import LLMResponse, ToolCall
from slack_assistant.config import get_config


logger = logging.getLogger(__name__)


class OpenAIClient(BaseLLMClient):
    """OpenAI API client.

    Note: This is a stub implementation. Install openai package and
    implement fully when needed.
    """

    def __init__(self):
        config = get_config()
        self.api_key = config.openai_api_key
        self.model = config.llm_model or 'gpt-4-turbo-preview'

        try:
            from openai import AsyncOpenAI

            self.client = AsyncOpenAI(api_key=self.api_key)
        except ImportError:
            raise ImportError('OpenAI package not installed. Run: pip install openai')

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send a completion request to OpenAI.

        Args:
            messages: Conversation history.
            system: System prompt.
            tools: Tool definitions.
            max_tokens: Maximum tokens in response.

        Returns:
            LLMResponse with text, tool calls, and metadata.
        """
        # Prepend system message if provided
        formatted_messages = []
        if system:
            formatted_messages.append({'role': 'system', 'content': system})

        for msg in messages:
            formatted_messages.append(self._format_message(msg))

        kwargs: dict[str, Any] = {
            'model': self.model,
            'max_tokens': max_tokens,
            'messages': formatted_messages,
        }

        if tools:
            kwargs['tools'] = self._format_tools(tools)
            kwargs['tool_choice'] = 'auto'

        logger.debug(f'Sending request to OpenAI: {len(formatted_messages)} messages')

        response = await self.client.chat.completions.create(**kwargs)
        return self._parse_response(response)

    def format_tool_result(self, tool_use_id: str, result: Any, is_error: bool = False) -> dict[str, Any]:
        """Format a tool result for OpenAI's API.

        Args:
            tool_use_id: ID of the tool call.
            result: The result from tool execution.
            is_error: Whether the result is an error.

        Returns:
            OpenAI-formatted tool result message.
        """
        content = result if isinstance(result, str) else json.dumps(result, default=str)

        if is_error:
            content = f'Error: {content}'

        return {
            'role': 'tool',
            'tool_call_id': tool_use_id,
            'content': content,
        }

    def _format_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Format a message for OpenAI's API.

        Args:
            msg: Provider-agnostic message.

        Returns:
            OpenAI-formatted message.
        """
        role = msg.get('role', 'user')
        content = msg.get('content', '')

        # Handle Anthropic-style content blocks
        if isinstance(content, list):
            # Convert tool_use blocks to OpenAI format
            tool_calls = []
            text_parts = []

            for block in content:
                if isinstance(block, dict):
                    if block.get('type') == 'tool_use':
                        tool_calls.append(
                            {
                                'id': block.get('id'),
                                'type': 'function',
                                'function': {
                                    'name': block.get('name'),
                                    'arguments': json.dumps(block.get('input', {})),
                                },
                            }
                        )
                    elif block.get('type') == 'text':
                        text_parts.append(block.get('text', ''))
                    elif block.get('type') == 'tool_result':
                        # This becomes a separate tool message
                        return {
                            'role': 'tool',
                            'tool_call_id': block.get('tool_use_id'),
                            'content': block.get('content', ''),
                        }

            if tool_calls:
                return {
                    'role': 'assistant',
                    'content': '\n'.join(text_parts) if text_parts else None,
                    'tool_calls': tool_calls,
                }
            else:
                content = '\n'.join(text_parts)

        return {'role': role, 'content': content}

    def _format_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Format tools for OpenAI's function calling API.

        Args:
            tools: Provider-agnostic tool definitions.

        Returns:
            OpenAI-formatted tool definitions.
        """
        openai_tools = []
        for tool in tools:
            openai_tools.append(
                {
                    'type': 'function',
                    'function': {
                        'name': tool['name'],
                        'description': tool['description'],
                        'parameters': tool['input_schema'],
                    },
                }
            )
        return openai_tools

    def _parse_response(self, response) -> LLMResponse:
        """Parse OpenAI response into common format.

        Args:
            response: Raw OpenAI response.

        Returns:
            Unified LLMResponse.
        """
        choice = response.choices[0]
        message = choice.message

        tool_calls = None
        if message.tool_calls:
            tool_calls = []
            for tc in message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        input=json.loads(tc.function.arguments),
                    )
                )

        return LLMResponse(
            text=message.content,
            tool_calls=tool_calls,
            stop_reason=choice.finish_reason,
            usage={
                'input_tokens': response.usage.prompt_tokens,
                'output_tokens': response.usage.completion_tokens,
            }
            if response.usage
            else None,
            raw_response=response,
        )
