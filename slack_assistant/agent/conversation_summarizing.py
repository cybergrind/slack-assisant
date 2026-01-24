"""Conversation history management with summarization for bounded context."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from slack_assistant.agent.llm.base import BaseLLMClient


logger = logging.getLogger(__name__)


@dataclass
class SummarizingConversationManager:
    """Manages conversation history with automatic summarization to bound context.

    This conversation manager keeps context bounded by:
    1. Maintaining a rolling window of recent messages (full detail)
    2. Summarizing older messages beyond the window into a compact summary
    3. Injecting the summary at the start of messages sent to LLM

    This prevents unbounded context growth while preserving conversation continuity.
    """

    messages: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""  # Condensed summary of old messages

    # Tuning parameters
    max_recent_turns: int = 4  # Keep last N user-assistant exchanges in full detail
    max_summary_tokens: int = 1000  # Keep summary under this token estimate
    summarize_threshold: int = 6  # Summarize when conversation exceeds N turns

    def add_user_message(self, content: str) -> None:
        """Add a user message to the conversation.

        Args:
            content: The user's message text.
        """
        self.messages.append({'role': 'user', 'content': content})

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
            self.messages.append(message)
        else:
            # Anthropic API requires non-empty content for non-final assistant messages.
            # Skip adding this message if there's no content.
            logger.debug('Skipping assistant message with no content')

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

    async def maybe_summarize(self, llm_client: BaseLLMClient) -> None:
        """Trigger summarization if conversation exceeds threshold.

        Args:
            llm_client: LLM client to use for generating summaries.
        """
        turn_count = self._count_turns()

        if turn_count <= self.summarize_threshold:
            logger.debug(f'Turn count {turn_count} under threshold {self.summarize_threshold}, skipping summarization')
            return

        logger.info(f'Turn count {turn_count} exceeds threshold {self.summarize_threshold}, triggering summarization')

        try:
            # Extract messages to summarize (keep last max_recent_turns)
            messages_to_summarize = self._extract_old_messages()

            if not messages_to_summarize:
                logger.debug('No old messages to summarize')
                return

            # Generate summary via LLM
            new_summary = await self._generate_summary(llm_client, messages_to_summarize)

            # Merge with existing summary if we have one
            if self.summary:
                logger.debug('Merging with existing summary')
                self.summary = await self._merge_summaries(llm_client, self.summary, new_summary)
            else:
                self.summary = new_summary

            # Keep only recent messages
            self.messages = self._get_recent_messages()

            logger.info(f'Summarization complete. Summary length: {len(self.summary)} chars, '
                       f'kept {len(self.messages)} recent messages')

        except Exception as e:
            logger.error(f'Summarization failed: {e}')
            # Fall back to simple truncation to prevent unbounded growth
            logger.warning('Falling back to simple message truncation')
            # Keep last 20 messages as emergency fallback
            if len(self.messages) > 20:
                self.messages = self.messages[-20:]

    def build_messages(self) -> list[dict[str, Any]]:
        """Build messages list for LLM API call with summary prepended.

        Returns:
            List of messages in format suitable for LLM API.
        """
        if not self.summary:
            return list(self.messages)

        # Inject summary as first user message
        summary_message = {
            'role': 'user',
            'content': f'[Context Summary from earlier in conversation]\n{self.summary}\n[End of summary]',
        }
        return [summary_message, *list(self.messages)]

    def clear(self) -> None:
        """Clear conversation history and summary."""
        self.messages.clear()
        self.summary = ""

    def get_summary(self) -> str:
        """Get a brief summary of the conversation state.

        Returns:
            Summary string with message counts and summarization status.
        """
        user_count = sum(1 for m in self.messages if m.get('role') == 'user')
        assistant_count = sum(1 for m in self.messages if m.get('role') == 'assistant')
        turn_count = self._count_turns()

        summary_status = f', has summary ({len(self.summary)} chars)' if self.summary else ''
        return (f'{len(self.messages)} messages ({user_count} user, {assistant_count} assistant), '
                f'{turn_count} turns{summary_status}')

    def _count_turns(self) -> int:
        """Count completed user-assistant exchange turns.

        A "turn" is a user message (not tool_result) that initiates a new exchange.
        Tool results are part of the same turn as the user message that triggered the tools.

        Returns:
            Number of turns in the conversation.
        """
        count = 0
        for msg in self.messages:
            # User messages that are NOT tool results indicate a new turn
            if msg['role'] == 'user':
                content = msg.get('content', '')
                if isinstance(content, str):
                    # Text message = new turn
                    count += 1
                elif isinstance(content, list):
                    # Check if it's a tool_result
                    has_tool_result = any(
                        isinstance(c, dict) and c.get('type') == 'tool_result'
                        for c in content
                    )
                    if not has_tool_result:
                        count += 1
        return count

    def _extract_old_messages(self) -> list[dict[str, Any]]:
        """Extract messages beyond the recent window for summarization.

        Returns:
            List of old messages to be summarized.
        """
        recent_messages = self._get_recent_messages()
        # Find index where recent messages start
        if not recent_messages:
            return list(self.messages)

        # Get all messages up to (but not including) the recent window
        recent_start_idx = len(self.messages) - len(recent_messages)
        return self.messages[:recent_start_idx]

    def _get_recent_messages(self) -> list[dict[str, Any]]:
        """Get the recent message window to preserve in full detail.

        Returns:
            List of recent messages (last max_recent_turns).
        """
        # Find indices of user messages that start turns (not tool results)
        turn_indices: list[int] = []
        for idx, msg in enumerate(self.messages):
            if msg['role'] == 'user':
                content = msg.get('content', '')
                if isinstance(content, str):
                    turn_indices.append(idx)
                elif isinstance(content, list):
                    has_tool_result = any(
                        isinstance(c, dict) and c.get('type') == 'tool_result'
                        for c in content
                    )
                    if not has_tool_result:
                        turn_indices.append(idx)

        if len(turn_indices) <= self.max_recent_turns:
            # All messages are within recent window
            return list(self.messages)

        # Get the start index of the recent window
        recent_start_idx = turn_indices[-self.max_recent_turns]
        return self.messages[recent_start_idx:]

    async def _generate_summary(self, llm_client: BaseLLMClient, messages: list[dict[str, Any]]) -> str:
        """Generate compact summary of messages using LLM.

        Args:
            llm_client: LLM client to use for generation.
            messages: Messages to summarize.

        Returns:
            Concise summary text.
        """
        formatted_messages = self._format_messages_for_summary(messages)
        prompt = f"""Summarize this conversation segment concisely (max 200 words):

