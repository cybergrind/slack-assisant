"""Tests for Slack message formatting."""

from slack_assistant.formatting.models import FormattedStatusItem, Priority
from slack_assistant.formatting.patterns import CollectedEntities, collect_entities, format_text
from slack_assistant.formatting.resolver import ResolvedContext


class TestCollectEntities:
    """Tests for entity collection from text."""

    def test_collect_user_mentions(self):
        text = 'Hello <@U123ABC>!'
        entities = collect_entities(text)
        assert entities.user_ids == {'U123ABC'}
        assert entities.channel_ids == set()

    def test_collect_multiple_users(self):
        text = '<@U111> mentioned <@U222> and <@U333>'
        entities = collect_entities(text)
        assert entities.user_ids == {'U111', 'U222', 'U333'}

    def test_collect_channel_without_name(self):
        text = 'See <#C456DEF>'
        entities = collect_entities(text)
        assert entities.channel_ids == {'C456DEF'}

    def test_skip_channel_with_name(self):
        # When name is provided, no need to resolve
        text = 'See <#C456DEF|general>'
        entities = collect_entities(text)
        assert entities.channel_ids == set()

    def test_collect_mixed(self):
        text = '<@U111> posted in <#C222> about <@U333>'
        entities = collect_entities(text)
        assert entities.user_ids == {'U111', 'U333'}
        assert entities.channel_ids == {'C222'}

    def test_empty_text(self):
        entities = collect_entities('')
        assert not entities

    def test_none_text(self):
        entities = collect_entities(None)
        assert not entities

    def test_merge(self):
        e1 = CollectedEntities(user_ids={'U1'}, channel_ids={'C1'})
        e2 = CollectedEntities(user_ids={'U2'}, channel_ids={'C2'})
        e1.merge(e2)
        assert e1.user_ids == {'U1', 'U2'}
        assert e1.channel_ids == {'C1', 'C2'}

    def test_user_mention_with_display_name(self):
        text = 'Hello <@U123ABC|john>!'
        entities = collect_entities(text)
        assert entities.user_ids == {'U123ABC'}

    def test_w_prefix_user(self):
        # Some workspace users have W prefix
        text = 'Hello <@W123ABC>!'
        entities = collect_entities(text)
        assert entities.user_ids == {'W123ABC'}


class TestFormatText:
    """Tests for text formatting."""

    def test_format_user_mention(self):
        text = 'Hello <@U123>!'
        result = format_text(text, {'U123': 'john_doe'}, {})
        assert result == 'Hello @john_doe!'

    def test_format_unknown_user(self):
        text = 'Hello <@U999>!'
        result = format_text(text, {}, {})
        assert result == 'Hello @U999!'

    def test_format_channel_with_name(self):
        text = 'See <#C123|general>'
        result = format_text(text, {}, {})
        assert result == 'See #general'

    def test_format_channel_without_name(self):
        text = 'See <#C123>'
        result = format_text(text, {}, {'C123': 'random'})
        assert result == 'See #random'

    def test_format_url_with_label(self):
        text = 'Check <https://example.com|this link>'
        result = format_text(text, {}, {})
        assert result == 'Check this link'

    def test_format_url_without_label(self):
        text = 'Check <https://example.com>'
        result = format_text(text, {}, {})
        assert result == 'Check https://example.com'

    def test_format_special_mentions(self):
        assert format_text('Hey <!here>', {}, {}) == 'Hey @here'
        assert format_text('Hey <!channel>', {}, {}) == 'Hey @channel'
        assert format_text('Hey <!everyone>', {}, {}) == 'Hey @everyone'

    def test_format_html_entities(self):
        text = 'Tom &amp; Jerry &lt;script&gt;'
        result = format_text(text, {}, {})
        assert result == 'Tom & Jerry <script>'

    def test_format_complex_message(self):
        text = '<@U123> said in <#C456|general>: check &lt;this&gt; <!here>'
        result = format_text(text, {'U123': 'alice'}, {})
        assert result == '@alice said in #general: check <this> @here'

    def test_format_empty_text(self):
        assert format_text('', {}, {}) == ''

    def test_format_none_text(self):
        assert format_text(None, {}, {}) == ''

    def test_format_team_mention_with_label(self):
        text = 'Hey <!subteam^S123|@devteam>'
        result = format_text(text, {}, {})
        assert result == 'Hey @devteam'

    def test_format_team_mention_without_label(self):
        text = 'Hey <!subteam^S123>'
        result = format_text(text, {}, {})
        assert result == 'Hey @team'

    def test_format_multiple_users_cyrillic(self):
        text = 'если <@U035N3R77GW> и <@U0388MHA23B> будут ревьювать'
        result = format_text(text, {'U035N3R77GW': 'john.doe', 'U0388MHA23B': 'jane.smith'}, {})
        assert result == 'если @john.doe и @jane.smith будут ревьювать'


