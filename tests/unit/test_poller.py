"""Tests for the Slack poller module."""

from unittest.mock import AsyncMock

import pytest

from slack_assistant.db.models import Channel
from slack_assistant.db.repository import Repository
from slack_assistant.slack.client import SlackClient
from slack_assistant.slack.poller import SlackPoller


class TestSlackPoller:
    """Tests for SlackPoller class."""

    @pytest.fixture
    def mock_slack_client(self):
        """Create a mock Slack client."""
        client = AsyncMock(spec=SlackClient)
        client.user_id = 'U123456'
        return client

    @pytest.fixture
    def mock_repository(self):
        """Create a mock repository."""
        return AsyncMock(spec=Repository)

    @pytest.fixture
    def poller(self, mock_slack_client, mock_repository):
        """Create a SlackPoller instance with mocked dependencies."""
        return SlackPoller(
            client=mock_slack_client,
            repository=mock_repository,
            poll_interval=60,
        )


class TestGetChannelDisplayName:
    """Tests for the _get_channel_display_name method."""

    @pytest.fixture
    def mock_slack_client(self):
        """Create a mock Slack client."""
        client = AsyncMock(spec=SlackClient)
        client.user_id = 'U123456'
        return client

    @pytest.fixture
    def mock_repository(self):
        """Create a mock repository."""
        return AsyncMock(spec=Repository)

    @pytest.fixture
    def poller(self, mock_slack_client, mock_repository):
        """Create a SlackPoller instance with mocked dependencies."""
        return SlackPoller(
            client=mock_slack_client,
            repository=mock_repository,
            poll_interval=60,
        )

    async def test_im_channel_with_display_name(self, poller, mock_repository):
        """Test IM channel display with user's display name."""
        # Setup
        channel = Channel(
            id='D123456',
            name='U789012',  # For IM channels, name is the user ID
            channel_type='im',
            is_archived=False,
        )
        mock_repository.get_channel_display_name = AsyncMock(return_value='DM: @Johnny')

        # Execute
        result = await poller._get_channel_display_name(channel)

        # Verify
        assert result == 'DM: @Johnny'
        mock_repository.get_channel_display_name.assert_called_once_with(channel)

    async def test_im_channel_with_real_name_fallback(self, poller, mock_repository):
        """Test IM channel display falls back to real name if no display name."""
        # Setup
        channel = Channel(
            id='D123456',
            name='U789012',
            channel_type='im',
            is_archived=False,
        )
        mock_repository.get_channel_display_name = AsyncMock(return_value='DM: @John Doe')

        # Execute
        result = await poller._get_channel_display_name(channel)

        # Verify
        assert result == 'DM: @John Doe'

    async def test_im_channel_with_name_fallback(self, poller, mock_repository):
        """Test IM channel display falls back to name if no display/real name."""
        # Setup
        channel = Channel(
            id='D123456',
            name='U789012',
            channel_type='im',
            is_archived=False,
        )
        mock_repository.get_channel_display_name = AsyncMock(return_value='DM: @john.doe')

        # Execute
        result = await poller._get_channel_display_name(channel)

        # Verify
        assert result == 'DM: @john.doe'

    async def test_im_channel_user_not_found(self, poller, mock_repository):
        """Test IM channel display when user is not found in database."""
        # Setup
        channel = Channel(
            id='D123456',
            name='U789012',
            channel_type='im',
            is_archived=False,
        )
        mock_repository.get_channel_display_name = AsyncMock(return_value='DM: U789012')

        # Execute
        result = await poller._get_channel_display_name(channel)

        # Verify
        assert result == 'DM: U789012'

    async def test_im_channel_no_user_id(self, poller, mock_repository):
        """Test IM channel display when channel has no user ID."""
        # Setup
        channel = Channel(
            id='D123456',
            name=None,  # No user ID
            channel_type='im',
            is_archived=False,
        )
        mock_repository.get_channel_display_name = AsyncMock(return_value='DM: D123456')

        # Execute
        result = await poller._get_channel_display_name(channel)

        # Verify
        assert result == 'DM: D123456'

    async def test_mpim_channel(self, poller, mock_repository):
        """Test group DM (mpim) channel display."""
        # Setup
        channel = Channel(
            id='G123456',
            name='mpdm-user1-user2-user3',
            channel_type='mpim',
            is_archived=False,
        )
        mock_repository.get_channel_display_name = AsyncMock(return_value='Group DM: mpdm-user1-user2-user3')

        # Execute
        result = await poller._get_channel_display_name(channel)

        # Verify
        assert result == 'Group DM: mpdm-user1-user2-user3'

    async def test_mpim_channel_no_name(self, poller, mock_repository):
        """Test group DM channel with no name falls back to ID."""
        # Setup
        channel = Channel(
            id='G123456',
            name=None,
            channel_type='mpim',
            is_archived=False,
        )
        mock_repository.get_channel_display_name = AsyncMock(return_value='Group DM: G123456')

        # Execute
        result = await poller._get_channel_display_name(channel)

        # Verify
        assert result == 'Group DM: G123456'

    async def test_public_channel(self, poller, mock_repository):
        """Test public channel display."""
        # Setup
        channel = Channel(
            id='C123456',
            name='general',
            channel_type='public_channel',
            is_archived=False,
        )
        mock_repository.get_channel_display_name = AsyncMock(return_value='#general')

        # Execute
        result = await poller._get_channel_display_name(channel)

        # Verify
        assert result == '#general'

    async def test_private_channel(self, poller, mock_repository):
        """Test private channel display."""
        # Setup
        channel = Channel(
            id='G123456',
            name='secret-project',
            channel_type='private_channel',
            is_archived=False,
        )
        mock_repository.get_channel_display_name = AsyncMock(return_value='#secret-project')

        # Execute
        result = await poller._get_channel_display_name(channel)

        # Verify
        assert result == '#secret-project'

    async def test_channel_no_name_fallback_to_id(self, poller, mock_repository):
        """Test channel with no name falls back to ID."""
        # Setup
        channel = Channel(
            id='C123456',
            name=None,
            channel_type='public_channel',
            is_archived=False,
        )
        mock_repository.get_channel_display_name = AsyncMock(return_value='#C123456')

        # Execute
        result = await poller._get_channel_display_name(channel)

        # Verify
        assert result == '#C123456'
