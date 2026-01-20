"""Tests for the AnalysisTool."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from slack_assistant.agent.tools.analysis_tool import AnalysisTool
from slack_assistant.db.models import User
from slack_assistant.session import SessionState


class TestAnalysisTool:
    """Tests for AnalysisTool."""

    @pytest.fixture
    def mock_client(self):
        client = MagicMock()
        client.user_id = 'U123'
        client.get_message_link = MagicMock(return_value='https://slack.com/archives/C123/p123')
        return client

    @pytest.fixture
    def mock_repository(self):
        repo = MagicMock()
        repo.get_recent_messages_for_analysis = AsyncMock(return_value=[])
        repo.get_users_batch = AsyncMock(return_value=[])
        return repo

    @pytest.fixture
    def tool(self, mock_client, mock_repository):
        return AnalysisTool(mock_client, mock_repository)

    def test_name(self, tool):
        assert tool.name == 'analyze_messages'

    def test_description_mentions_content_analysis(self, tool):
        desc = tool.description
        assert 'full message' in desc.lower() or 'full text' in desc.lower()
        assert 'content' in desc.lower()

    def test_input_schema(self, tool):
        schema = tool.input_schema
        assert schema['type'] == 'object'
        props = schema['properties']
        assert 'hours_back' in props
        assert 'max_messages' in props
        assert 'include_own_messages' in props
        assert 'text_limit' in props

    def test_to_dict(self, tool):
        d = tool.to_dict()
        assert d['name'] == 'analyze_messages'
        assert 'description' in d
        assert 'input_schema' in d

    @pytest.mark.asyncio
    async def test_execute_no_user_id(self, mock_repository):
        client = MagicMock()
        client.user_id = None
        tool = AnalysisTool(client, mock_repository)

        result = await tool.execute()
        assert 'error' in result
        assert 'User ID not available' in result['error']

    @pytest.mark.asyncio
    async def test_execute_empty_messages(self, tool, mock_repository):
        mock_repository.get_recent_messages_for_analysis.return_value = []
        mock_repository.get_users_batch.return_value = []

        result = await tool.execute()

        assert result['user_id'] == 'U123'
        assert result['hours_back'] == 24
        assert result['total_found'] == 0
        assert result['returned'] == 0
        assert result['messages'] == []

    @pytest.mark.asyncio
    async def test_execute_with_messages(self, tool, mock_client, mock_repository):
        mock_repository.get_recent_messages_for_analysis.return_value = [
            {
                'id': 'C123:1234567890.123456',
                'db_id': 1,
                'channel_id': 'C123',
                'channel': '#general',
                'channel_type': 'public_channel',
                'user_id': 'U456',
                'is_own_message': False,
                'is_mention': True,
                'is_dm': False,
                'is_self_dm': False,
                'text': 'Hey @U123, this is urgent!',
                'thread_ts': None,
                'timestamp': datetime.now().isoformat(),
                'metadata_priority': 'CRITICAL',
            }
        ]
        mock_repository.get_users_batch.return_value = [
            MagicMock(spec=User, id='U456', display_name='John', real_name='John Doe', name='john')
        ]

        result = await tool.execute()

        assert result['total_found'] == 1
        assert result['returned'] == 1
        assert len(result['messages']) == 1

        msg = result['messages'][0]
        assert msg['id'] == 'C123:1234567890.123456'
        assert msg['channel'] == '#general'
        assert msg['user'] == 'John'
        assert msg['is_mention'] is True
        assert msg['metadata_priority'] == 'CRITICAL'
        assert 'urgent' in msg['text']

    @pytest.mark.asyncio
    async def test_execute_text_truncation(self, tool, mock_repository):
        long_text = 'x' * 1000
        mock_repository.get_recent_messages_for_analysis.return_value = [
            {
                'id': 'C123:1234567890.123456',
                'db_id': 1,
                'channel_id': 'C123',
                'channel': '#general',
                'channel_type': 'public_channel',
                'user_id': 'U456',
                'is_own_message': False,
                'is_mention': False,
                'is_dm': False,
                'is_self_dm': False,
                'text': long_text,
                'thread_ts': None,
                'timestamp': datetime.now().isoformat(),
                'metadata_priority': 'LOW',
            }
        ]
        mock_repository.get_users_batch.return_value = []

        result = await tool.execute(text_limit=100)

        msg = result['messages'][0]
        assert len(msg['text']) == 103  # 100 chars + '...'
        assert msg['text'].endswith('...')

    @pytest.mark.asyncio
    async def test_execute_custom_parameters(self, tool, mock_repository):
        mock_repository.get_recent_messages_for_analysis.return_value = []
        mock_repository.get_users_batch.return_value = []

        result = await tool.execute(
            hours_back=48,
            max_messages=25,
            include_own_messages=True,
            text_limit=200,
        )

        assert result['hours_back'] == 48
        assert result['include_own_messages'] is True

        # Verify repository was called with correct params
        call_kwargs = mock_repository.get_recent_messages_for_analysis.call_args.kwargs
        assert call_kwargs['limit'] == 25
        assert call_kwargs['include_own_messages'] is True

    @pytest.mark.asyncio
    async def test_execute_includes_self_dm_when_requested(self, tool, mock_repository):
        mock_repository.get_recent_messages_for_analysis.return_value = [
            {
                'id': 'D123:1234567890.123456',
                'db_id': 1,
                'channel_id': 'D123',
                'channel': '#self',
                'channel_type': 'im',
                'user_id': 'U123',
                'is_own_message': True,
                'is_mention': False,
                'is_dm': False,
                'is_self_dm': True,
                'text': 'super urgent test message',
                'thread_ts': None,
                'timestamp': datetime.now().isoformat(),
                'metadata_priority': 'LOW',  # Metadata says LOW, but content says urgent
            }
        ]
        mock_repository.get_users_batch.return_value = []

        result = await tool.execute(include_own_messages=True)

        assert result['returned'] == 1
        msg = result['messages'][0]
        assert msg['is_own_message'] is True
        assert msg['is_self_dm'] is True
        assert 'urgent' in msg['text']
        # The LLM should override this LOW priority based on content

    @pytest.mark.asyncio
    async def test_execute_generates_link(self, tool, mock_client, mock_repository):
        mock_repository.get_recent_messages_for_analysis.return_value = [
            {
                'id': 'C123:1234567890.123456',
                'db_id': 1,
                'channel_id': 'C123',
                'channel': '#general',
                'channel_type': 'public_channel',
                'user_id': 'U456',
                'is_own_message': False,
                'is_mention': False,
                'is_dm': False,
                'is_self_dm': False,
                'text': 'Test message',
                'thread_ts': 'thread_ts_value',
                'timestamp': datetime.now().isoformat(),
                'metadata_priority': 'LOW',
            }
        ]
        mock_repository.get_users_batch.return_value = []

        await tool.execute()

        # Verify get_message_link was called with correct params
        mock_client.get_message_link.assert_called_once_with(
            'C123',
            '1234567890.123456',
            'thread_ts_value',
        )

    @pytest.mark.asyncio
    async def test_execute_resolves_user_names(self, tool, mock_repository):
        mock_repository.get_recent_messages_for_analysis.return_value = [
            {
                'id': 'C123:1234567890.123456',
                'db_id': 1,
                'channel_id': 'C123',
                'channel': '#general',
                'channel_type': 'public_channel',
                'user_id': 'U789',
                'is_own_message': False,
                'is_mention': False,
                'is_dm': False,
                'is_self_dm': False,
                'text': 'Hello',
                'thread_ts': None,
                'timestamp': datetime.now().isoformat(),
                'metadata_priority': 'LOW',
            }
        ]

        # Return a user with display_name
        user = MagicMock(spec=User)
        user.id = 'U789'
        user.display_name = 'Jane'
        user.real_name = 'Jane Smith'
        user.name = 'jsmith'
        mock_repository.get_users_batch.return_value = [user]

        result = await tool.execute()

        msg = result['messages'][0]
        assert msg['user'] == 'Jane'  # Should use display_name first

    @pytest.mark.asyncio
    async def test_execute_fallback_user_name(self, tool, mock_repository):
        mock_repository.get_recent_messages_for_analysis.return_value = [
            {
                'id': 'C123:1234567890.123456',
                'db_id': 1,
                'channel_id': 'C123',
                'channel': '#general',
                'channel_type': 'public_channel',
                'user_id': 'U999',
                'is_own_message': False,
                'is_mention': False,
                'is_dm': False,
                'is_self_dm': False,
                'text': 'Hello',
                'thread_ts': None,
                'timestamp': datetime.now().isoformat(),
                'metadata_priority': 'LOW',
            }
        ]
        # User not found in batch lookup
        mock_repository.get_users_batch.return_value = []

        result = await tool.execute()

        msg = result['messages'][0]
        assert msg['user'] == 'U999'  # Falls back to user_id

    @pytest.mark.asyncio
    async def test_execute_resolves_user_mentions_in_text(self, tool, mock_repository):
        """Test that user mentions inside message text are resolved."""
        mock_repository.get_recent_messages_for_analysis.return_value = [
            {
                'id': 'C123:1234567890.123456',
                'db_id': 1,
                'channel_id': 'C123',
                'channel': '#general',
                'channel_type': 'public_channel',
                'user_id': 'U456',
                'is_own_message': False,
                'is_mention': False,
                'is_dm': False,
                'is_self_dm': False,
                'text': 'cc <@U789> check this out',
                'thread_ts': None,
                'timestamp': datetime.now().isoformat(),
                'metadata_priority': 'LOW',
            }
        ]

        # Return users for both sender and mentioned user
        sender = MagicMock(spec=User)
        sender.id = 'U456'
        sender.display_name = 'Sender'
        sender.real_name = None
        sender.name = None

        mentioned = MagicMock(spec=User)
        mentioned.id = 'U789'
        mentioned.display_name = 'MentionedUser'
        mentioned.real_name = None
        mentioned.name = None

        mock_repository.get_users_batch.return_value = [sender, mentioned]

        result = await tool.execute()

        msg = result['messages'][0]
        # The <@U789> should be resolved to @MentionedUser
        assert msg['text'] == 'cc @MentionedUser check this out'
        assert msg['user'] == 'Sender'

    @pytest.mark.asyncio
    async def test_execute_resolves_multiple_mentions_in_text(self, tool, mock_repository):
        """Test that multiple user mentions in text are all resolved."""
        mock_repository.get_recent_messages_for_analysis.return_value = [
            {
                'id': 'C123:1234567890.123456',
                'db_id': 1,
                'channel_id': 'C123',
                'channel': '#general',
                'channel_type': 'public_channel',
                'user_id': 'U456',
                'is_own_message': False,
                'is_mention': False,
                'is_dm': False,
                'is_self_dm': False,
                'text': '<@U111> and <@U222> please review',
                'thread_ts': None,
                'timestamp': datetime.now().isoformat(),
                'metadata_priority': 'LOW',
            }
        ]

        user1 = MagicMock(spec=User)
        user1.id = 'U111'
        user1.display_name = 'Alice'
        user1.real_name = None
        user1.name = None

        user2 = MagicMock(spec=User)
        user2.id = 'U222'
        user2.display_name = 'Bob'
        user2.real_name = None
        user2.name = None

        sender = MagicMock(spec=User)
        sender.id = 'U456'
        sender.display_name = 'Sender'
        sender.real_name = None
        sender.name = None

        mock_repository.get_users_batch.return_value = [user1, user2, sender]

        result = await tool.execute()

        msg = result['messages'][0]
        assert msg['text'] == '@Alice and @Bob please review'

    @pytest.mark.asyncio
    async def test_execute_exclude_analyzed_by_default(self, mock_client, mock_repository):
        """Test that already-analyzed messages are excluded by default."""
        session = SessionState()
        # Mark a message as already analyzed
        session.add_analyzed_item(
            channel_id='C123',
            message_ts='1234567890.123456',
            priority='HIGH',
            summary='Already analyzed',
        )

        tool = AnalysisTool(mock_client, mock_repository, session)

        mock_repository.get_recent_messages_for_analysis.return_value = [
            {
                'id': 'C123:1234567890.123456',  # This one is already analyzed
                'db_id': 1,
                'channel_id': 'C123',
                'channel': '#general',
                'channel_type': 'public_channel',
                'user_id': 'U456',
                'is_own_message': False,
                'is_mention': False,
                'is_dm': False,
                'is_self_dm': False,
                'text': 'Already analyzed message',
                'thread_ts': None,
                'timestamp': datetime.now().isoformat(),
                'metadata_priority': 'HIGH',
            },
            {
                'id': 'C123:9999999999.999999',  # This one is new
                'db_id': 2,
                'channel_id': 'C123',
                'channel': '#general',
                'channel_type': 'public_channel',
                'user_id': 'U789',
                'is_own_message': False,
                'is_mention': False,
                'is_dm': False,
                'is_self_dm': False,
                'text': 'New message',
                'thread_ts': None,
                'timestamp': datetime.now().isoformat(),
                'metadata_priority': 'LOW',
            },
        ]
        mock_repository.get_users_batch.return_value = []

        result = await tool.execute()

        # Should only return the new message
        assert result['returned'] == 1
        assert result['messages'][0]['id'] == 'C123:9999999999.999999'
        assert result['excluded_already_analyzed'] == 1

    @pytest.mark.asyncio
    async def test_execute_include_analyzed_when_requested(self, mock_client, mock_repository):
        """Test that already-analyzed messages can be included."""
        session = SessionState()
        session.add_analyzed_item(
            channel_id='C123',
            message_ts='1234567890.123456',
            priority='HIGH',
            summary='Already analyzed',
        )

        tool = AnalysisTool(mock_client, mock_repository, session)

        mock_repository.get_recent_messages_for_analysis.return_value = [
            {
                'id': 'C123:1234567890.123456',
                'db_id': 1,
                'channel_id': 'C123',
                'channel': '#general',
                'channel_type': 'public_channel',
                'user_id': 'U456',
                'is_own_message': False,
                'is_mention': False,
                'is_dm': False,
                'is_self_dm': False,
                'text': 'Already analyzed message',
                'thread_ts': None,
                'timestamp': datetime.now().isoformat(),
                'metadata_priority': 'HIGH',
            },
        ]
        mock_repository.get_users_batch.return_value = []

        result = await tool.execute(exclude_analyzed=False)

        # Should return the analyzed message when exclude_analyzed=False
        assert result['returned'] == 1
        assert result['messages'][0]['id'] == 'C123:1234567890.123456'
        assert 'excluded_already_analyzed' not in result

    @pytest.mark.asyncio
    async def test_execute_no_session_includes_all(self, mock_client, mock_repository):
        """Test that without a session, all messages are included."""
        tool = AnalysisTool(mock_client, mock_repository, session=None)

        mock_repository.get_recent_messages_for_analysis.return_value = [
            {
                'id': 'C123:1234567890.123456',
                'db_id': 1,
                'channel_id': 'C123',
                'channel': '#general',
                'channel_type': 'public_channel',
                'user_id': 'U456',
                'is_own_message': False,
                'is_mention': False,
                'is_dm': False,
                'is_self_dm': False,
                'text': 'Test message',
                'thread_ts': None,
                'timestamp': datetime.now().isoformat(),
                'metadata_priority': 'LOW',
            },
        ]
        mock_repository.get_users_batch.return_value = []

        result = await tool.execute()

        # Without session, all messages should be returned
        assert result['returned'] == 1
        assert 'excluded_already_analyzed' not in result

    @pytest.mark.asyncio
    async def test_execute_empty_analyzed_keys(self, mock_client, mock_repository):
        """Test behavior with session but no analyzed items."""
        session = SessionState()  # Empty session
        tool = AnalysisTool(mock_client, mock_repository, session)

        mock_repository.get_recent_messages_for_analysis.return_value = [
            {
                'id': 'C123:1234567890.123456',
                'db_id': 1,
                'channel_id': 'C123',
                'channel': '#general',
                'channel_type': 'public_channel',
                'user_id': 'U456',
                'is_own_message': False,
                'is_mention': False,
                'is_dm': False,
                'is_self_dm': False,
                'text': 'Test message',
                'thread_ts': None,
                'timestamp': datetime.now().isoformat(),
                'metadata_priority': 'LOW',
            },
        ]
        mock_repository.get_users_batch.return_value = []

        result = await tool.execute()

        # All messages should be returned, no excluded_already_analyzed key
        assert result['returned'] == 1
        assert 'excluded_already_analyzed' not in result
