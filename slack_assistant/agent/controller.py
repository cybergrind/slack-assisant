"""Agent controller for orchestrating conversations."""

import logging
from dataclasses import dataclass
from typing import Any

from slack_assistant.agent.conversation import ConversationManager
from slack_assistant.agent.llm import BaseLLMClient, get_llm_client
from slack_assistant.agent.llm.models import ToolCall
from slack_assistant.agent.prompts import INITIAL_STATUS_PROMPT, build_system_prompt
from slack_assistant.agent.tools import (
    ContextTool,
    PreferencesTool,
    SearchTool,
    StatusTool,
    ThreadTool,
    ToolRegistry,
)
from slack_assistant.db.repository import Repository
from slack_assistant.preferences import PreferenceStorage
from slack_assistant.services.embeddings import EmbeddingService
from slack_assistant.slack.client import SlackClient


logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """Response from the agent."""

    text: str | None
    tool_calls_made: int = 0
    tokens_used: int = 0


class AgentController:
    """Orchestrates conversations between user and LLM with tool use."""

    def __init__(
        self,
        client: SlackClient,
        repository: Repository,
        llm_client: BaseLLMClient | None = None,
        preference_storage: PreferenceStorage | None = None,
        embedding_service: EmbeddingService | None = None,
    ):
        """Initialize the agent controller.

        Args:
            client: Slack client for API calls.
            repository: Database repository.
            llm_client: LLM client (defaults to config-based).
            preference_storage: Preference storage (defaults to file-based).
            embedding_service: Embedding service for vector search.
        """
        self._client = client
        self._repository = repository
        self._llm = llm_client or get_llm_client()
        self._prefs_storage = preference_storage or PreferenceStorage()
        self._embedding_service = embedding_service

        # Initialize conversation
        self._conversation = ConversationManager()

        # Initialize tool registry
        self._tools = ToolRegistry()
        self._setup_tools()

    def _setup_tools(self) -> None:
        """Register all available tools."""
        # Status tool
        self._tools.register(StatusTool(self._client, self._repository))

        # Search tool
        self._tools.register(SearchTool(self._client, self._repository, self._embedding_service))

        # Thread tool
        self._tools.register(ThreadTool(self._client, self._repository))

        # Context tool
        self._tools.register(ContextTool(self._client, self._repository, self._embedding_service))

        # Preferences tool
        self._tools.register(PreferencesTool(self._prefs_storage))

    def _build_system_prompt(self) -> str:
        """Build system prompt with current preferences."""
        prefs = self._prefs_storage.load()

        user_context = f'User ID: {self._client.user_id}' if self._client.user_id else ''

        return build_system_prompt(
            user_context=user_context,
            custom_rules=prefs.get_rules_text(),
            remembered_facts=prefs.get_facts_text(),
        )

    async def initialize(self) -> AgentResponse:
        """Initialize agent and get initial status.

        Returns:
            Initial greeting with status summary.
        """
        # Clear any existing conversation
        self._conversation.clear()

        # Send initial status prompt
        return await self.process_message(INITIAL_STATUS_PROMPT)

    async def process_message(self, user_input: str) -> AgentResponse:
        """Process a user message and return response.

        Args:
            user_input: User's message text.

        Returns:
            Agent response with text and metadata.
        """
        # Add user message to history
        self._conversation.add_user_message(user_input)

        # Get system prompt
        system_prompt = self._build_system_prompt()

        # Get tool definitions
        tool_definitions = self._tools.get_tool_definitions()

        total_tool_calls = 0
        total_tokens = 0

        # Conversation loop with tool use
        max_iterations = 10
        for _ in range(max_iterations):
            # Call LLM
            response = await self._llm.complete(
                messages=self._conversation.build_messages(),
                system=system_prompt,
                tools=tool_definitions,
            )

            # Track tokens
            if response.usage:
                total_tokens += response.usage.get('input_tokens', 0)
                total_tokens += response.usage.get('output_tokens', 0)

            # Add assistant response to history
            tool_call_dicts = None
            if response.tool_calls:
                tool_call_dicts = [{'id': tc.id, 'name': tc.name, 'input': tc.input} for tc in response.tool_calls]
            self._conversation.add_assistant_message(response.text, tool_call_dicts)

            # If no tool calls, we're done
            if not response.has_tool_calls:
                return AgentResponse(
                    text=response.text,
                    tool_calls_made=total_tool_calls,
                    tokens_used=total_tokens,
                )

            # Execute tools
            for tool_call in response.tool_calls:
                total_tool_calls += 1
                result, is_error = await self._execute_tool(tool_call)
                self._conversation.add_tool_result(tool_call.id, result, is_error)

        # Max iterations reached
        logger.warning('Max iterations reached in conversation loop')
        return AgentResponse(
            text=response.text or 'I apologize, but I encountered an issue processing your request.',
            tool_calls_made=total_tool_calls,
            tokens_used=total_tokens,
        )

    async def _execute_tool(self, tool_call: ToolCall) -> tuple[Any, bool]:
        """Execute a tool call.

        Args:
            tool_call: Tool call to execute.

        Returns:
            Tuple of (result, is_error).
        """
        try:
            result = await self._tools.execute(tool_call.name, **tool_call.input)
            return result, False
        except Exception as e:
            logger.exception(f'Tool execution failed: {tool_call.name}')
            return f'Error executing tool: {e!s}', True

    def clear_conversation(self) -> None:
        """Clear the conversation history."""
        self._conversation.clear()

    def get_conversation_summary(self) -> str:
        """Get a summary of the current conversation.

        Returns:
            Summary string.
        """
        return self._conversation.get_summary()
