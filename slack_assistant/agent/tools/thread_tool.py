"""Thread tool for getting full thread conversations."""

from collections import defaultdict
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
        return """Get all messages in a Slack thread with reactions.
Use this to drill into a specific thread and see the full conversation.
Accepts either a thread_ts or a Slack message link.
Use refresh_reactions=true to fetch live reactions from Slack API."""

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
                'refresh_reactions': {
                    'type': 'boolean',
                    'description': 'If true, fetch live reactions from Slack API (default: false, uses cached data)',
                },
            },
            'required': [],
        }

    async def execute(
        self,
        channel_id: str | None = None,
        thread_ts: str | None = None,
        message_link: str | None = None,
        refresh_reactions: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get thread messages with reactions.

        Args:
            channel_id: Channel ID.
            thread_ts: Thread timestamp.
            message_link: Alternative: Slack permalink.
            refresh_reactions: If True, fetch live reactions from Slack API.

        Returns:
            Thread messages with reactions as dict.
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
                'reactions_source': 'none',
            }

        # Collect entities for formatting
        all_entities = collect_entities('')
        for msg in messages:
            entities = collect_entities(msg.text)
            if msg.user_id:
                entities.user_ids.add(msg.user_id)
            entities.channel_ids.add(msg.channel_id)
            all_entities.merge(entities)

        # Get reactions - either from database or live API
        reactions_source = 'database'
        reactions_by_msg_id: dict[int, dict[str, list[str]]] = {}

        if refresh_reactions:
            # Fetch live reactions from Slack API and update database
            reactions_source = 'live_api'
            for msg in messages:
                live_reactions = await self._client.get_message_reactions(channel_id, msg.ts)
                if live_reactions:
                    # Store in database for future use
                    await self._repository.upsert_reactions(msg.id, live_reactions)
                    # Format for output: {emoji: [user1, user2]}
                    reactions_by_msg_id[msg.id] = self._format_reactions(live_reactions)
                    # Collect user IDs from reactions for name resolution
                    for reaction in live_reactions:
                        for user_id in reaction.get('users', []):
                            all_entities.user_ids.add(user_id)
                else:
                    reactions_by_msg_id[msg.id] = {}
        else:
            # Get reactions from database
            message_ids = [msg.id for msg in messages]
            db_reactions = await self._repository.get_reactions_for_messages_batch(message_ids)
            for msg_id, reaction_list in db_reactions.items():
                grouped: dict[str, list[str]] = defaultdict(list)
                for reaction in reaction_list:
                    grouped[reaction.name].append(reaction.user_id)
                    all_entities.user_ids.add(reaction.user_id)
                reactions_by_msg_id[msg_id] = dict(grouped)

        context = await self._resolver.resolve(all_entities)

        # Get channel name
        channel_name = context.channels.get(channel_id, channel_id)

        # Build output with reactions (resolve user IDs to names)
        formatted_messages = []
        for msg in messages:
            msg_reactions = reactions_by_msg_id.get(msg.id, {})
            # Resolve user IDs to names in reactions
            formatted_reactions = {
                emoji: [context.users.get(uid, uid) for uid in user_ids]
                for emoji, user_ids in msg_reactions.items()
            }

            formatted_messages.append({
                'user': context.users.get(msg.user_id, msg.user_id) if msg.user_id else 'unknown',
                'user_id': msg.user_id,
                'text': format_text(msg.text, context.users, context.channels) if msg.text else '',
                'timestamp': msg.created_at.isoformat() if msg.created_at else None,
                'is_parent': msg.ts == thread_ts,
                'link': self._client.get_message_link(channel_id, msg.ts, msg.thread_ts),
                'reactions': formatted_reactions,
            })

        return {
            'channel_id': channel_id,
            'channel_name': channel_name,
            'thread_ts': thread_ts,
            'count': len(messages),
            'link': self._client.get_message_link(channel_id, thread_ts),
            'messages': formatted_messages,
            'reactions_source': reactions_source,
        }

    def _format_reactions(self, reactions: list[dict[str, Any]]) -> dict[str, list[str]]:
        """Format Slack API reactions to {emoji: [user_ids]} dict.

        Args:
            reactions: List of reactions from Slack API.

        Returns:
            Dict mapping emoji name to list of user IDs.
        """
        result: dict[str, list[str]] = {}
        for reaction in reactions:
            name = reaction.get('name', '')
            users = reaction.get('users', [])
            result[name] = users
        return result

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