class TestResolvedContext:
    """Tests for ResolvedContext."""

    def test_get_user_name_found(self):
        context = ResolvedContext(users={'U123': 'john'}, channels={})
        assert context.get_user_name('U123') == 'john'

    def test_get_user_name_not_found(self):
        context = ResolvedContext(users={}, channels={})
        assert context.get_user_name('U123') == 'U123'

    def test_get_channel_name_found(self):
        context = ResolvedContext(users={}, channels={'C123': 'general'})
        assert context.get_channel_name('C123') == 'general'

    def test_get_channel_name_not_found(self):
        context = ResolvedContext(users={}, channels={})
        assert context.get_channel_name('C123') == 'C123'


class TestFormattedStatusItem:
    """Tests for FormattedStatusItem Pydantic model."""

    def test_text_preview_with_context(self):
        context = ResolvedContext(
            users={'U123': 'john_doe'},
            channels={'C456': 'general'},
        )
        item = FormattedStatusItem.from_raw(
            priority=Priority.CRITICAL,
            channel_id='C456',
            message_ts='123.456',
            text='Hey <@U123>, check <#C456>',
            context=context,
        )
        assert item.text_preview == 'Hey @john_doe, check #general'

    def test_text_preview_truncation(self):
        context = ResolvedContext(users={}, channels={})
        item = FormattedStatusItem.from_raw(
            priority=Priority.LOW,
            channel_id='C1',
            message_ts='1.1',
            text='A' * 200,
            context=context,
        )
        assert len(item.text_preview) == 100
        assert item.text_preview.endswith('...')

    def test_formatted_user_with_context(self):
        context = ResolvedContext(users={'U123': 'alice'}, channels={})
        item = FormattedStatusItem.from_raw(
            priority=Priority.HIGH,
            channel_id='C1',
            message_ts='1.1',
            user_id='U123',
            context=context,
        )
        assert item.formatted_user == 'alice'

    def test_formatted_user_fallback_to_user_name(self):
        item = FormattedStatusItem.from_raw(
            priority=Priority.HIGH,
            channel_id='C1',
            message_ts='1.1',
            user_name='explicit_name',
            context=None,
        )
        assert item.formatted_user == 'explicit_name'

    def test_formatted_user_fallback_to_id(self):
        item = FormattedStatusItem.from_raw(
            priority=Priority.HIGH,
            channel_id='C1',
            message_ts='1.1',
            user_id='U456',
            context=None,
        )
        assert item.formatted_user == 'U456'

    def test_formatted_user_unknown(self):
        item = FormattedStatusItem.from_raw(
            priority=Priority.HIGH,
            channel_id='C1',
            message_ts='1.1',
            context=None,
        )
        assert item.formatted_user == 'unknown'

    def test_formatted_channel_with_context(self):
        context = ResolvedContext(users={}, channels={'C123': 'random'})
        item = FormattedStatusItem.from_raw(
            priority=Priority.LOW,
            channel_id='C123',
            message_ts='1.1',
            context=context,
        )
        assert item.formatted_channel == '#random'

    def test_formatted_channel_with_explicit_name(self):
        item = FormattedStatusItem.from_raw(
            priority=Priority.LOW,
            channel_id='C123',
            channel_name='explicit_channel',
            message_ts='1.1',
            context=None,
        )
        assert item.formatted_channel == '#explicit_channel'

    def test_formatted_channel_fallback_to_id(self):
        item = FormattedStatusItem.from_raw(
            priority=Priority.LOW,
            channel_id='C123',
            message_ts='1.1',
            context=None,
        )
        assert item.formatted_channel == '#C123'

    def test_without_context(self):
        item = FormattedStatusItem.from_raw(
            priority=Priority.LOW,
            channel_id='C123',
            message_ts='1.1',
            user_id='U456',
            text='<@U789> hello',
            context=None,
        )
        # Falls back to IDs
        assert item.formatted_user == 'U456'
        assert item.formatted_channel == '#C123'
        assert item.text_preview == '@U789 hello'

    def test_priority_values(self):
        assert Priority.CRITICAL.value == 1
        assert Priority.HIGH.value == 2
        assert Priority.MEDIUM.value == 3
        assert Priority.LOW.value == 4

    def test_model_fields(self):
        from datetime import datetime

        context = ResolvedContext(users={'U1': 'user1'}, channels={'C1': 'chan1'})
        ts = datetime(2025, 1, 19, 10, 25, 0)
        item = FormattedStatusItem.from_raw(
            priority=Priority.CRITICAL,
            channel_id='C1',
            channel_name='test-channel',
            message_ts='123.456',
            thread_ts='123.000',
            user_id='U1',
            user_name='test_user',
            text='test message',
            timestamp=ts,
            link='https://slack.com/archives/C1/p123456',
            reason='You were mentioned',
            metadata={'key': 'value'},
            context=context,
        )
        assert item.priority == Priority.CRITICAL
        assert item.channel_id == 'C1'
        assert item.channel_name == 'test-channel'
        assert item.message_ts == '123.456'
        assert item.thread_ts == '123.000'
        assert item.user_id == 'U1'
        assert item.user_name == 'test_user'
        assert item.raw_text == 'test message'
        assert item.timestamp == ts
        assert item.link == 'https://slack.com/archives/C1/p123456'
        assert item.reason == 'You were mentioned'
        assert item.metadata == {'key': 'value'}
