"""Tests for database models."""


from slack_assistant.db.models import Channel, User


class TestUserDisplayName:
    """Tests for User.display_name_or_fallback property."""

    def test_display_name_priority(self):
        """Test that display_name takes priority."""
        user = User(
            id='U123',
            name='john',
            real_name='John Doe',
            display_name='Johnny',
        )
        assert user.display_name_or_fallback == 'Johnny'

    def test_real_name_fallback(self):
        """Test fallback to real_name when display_name is None."""
        user = User(
            id='U123',
            name='john',
            real_name='John Doe',
            display_name=None,
        )
        assert user.display_name_or_fallback == 'John Doe'

    def test_name_fallback(self):
        """Test fallback to name when display_name and real_name are None."""
        user = User(
            id='U123',
            name='john',
            real_name=None,
            display_name=None,
        )
        assert user.display_name_or_fallback == 'john'

    def test_id_fallback(self):
        """Test fallback to id when all name fields are None."""
        user = User(
            id='U123',
            name=None,
            real_name=None,
            display_name=None,
        )
        assert user.display_name_or_fallback == 'U123'

    def test_empty_string_fallback(self):
        """Test that empty strings are treated as falsy and fall back."""
        user = User(
            id='U123',
            name='john',
            real_name='',
            display_name='',
        )
        assert user.display_name_or_fallback == 'john'


class TestChannelDisplayName:
    """Tests for Channel.get_display_name() method."""

    def test_public_channel(self):
        """Test display name for public channel."""
        channel = Channel(
            id='C123',
            name='general',
            channel_type='public_channel',
        )
        assert channel.get_display_name() == '#general'

    def test_private_channel(self):
        """Test display name for private channel."""
        channel = Channel(
            id='C456',
            name='secret',
            channel_type='private_channel',
        )
        assert channel.get_display_name() == '#secret'

    def test_group_dm(self):
        """Test display name for group DM (MPIM)."""
        channel = Channel(
            id='G789',
            name='mpdm-user1--user2--user3-1',
            channel_type='mpim',
        )
        assert channel.get_display_name() == 'Group DM: mpdm-user1--user2--user3-1'

    def test_im_without_resolver(self):
        """Test IM channel without user resolver."""
        channel = Channel(
            id='D123',
            name='U456',
            channel_type='im',
        )
        assert channel.get_display_name() == 'DM: U456'

    def test_im_with_resolver(self):
        """Test IM channel with user resolver."""
        channel = Channel(
            id='D123',
            name='U456',
            channel_type='im',
        )

        def resolver(user_id: str) -> str:
            return 'john' if user_id == 'U456' else user_id

        assert channel.get_display_name(resolver) == 'DM: @john'

    def test_im_with_resolver_lambda(self):
        """Test IM channel with lambda resolver."""
        channel = Channel(
            id='D123',
            name='U456',
            channel_type='im',
        )
        assert channel.get_display_name(lambda uid: 'jane') == 'DM: @jane'

    def test_channel_without_name(self):
        """Test channel with None name falls back to ID."""
        channel = Channel(
            id='C999',
            name=None,
            channel_type='public_channel',
        )
        assert channel.get_display_name() == '#C999'

    def test_im_without_name(self):
        """Test IM channel with None name falls back to ID."""
        channel = Channel(
            id='D999',
            name=None,
            channel_type='im',
        )
        assert channel.get_display_name() == 'DM: D999'

    def test_mpim_without_name(self):
        """Test MPIM channel with None name falls back to ID."""
        channel = Channel(
            id='G999',
            name=None,
            channel_type='mpim',
        )
        assert channel.get_display_name() == 'Group DM: G999'

    def test_empty_string_name_fallback(self):
        """Test that empty string name falls back to ID."""
        channel = Channel(
            id='C999',
            name='',
            channel_type='public_channel',
        )
        assert channel.get_display_name() == '#C999'
