"""Analysis tool for LLM-based message categorization."""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from slack_assistant.agent.tools.base import BaseTool
from slack_assistant.db.repository import Repository
from slack_assistant.formatting import collect_entities
from slack_assistant.formatting.patterns import format_text
from slack_assistant.slack.client import SlackClient


if TYPE_CHECKING:
    from slack_assistant.session import SessionState


class AnalysisTool(BaseTool):
    """Tool for LLM to analyze messages with full content access.

    Unlike get_status which pre-filters messages by metadata (mentions, DMs, etc.),
    this tool returns ALL recent messages with full text content, allowing the LLM
    to intelligently categorize and prioritize based on actual message content.
    """

    def __init__(
        self,
        client: SlackClient,
        repository: Repository,
        session: 'SessionState | None' = None,
    ):
        """Initialize analysis tool.

        Args:
            client: Slack client for generating links.
            repository: Database repository.
            session: Optional session state for filtering already-analyzed items.
        """
        self._client = client
        self._repository = repository
        self._session = session

    @property
    def name(self) -> str:
        return 'analyze_messages'

    @property
    def description(self) -> str:
        return """Analyze recent messages with full content access for intelligent categorization.

Use this tool when the user asks for status or what needs their attention.
Unlike get_status which filters by metadata, this tool gives you full message
text so you can categorize based on actual content (urgency words, deadlines, etc.).

Returns messages with:
- Full text content (up to text_limit chars)
- Channel context (name, type, is_dm)
- Metadata hints (is_mention, is_dm, metadata_priority)
- Slack link for easy navigation

You should assign priority based on content analysis:
- CRITICAL: Urgency indicators ("urgent", "ASAP", "blocking"), explicit deadlines
- HIGH: Direct questions, action requests, time-sensitive content
- MEDIUM: FYIs, project updates, discussions needing awareness
- LOW: General chat, automated messages, already-addressed items

The metadata_priority is a hint based on message type, but you should override
it based on content. A self-DM saying "super urgent" should be CRITICAL.

By default, messages you've already analyzed (via save_analysis) are excluded.
Set exclude_analyzed=false to include them if you need to re-analyze."""

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            'type': 'object',
            'properties': {
                'hours_back': {
                    'type': 'integer',
                    'description': 'Number of hours to look back (default: 24)',
                    'default': 24,
                    'minimum': 1,
                    'maximum': 168,
                },
                'max_messages': {
                    'type': 'integer',
                    'description': 'Maximum number of messages to return (default: 50)',
                    'default': 50,
                    'minimum': 1,
                    'maximum': 100,
                },
                'include_own_messages': {
                    'type': 'boolean',
                    'description': 'Include messages sent by the user (default: false, set true for self-DM testing)',
                    'default': False,
                },
                'text_limit': {
                    'type': 'integer',
                    'description': 'Maximum characters per message text (default: 500)',
                    'default': 500,
                    'minimum': 100,
                    'maximum': 2000,
                },
                'exclude_analyzed': {
                    'type': 'boolean',
                    'description': 'Exclude messages already analyzed in this session (default: true)',
                    'default': True,
                },
            },
            'required': [],
        }

    async def execute(
        self,
        hours_back: int = 24,
        max_messages: int = 50,
        include_own_messages: bool = False,
        text_limit: int = 500,
        exclude_analyzed: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyze recent messages for LLM categorization.

        Args:
            hours_back: Number of hours to look back.
            max_messages: Maximum number of messages to return.
            include_own_messages: Include messages sent by the user.
            text_limit: Maximum characters per message text.
            exclude_analyzed: Exclude messages already analyzed in this session.

        Returns:
            Dict with messages and metadata for LLM analysis.
        """
        user_id = self._client.user_id
        if not user_id:
            return {'error': 'User ID not available. Please ensure Slack client is authenticated.'}

        since = datetime.now() - timedelta(hours=hours_back)

        # Get raw messages from repository
        raw_messages = await self._repository.get_recent_messages_for_analysis(
            user_id=user_id,
            since=since,
            limit=max_messages,
            include_own_messages=include_own_messages,
        )

        # Filter out already-analyzed messages if session is available
        analyzed_keys: set[str] = set()
        if exclude_analyzed and self._session is not None:
            analyzed_keys = self._session.get_analyzed_keys()
            raw_messages = [
                msg for msg in raw_messages if msg['id'] not in analyzed_keys
            ]

        # Collect all user IDs: message senders + users mentioned in text
        all_user_ids: set[str] = set()
        for msg in raw_messages:
            if msg['user_id']:
                all_user_ids.add(msg['user_id'])
            # Also collect users mentioned in message text
            entities = collect_entities(msg['text'])
            all_user_ids |= entities.user_ids

        # Get user info for resolving names
        users = await self._repository.get_users_batch(list(all_user_ids))
        user_map = {u.id: u.display_name or u.real_name or u.name or u.id for u in users}

        # Format messages for LLM
        messages = []
        for msg in raw_messages:
            # Format text to resolve user mentions, channel links, etc.
            text = format_text(msg['text'], user_map, {})
            # Truncate if needed
            if len(text) > text_limit:
                text = text[:text_limit] + '...'

            # Generate Slack link
            link = self._client.get_message_link(
                msg['channel_id'],
                msg['id'].split(':')[1],  # Extract ts from id
                msg['thread_ts'],
            )

            # Resolve user name
            user_name = user_map.get(msg['user_id'], msg['user_id']) if msg['user_id'] else 'Unknown'

            messages.append({
                'id': msg['id'],
                'channel': msg['channel'],
                'channel_type': msg['channel_type'],
                'user': user_name,
                'is_own_message': msg['is_own_message'],
                'is_mention': msg['is_mention'],
                'is_dm': msg['is_dm'],
                'is_self_dm': msg['is_self_dm'],
                'text': text,
                'timestamp': msg['timestamp'],
                'link': link,
                'metadata_priority': msg['metadata_priority'],
            })

        result: dict[str, Any] = {
            'user_id': user_id,
            'hours_back': hours_back,
            'total_found': len(raw_messages),
            'returned': len(messages),
            'include_own_messages': include_own_messages,
            'messages': messages,
        }

        if exclude_analyzed and analyzed_keys:
            result['excluded_already_analyzed'] = len(analyzed_keys)

        return result
