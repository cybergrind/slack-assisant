"""LLM provider abstraction layer."""

from slack_assistant.agent.llm.base import BaseLLMClient
from slack_assistant.agent.llm.models import LLMResponse, ToolCall


def get_llm_client(provider: str | None = None) -> BaseLLMClient:
    """Factory to get LLM client based on config.

    Args:
        provider: LLM provider name ('anthropic', 'openai').
                  If None, uses config.llm_provider.

    Returns:
        LLM client instance.

    Raises:
        ValueError: If provider is unknown.
    """
    from slack_assistant.config import get_config

    config = get_config()
    provider = provider or config.llm_provider

    if provider == 'anthropic':
        from slack_assistant.agent.llm.anthropic import AnthropicClient

        return AnthropicClient()
    elif provider == 'openai':
        from slack_assistant.agent.llm.openai import OpenAIClient

        return OpenAIClient()
    else:
        raise ValueError(f'Unknown LLM provider: {provider}')


__all__ = [
    'BaseLLMClient',
    'LLMResponse',
    'ToolCall',
    'get_llm_client',
]
