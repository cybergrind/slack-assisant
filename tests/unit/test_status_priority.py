"""Tests for status priority filtering - mentions where user already replied."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from slack_assistant.db.models import Channel, Message
from slack_assistant.formatting.models import Priority
from slack_assistant.services.status import StatusService


@pytest.fixture
def mock_repository():
    """Create a mock repository."""
    return MagicMock()


@pytest.fixture
def mock_slack_client():
    """Create a mock Slack client."""
    client = MagicMock()
    client.user_id = 'U_CURRENT_USER'
    client.get_message_link = MagicMock(return_value='https://slack.com/link')
    return client


@pytest.fixture
def status_service(mock_slack_client, mock_repository):
    """Create StatusService with mocked dependencies."""
    return StatusService(mock_slack_client, mock_repository)


class TestStatusMentionPriority:
    """Tests for mention priority based on user reply status."""

    @pytest.mark.asyncio
    async def test_mention_without_reply_is_critical(self, status_service, mock_repository):
        """Mentions where user hasn't replied should be CRITICAL priority."""
        # Setup: A mention message in a thread
        mention_msg = Message(
            id=1,
            channel_id='C123',
            ts='1234567890.000001',
            thread_ts='1234567890.000000',
            user_id='U_OTHER_USER',
            text='Hey <@U_CURRENT_USER> can you help?',
            created_at=datetime.now(),
        )

        mock_repository.get_unread_mentions = AsyncMock(return_value=[mention_msg])
        mock_repository.get_user_reply_status_batch = AsyncMock(
            return_value={'C123:1234567890.000000': False}  # User has NOT replied
        )
        mock_repository.get_dm_messages = AsyncMock(return_value=[])
        mock_repository.get_threads_with_replies = AsyncMock(return_value=[])
        mock_repository.get_pending_reminders = AsyncMock(return_value=[])
        mock_repository.get_users_batch = AsyncMock(return_value=[])
        mock_repository.get_channels_batch = AsyncMock(return_value=[
            Channel(id='C123', name='general', channel_type='public_channel')
        ])

        status = await status_service.get_status()

        assert len(status.items) == 1
        assert status.items[0].priority == Priority.CRITICAL
        assert status.items[0].reason == 'You were mentioned'

    @pytest.mark.asyncio
    async def test_mention_with_reply_is_low(self, status_service, mock_repository):
        """Mentions where user has already replied should be LOW priority."""
        # Setup: A mention message in a thread
        mention_msg = Message(
            id=1,
            channel_id='C123',
            ts='1234567890.000001',
            thread_ts='1234567890.000000',
            user_id='U_OTHER_USER',
            text='Hey <@U_CURRENT_USER> can you help?',
            created_at=datetime.now(),
        )

        mock_repository.get_unread_mentions = AsyncMock(return_value=[mention_msg])
        mock_repository.get_user_reply_status_batch = AsyncMock(
            return_value={'C123:1234567890.000000': True}  # User HAS replied
        )
        mock_repository.get_dm_messages = AsyncMock(return_value=[])
        mock_repository.get_threads_with_replies = AsyncMock(return_value=[])
        mock_repository.get_pending_reminders = AsyncMock(return_value=[])
        mock_repository.get_users_batch = AsyncMock(return_value=[])
        mock_repository.get_channels_batch = AsyncMock(return_value=[
            Channel(id='C123', name='general', channel_type='public_channel')
        ])

        status = await status_service.get_status()

        assert len(status.items) == 1
        assert status.items[0].priority == Priority.LOW
        assert status.items[0].reason == 'You were mentioned (already replied)'

    @pytest.mark.asyncio
    async def test_top_level_mention_uses_message_ts_as_thread(self, status_service, mock_repository):
        """Top-level mentions (no thread_ts) should use message ts as thread key."""
        # Setup: A top-level mention (not in a thread)
        mention_msg = Message(
            id=1,
            channel_id='C123',
            ts='1234567890.000001',
            thread_ts=None,  # Top-level message
            user_id='U_OTHER_USER',
            text='Hey <@U_CURRENT_USER> check this out',
            created_at=datetime.now(),
        )

        mock_repository.get_unread_mentions = AsyncMock(return_value=[mention_msg])
        mock_repository.get_user_reply_status_batch = AsyncMock(
            return_value={'C123:1234567890.000001': True}  # User replied to this thread
        )
        mock_repository.get_dm_messages = AsyncMock(return_value=[])
        mock_repository.get_threads_with_replies = AsyncMock(return_value=[])
        mock_repository.get_pending_reminders = AsyncMock(return_value=[])
        mock_repository.get_users_batch = AsyncMock(return_value=[])
        mock_repository.get_channels_batch = AsyncMock(return_value=[
            Channel(id='C123', name='general', channel_type='public_channel')
        ])

        status = await status_service.get_status()

        # Verify batch check was called with correct context
        call_args = mock_repository.get_user_reply_status_batch.call_args
        mention_contexts = call_args[0][1]  # Second positional arg
        assert ('C123', None, '1234567890.000001') in mention_contexts

        # Verify priority
        assert len(status.items) == 1
        assert status.items[0].priority == Priority.LOW

    @pytest.mark.asyncio
    async def test_multiple_mentions_mixed_replies(self, status_service, mock_repository):
        """Mix of replied and unreplied mentions should have correct priorities."""
        mention1 = Message(
            id=1,
            channel_id='C123',
            ts='1234567890.000001',
            thread_ts='1234567890.000000',
            user_id='U_USER1',
            text='<@U_CURRENT_USER> question 1',
            created_at=datetime.now(),
        )
        mention2 = Message(
            id=2,
            channel_id='C456',
            ts='1234567891.000001',
            thread_ts='1234567891.000000',
            user_id='U_USER2',
            text='<@U_CURRENT_USER> question 2',
            created_at=datetime.now(),
        )

        mock_repository.get_unread_mentions = AsyncMock(return_value=[mention1, mention2])
        mock_repository.get_user_reply_status_batch = AsyncMock(
            return_value={
                'C123:1234567890.000000': True,   # Replied to first
                'C456:1234567891.000000': False,  # Not replied to second
            }
        )
        mock_repository.get_dm_messages = AsyncMock(return_value=[])
        mock_repository.get_threads_with_replies = AsyncMock(return_value=[])
        mock_repository.get_pending_reminders = AsyncMock(return_value=[])
        mock_repository.get_users_batch = AsyncMock(return_value=[])
        mock_repository.get_channels_batch = AsyncMock(return_value=[
            Channel(id='C123', name='general', channel_type='public_channel'),
            Channel(id='C456', name='random', channel_type='public_channel'),
        ])

        status = await status_service.get_status()

        assert len(status.items) == 2

        # Find items by channel
        items_by_channel = {item.channel_id: item for item in status.items}

        # First mention (replied) should be LOW
        assert items_by_channel['C123'].priority == Priority.LOW
        assert 'already replied' in items_by_channel['C123'].reason

        # Second mention (not replied) should be CRITICAL
        assert items_by_channel['C456'].priority == Priority.CRITICAL
        assert 'already replied' not in items_by_channel['C456'].reason
