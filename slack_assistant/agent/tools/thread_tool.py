"""Thread tool for getting full thread conversations."""

from typing import Any

from slack_assistant.agent.tools.base import BaseTool
from slack_assistant.db.repository import Repository
from slack_assistant.formatting import EntityResolver, collect_entities
from slack_assistant.formatting.patterns import format_text
from slack_assistant.slack.client import SlackClient


class ThreadTool(BaseTool):
    """Tool for getting full thread conversations."""

    def __init__(self, client: SlackClient, repository: Repository):
        self._client = client
        self._repository = repository
        self._resolver = EntityResolver(repository)

    @property
    def name(self) -> str:
        return 'get_thread'

    @property
    def description(self) -> str:
        return """Get all messages in a Slack thread.
Use this to drill into a specific thread and see the full conversation.
Accepts either a thread_ts or a Slack message link."""

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            'type': 'object',
            'properties': {
                'channel_id': {
                    'type': 'string',
                    'description': 'Channel ID (e.g., C1234567890)',
                },
                'thread_ts': {
                    'type': 'string',
                    'description': 'Thread timestamp (e.g., 1234567890.123456)',
                },
                'message_link': {
                    'type': 'string',
                    'description': 'Slack message permalink (alternative to channel_id/thread_ts)',
                },
            },
            'required': [],
        }

    async def execute(
        self,
        channel_id: str | None = None,
        thread_ts: str | None = None,
        message_link: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get thread messages.

        Args:
            channel_id: Channel ID.
            thread_ts: Thread timestamp.
            message_link: Alternative: Slack permalink.

        Returns:
            Thread messages as dict.
        """
        # Parse link if provided
        if message_link and not (channel_id and thread_ts):
            parsed = self._parse_link(message_link)
            if parsed:
                channel_id, thread_ts = parsed

        if not channel_id or not thread_ts:
            return {'error': 'Either message_link or both channel_id and thread_ts are required'}

        # Get thread messages from database
        messages = await self._repository.get_thread_messages(channel_id, thread_ts)

        if not messages:
            return {
                'channel_id': channel_id,
                'thread_ts': thread_ts,
                'count': 0,
                'messages': [],
            }

        # Collect entities for formatting
        all_entities = collect_entities('')
        for msg in messages:
            entities = collect_entities(msg.text)
            if msg.user_id:
                entities.user_ids.add(msg.user_id)
            entities.channel_ids.add(msg.channel_id)
            all_entities.merge(entities)

        context = await self._resolver.resolve(all_entities)

        # Get channel name
        channel_name = context.channels.get(channel_id, channel_id)

        return {
            'channel_id': channel_id,
            'channel_name': channel_name,
            'thread_ts': thread_ts,
            'count': len(messages),
            'link': self._client.get_message_link(channel_id, thread_ts),
            'messages': [
                {
                    'user': context.users.get(msg.user_id, msg.user_id) if msg.user_id else 'unknown',
                    'user_id': msg.user_id,
                    'text': format_text(msg.text, context.users, context.channels) if msg.text else '',
                    'timestamp': msg.created_at.isoformat() if msg.created_at else None,
                    'is_parent': msg.ts == thread_ts,
                    'link': self._client.get_message_link(channel_id, msg.ts, msg.thread_ts),
                }
                for msg in messages
            ],
        }

    def _parse_link(self, link: str) -> tuple[str, str] | None:
        """Parse a Slack message link to extract channel_id and ts.

        Args:
            link: Slack message permalink.

        Returns:
            Tuple of (channel_id, message_ts) or None.
        """
        import urllib.parse

        parsed = urllib.parse.urlparse(link)

        if 'slack.com' in parsed.netloc or parsed.path.startswith('/archives/'):
            parts = parsed.path.strip('/').split('/')
            if len(parts) >= 2 and parts[0] == 'archives':
                channel_id = parts[1]
                if len(parts) >= 3:
                    ts_part = parts[2]
                    if ts_part.startswith('p'):
                        ts_digits = ts_part[1:]
                        message_ts = f'{ts_digits[:-6]}.{ts_digits[-6:]}'
                        return channel_id, message_ts

        elif parsed.scheme == 'slack':
            params = urllib.parse.parse_qs(parsed.query)
            channel_id = params.get('id', [None])[0]
            message_ts = params.get('message', [None])[0]
            if channel_id and message_ts:
                return channel_id, message_ts

        return None