Focus on:
- Key facts discovered (channels, users, priorities, message IDs)
- Actions taken or decisions made
- Items marked as reviewed, deferred, or acted upon
- Important context for continuing the conversation

Be extremely concise. Omit greetings and redundant information.
Preserve specific identifiers (channel names, user names, timestamps) when mentioned.

Conversation to summarize:
{formatted_messages}
"""
        response = await llm_client.complete(
            messages=[{'role': 'user', 'content': prompt}],
            system=(
                'You are a concise summarization assistant. '
                'Your summaries are factual, brief, and preserve key details.'
            ),
            max_tokens=500,  # Force brevity
        )
        return response.text or ''

    async def _merge_summaries(self, llm_client: BaseLLMClient, old_summary: str, new_summary: str) -> str:
        """Merge two summaries into one condensed summary.

        Args:
            llm_client: LLM client to use for merging.
            old_summary: Older summary text.
            new_summary: Recent summary text.

        Returns:
            Merged summary text.
        """
        prompt = f"""Merge these two summaries into ONE concise summary (max 250 words):

Summary 1 (older):
{old_summary}

Summary 2 (recent):
{new_summary}

Create a single merged summary. Prioritize recent information over older information.
Preserve key facts, channel names, user names, and important decisions.
"""

        response = await llm_client.complete(
            messages=[{'role': 'user', 'content': prompt}],
            system=(
                'You are a concise summarization assistant. '
                'Your summaries are factual, brief, and preserve key details.'
            ),
            max_tokens=600,
        )
        return response.text or ''

    def _format_messages_for_summary(self, messages: list[dict[str, Any]]) -> str:
        """Format messages into readable text for summarization.

        Args:
            messages: Messages to format.

        Returns:
            Formatted text representation.
        """
        lines = []
        for msg in messages:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')

            if isinstance(content, str):
                lines.append(f'{role.upper()}: {content[:500]}')  # Truncate long messages
            elif isinstance(content, list):
                # Handle structured content (tool_use, tool_result, etc.)
                for block in content:
                    if isinstance(block, dict):
                        block_type = block.get('type', 'unknown')
                        if block_type == 'text':
                            lines.append(f'{role.upper()}: {block.get("text", "")[:500]}')
                        elif block_type == 'tool_use':
                            tool_name = block.get('name', 'unknown')
                            lines.append(f'{role.upper()}: [called tool: {tool_name}]')
                        elif block_type == 'tool_result':
                            result_text = str(block.get('content', ''))[:300]
                            lines.append(f'{role.upper()}: [tool result: {result_text}...]')

        return '\n'.join(lines)
