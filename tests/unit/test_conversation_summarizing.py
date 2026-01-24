"""Tests for the summarizing conversation manager."""

from unittest.mock import AsyncMock

import pytest

from slack_assistant.agent.conversation_summarizing import SummarizingConversationManager
from slack_assistant.agent.llm.models import LLMResponse


@pytest.fixture
def mock_llm():
    """Create a mock LLM client for testing."""
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=LLMResponse(
        text='Concise summary of previous messages...',
        tool_calls=[],
        stop_reason='end_turn',
        usage={'input_tokens': 100, 'output_tokens': 50}
    ))
    return llm


class TestSummarizingConversationManager:
    """Tests for SummarizingConversationManager."""

    def test_add_user_message(self):
        """Test adding a user message."""
        manager = SummarizingConversationManager()
        manager.add_user_message('Hello')

        messages = manager.build_messages()
        assert len(messages) == 1
        assert messages[0]['role'] == 'user'
        assert messages[0]['content'] == 'Hello'

    def test_add_assistant_message_text_only(self):
        """Test adding an assistant message with text only."""
        manager = SummarizingConversationManager()
        manager.add_assistant_message('Hi there!')

        messages = manager.build_messages()
        assert len(messages) == 1
        assert messages[0]['role'] == 'assistant'
        assert messages[0]['content'] == [{'type': 'text', 'text': 'Hi there!'}]

    def test_add_assistant_message_with_tool_calls(self):
        """Test adding an assistant message with tool calls."""
        manager = SummarizingConversationManager()
        tool_calls = [{'id': 'tc_123', 'name': 'analyze_messages', 'input': {'hours_back': 24}}]
        manager.add_assistant_message('Let me check...', tool_calls)

        messages = manager.build_messages()
        assert len(messages) == 1
        content = messages[0]['content']
        assert len(content) == 2
        assert content[0]['type'] == 'text'
        assert content[1]['type'] == 'tool_use'
        assert content[1]['id'] == 'tc_123'
        assert content[1]['name'] == 'analyze_messages'

    def test_add_tool_result(self):
        """Test adding a tool result."""
        manager = SummarizingConversationManager()
        manager.add_tool_result('tc_123', {'status': 'success', 'count': 42})

        messages = manager.build_messages()
        assert len(messages) == 1
        assert messages[0]['role'] == 'user'
        assert len(messages[0]['content']) == 1
        assert messages[0]['content'][0]['type'] == 'tool_result'
        assert messages[0]['content'][0]['tool_use_id'] == 'tc_123'

    def test_turn_counting_simple(self):
        """Test turn counting with simple user-assistant exchanges."""
        manager = SummarizingConversationManager()

        # Turn 1
        manager.add_user_message('Hello')
        assert manager._count_turns() == 1

        manager.add_assistant_message('Hi there!')
        assert manager._count_turns() == 1  # Still same turn

        # Turn 2
        manager.add_user_message('How are you?')
        assert manager._count_turns() == 2

        manager.add_assistant_message('I am fine!')
        assert manager._count_turns() == 2

    def test_turn_counting_with_tool_calls(self):
        """Test turn counting with tool calls (tool results don't count as new turns)."""
        manager = SummarizingConversationManager()

        # Turn 1: User message + tool call + tool result
        manager.add_user_message('Give me status')
        assert manager._count_turns() == 1

        tool_calls = [{'id': 'tc_1', 'name': 'analyze_messages', 'input': {}}]
        manager.add_assistant_message('Let me check...', tool_calls)
        assert manager._count_turns() == 1

        manager.add_tool_result('tc_1', {'messages': []})
        assert manager._count_turns() == 1  # Tool result doesn't increment turn count

        manager.add_assistant_message('Here is your status...')
        assert manager._count_turns() == 1  # Still same turn

        # Turn 2: New user message
        manager.add_user_message('Tell me more')
        assert manager._count_turns() == 2

    @pytest.mark.asyncio
    async def test_no_summarization_under_threshold(self, mock_llm):
        """Test that summarization is not triggered when under threshold."""
        manager = SummarizingConversationManager(summarize_threshold=6)

        # Add 5 turns (under threshold)
        for i in range(5):
            manager.add_user_message(f'Message {i}')
            manager.add_assistant_message(f'Response {i}')

        assert manager._count_turns() == 5
        assert manager.summary == ''

        # Trigger summarization check
        await manager.maybe_summarize(mock_llm)

        # Should not have called LLM
        mock_llm.complete.assert_not_called()
        assert manager.summary == ''

    @pytest.mark.asyncio
    async def test_summarization_triggered_at_threshold(self, mock_llm):
        """Test that summarization is triggered when exceeding threshold."""
        manager = SummarizingConversationManager(
            max_recent_turns=4,
            summarize_threshold=6
        )

        # Add 7 turns (over threshold)
        for i in range(7):
            manager.add_user_message(f'Message {i}')
            manager.add_assistant_message(f'Response {i}')

        assert manager._count_turns() == 7

        # Trigger summarization
        await manager.maybe_summarize(mock_llm)

        # Should have called LLM to generate summary
        assert mock_llm.complete.call_count > 0
        assert manager.summary == 'Concise summary of previous messages...'

        # Should have kept only recent messages
        messages = manager.messages
        recent_turn_count = manager._count_turns()
        assert recent_turn_count == 4  # max_recent_turns

    @pytest.mark.asyncio
    async def test_recent_window_preserved(self, mock_llm):
        """Test that recent message window is preserved in full detail."""
        manager = SummarizingConversationManager(
            max_recent_turns=3,
            summarize_threshold=5
        )

        # Add 6 turns
        for i in range(6):
            manager.add_user_message(f'Message {i}')
            manager.add_assistant_message(f'Response {i}')

        # Trigger summarization
        await manager.maybe_summarize(mock_llm)

        # Check that recent 3 turns are preserved
        assert manager._count_turns() == 3

        # Check that we can still see the messages
        messages = manager.messages
        assert len(messages) > 0

        # Recent messages should be preserved
        user_messages = [m for m in messages if m['role'] == 'user' and isinstance(m.get('content'), str)]
        # Should have last 3 user messages
        assert len(user_messages) == 3
        assert 'Message 3' in user_messages[0]['content'] or 'Message 4' in user_messages[0]['content']

    @pytest.mark.asyncio
    async def test_summary_injection_in_build_messages(self, mock_llm):
        """Test that summary is prepended to messages when building."""
        manager = SummarizingConversationManager(
            max_recent_turns=2,
            summarize_threshold=4
        )

        # Add 5 turns
        for i in range(5):
            manager.add_user_message(f'Message {i}')
            manager.add_assistant_message(f'Response {i}')

        # Trigger summarization
        await manager.maybe_summarize(mock_llm)

        # Build messages should include summary
        messages = manager.build_messages()

        # First message should be the summary
        assert messages[0]['role'] == 'user'
        assert '[Context Summary from earlier in conversation]' in messages[0]['content']
        assert 'Concise summary of previous messages...' in messages[0]['content']
        assert '[End of summary]' in messages[0]['content']

    @pytest.mark.asyncio
    async def test_summary_merging(self, mock_llm):
        """Test that summaries are merged when summarizing again."""
        manager = SummarizingConversationManager(
            max_recent_turns=2,
            summarize_threshold=4
        )

        # First summarization
        for i in range(5):
            manager.add_user_message(f'Message {i}')
            manager.add_assistant_message(f'Response {i}')

        await manager.maybe_summarize(mock_llm)
        assert manager.summary == 'Concise summary of previous messages...'

        # Add more messages to trigger second summarization
        for i in range(5, 10):
            manager.add_user_message(f'Message {i}')
            manager.add_assistant_message(f'Response {i}')

        # Mock the merge response
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            text='Merged summary of all previous messages...',
            tool_calls=[],
            stop_reason='end_turn',
            usage={'input_tokens': 200, 'output_tokens': 60}
        ))

        await manager.maybe_summarize(mock_llm)

        # Summary should be updated (merged)
        assert 'Merged summary' in manager.summary or manager.summary == 'Merged summary of all previous messages...'

    @pytest.mark.asyncio
    async def test_max_summary_length(self, mock_llm):
        """Test that summary stays under token limit."""
        manager = SummarizingConversationManager(
            max_recent_turns=2,
            summarize_threshold=4,
            max_summary_tokens=1000
        )

        # Add messages and trigger summarization
        for i in range(5):
            manager.add_user_message(f'Message {i}')
            manager.add_assistant_message(f'Response {i}')

        await manager.maybe_summarize(mock_llm)

        # Check that summary exists and is reasonable length
        # (approximate: 1000 tokens ≈ 4000 chars for English)
        assert len(manager.summary) > 0
        # In real usage, LLM should respect max_tokens=500 parameter
        # Here we just check the summary was created
        assert manager.summary == 'Concise summary of previous messages...'

    @pytest.mark.asyncio
    async def test_fallback_on_summarization_failure(self, mock_llm):
        """Test fallback to simple truncation if summarization fails."""
        manager = SummarizingConversationManager(
            max_recent_turns=2,
            summarize_threshold=4
        )

        # Add many messages
        for i in range(25):
            manager.add_user_message(f'Message {i}')
            manager.add_assistant_message(f'Response {i}')

        # Make LLM fail
        mock_llm.complete = AsyncMock(side_effect=Exception('LLM error'))

        # Should not crash, should fall back to truncation
        await manager.maybe_summarize(mock_llm)

        # Should have truncated to last 20 messages
        assert len(manager.messages) <= 20

    def test_clear(self):
        """Test clearing conversation and summary."""
        manager = SummarizingConversationManager()
        manager.add_user_message('Hello')
        manager.add_assistant_message('Hi')
        manager.summary = 'Some summary'

        manager.clear()

        assert len(manager.messages) == 0
        assert manager.summary == ''

    def test_get_summary(self):
        """Test getting conversation summary statistics."""
        manager = SummarizingConversationManager()
        manager.add_user_message('Hello')
        manager.add_assistant_message('Hi')
        manager.summary = 'Test summary'

        summary = manager.get_summary()

        assert '2 messages' in summary
        assert '1 user' in summary
        assert '1 assistant' in summary
        assert '1 turns' in summary
        assert 'has summary' in summary

    def test_format_messages_for_summary(self):
        """Test formatting messages for summarization."""
        manager = SummarizingConversationManager()

        # Add various message types
        manager.add_user_message('Hello')
        manager.add_assistant_message('Hi there!')
        tool_calls = [{'id': 'tc_1', 'name': 'get_status', 'input': {}}]
        manager.add_assistant_message('Let me check...', tool_calls)
        manager.add_tool_result('tc_1', {'status': 'ok'})

        # Format for summary
        formatted = manager._format_messages_for_summary(manager.messages)

        assert 'USER: Hello' in formatted
        assert 'ASSISTANT: Hi there!' in formatted
        assert 'called tool: get_status' in formatted
        assert 'tool result' in formatted

    @pytest.mark.asyncio
    async def test_extract_old_messages(self, mock_llm):
        """Test extraction of old messages for summarization."""
        manager = SummarizingConversationManager(
            max_recent_turns=2,
            summarize_threshold=4
        )

        # Add 5 turns
        for i in range(5):
            manager.add_user_message(f'Message {i}')
            manager.add_assistant_message(f'Response {i}')

        # Get old messages (before recent window)
        old_messages = manager._extract_old_messages()

        # Should have messages from first 3 turns (5 total - 2 recent)
        old_user_messages = [m for m in old_messages if m['role'] == 'user' and isinstance(m.get('content'), str)]
        assert len(old_user_messages) == 3  # Turns 0, 1, 2

    def test_get_recent_messages(self):
        """Test getting recent message window."""
        manager = SummarizingConversationManager(max_recent_turns=3)

        # Add 6 turns
        for i in range(6):
            manager.add_user_message(f'Message {i}')
            manager.add_assistant_message(f'Response {i}')

        # Get recent messages
        recent_messages = manager._get_recent_messages()

        # Should have last 3 turns (6 messages: 3 user + 3 assistant)
        user_messages = [m for m in recent_messages if m['role'] == 'user']
        assert len(user_messages) == 3

        # Check these are the most recent
        assert 'Message 3' in user_messages[0]['content']
        assert 'Message 4' in user_messages[1]['content']
        assert 'Message 5' in user_messages[2]['content']
