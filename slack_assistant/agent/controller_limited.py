"""Limited context agent controller with summarization."""

import logging

from slack_assistant.agent.controller import AgentController, AgentResponse
from slack_assistant.agent.conversation_summarizing import SummarizingConversationManager
from slack_assistant.agent.llm import BaseLLMClient
from slack_assistant.config import get_config
from slack_assistant.db.repository import Repository
from slack_assistant.preferences import PreferenceStorage
from slack_assistant.services.embeddings import EmbeddingService
from slack_assistant.session import SessionStorage
from slack_assistant.slack.client import SlackClient


logger = logging.getLogger(__name__)


class LimitedAgentController(AgentController):
    """Agent controller with bounded context via progressive summarization.

    This controller replaces the standard ConversationManager with a
    SummarizingConversationManager that keeps context bounded by:
    1. Maintaining a rolling window of recent messages
    2. Summarizing older messages beyond the window
    3. Injecting summaries at the start of context

    This prevents unbounded token growth while preserving conversation continuity.
    """

    def __init__(
        self,
        client: SlackClient,
        repository: Repository,
        llm_client: BaseLLMClient | None = None,
        preference_storage: PreferenceStorage | None = None,
        session_storage: SessionStorage | None = None,
        embedding_service: EmbeddingService | None = None,
    ):
        """Initialize the limited context agent controller.

        Args:
            client: Slack client for API calls.
            repository: Database repository.
            llm_client: LLM client (defaults to config-based).
            preference_storage: Preference storage (defaults to file-based).
            session_storage: Session storage (defaults to file-based).
            embedding_service: Embedding service for vector search.
        """
        # Call parent constructor
        super().__init__(
            client=client,
            repository=repository,
            llm_client=llm_client,
            preference_storage=preference_storage,
            session_storage=session_storage,
            embedding_service=embedding_service,
        )

        # Load config for summarization parameters
        config = get_config()

        # Replace conversation manager with summarizing version
        self._conversation = SummarizingConversationManager(
            max_recent_turns=config.context_max_recent_turns,
            max_summary_tokens=config.context_max_summary_tokens,
            summarize_threshold=config.context_summarize_threshold,
        )

        logger.info(
            f'Initialized LimitedAgentController with summarization: '
            f'max_recent_turns={config.context_max_recent_turns}, '
            f'summarize_threshold={config.context_summarize_threshold}, '
            f'max_summary_tokens={config.context_max_summary_tokens}'
        )

    async def process_message(self, user_input: str) -> AgentResponse:
        """Process a user message with automatic summarization.

        This overrides the parent implementation to add summarization
        after tool execution completes in each iteration.

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
        for iteration in range(max_iterations):
            # Build messages with summary (if any)
            messages = self._conversation.build_messages()

            # Call LLM
            response = await self._llm.complete(
                messages=messages,
                system=system_prompt,
                tools=tool_definitions,
            )

            # Track tokens
            if response.usage:
                input_tokens = response.usage.get('input_tokens', 0)
                output_tokens = response.usage.get('output_tokens', 0)
                total_tokens += input_tokens + output_tokens
                logger.info(f'Iteration {iteration + 1}: {input_tokens} input tokens, {output_tokens} output tokens')

            # Add assistant response to history
            tool_call_dicts = None
            if response.tool_calls:
                tool_call_dicts = [{'id': tc.id, 'name': tc.name, 'input': tc.input} for tc in response.tool_calls]
            self._conversation.add_assistant_message(response.text, tool_call_dicts)

            # If no tool calls, we're done
            if not response.has_tool_calls:
                # Trigger summarization before returning (if needed)
                await self._conversation.maybe_summarize(self._llm)

                logger.info(f'Conversation complete: {total_tool_calls} tool calls, {total_tokens} total tokens')
                logger.info(f'Conversation state: {self._conversation.get_summary()}')

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

            # Trigger summarization after tool results added (if needed)
            await self._conversation.maybe_summarize(self._llm)

        # Max iterations reached
        logger.warning('Max iterations reached in conversation loop')
        logger.info(f'Final conversation state: {self._conversation.get_summary()}')

        return AgentResponse(
            text=response.text or 'I apologize, but I encountered an issue processing your request.',
            tool_calls_made=total_tool_calls,
            tokens_used=total_tokens,
        )
