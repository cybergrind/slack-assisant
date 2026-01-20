"""Status tool for getting Slack attention items."""

from typing import TYPE_CHECKING, Any

from slack_assistant.agent.tools.base import BaseTool
from slack_assistant.db.repository import Repository
from slack_assistant.formatting.models import Priority
from slack_assistant.services.status import StatusService
from slack_assistant.slack.client import SlackClient


if TYPE_CHECKING:
    from slack_assistant.session import SessionState


class StatusTool(BaseTool):
    """Tool for getting Slack status and attention-needed items."""

    def __init__(
        self,
        client: SlackClient,
        repository: Repository,
        session: 'SessionState | None' = None,
    ):
        """Initialize status tool.

        Args:
            client: Slack client.
            repository: Database repository.
            session: Optional session state for filtering processed items.
        """
        self._client = client
        self._repository = repository
        self._session = session
        self._service = StatusService(client, repository)

    @property
    def name(self) -> str:
        return 'get_status'

    @property
    def description(self) -> str:
        return """Get the current Slack status showing items that need attention.
Returns prioritized items grouped by:
- CRITICAL: Direct mentions (messages where user is @-mentioned)
- HIGH: Direct messages from other users
- MEDIUM: Replies in threads the user participated in
- LOW: Already replied mentions, or items acknowledged with your emoji patterns

Also returns pending reminders (Later section).

Items already processed in this session are filtered out unless include_processed=true."""

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
                'include_processed': {
                    'type': 'boolean',
                    'description': 'Include items already processed in this session (default: false)',
                    'default': False,
                },
            },
            'required': [],
        }

    async def execute(self, hours_back: int = 24, include_processed: bool = False, **kwargs: Any) -> dict[str, Any]:
        """Get Slack status.

        Args:
            hours_back: Number of hours to look back.
            include_processed: Include items already processed in this session.

        Returns:
            Status report as dict.
        """
        status = await self._service.get_status(
            hours_back=hours_back,
            session=self._session if not include_processed else None,
        )

        # Convert to serializable format
        result: dict[str, Any] = {
            'generated_at': status.generated_at.isoformat(),
            'summary': {
                'total_items': len(status.items),
                'critical_count': len(status.by_priority[Priority.CRITICAL]),
                'high_count': len(status.by_priority[Priority.HIGH]),
                'medium_count': len(status.by_priority[Priority.MEDIUM]),
                'low_count': len(status.by_priority[Priority.LOW]),
                'reminders_count': len(status.reminders),
            },
            'items': [],
            'reminders': status.reminders,
        }

        # Add session info if available
        if self._session:
            result['session'] = {
                'session_id': self._session.session_id,
                'processed_count': len(self._session.processed_items),
                'filtered_processed': not include_processed,
            }

        for item in status.items:
            result['items'].append(
                {
                    'priority': item.priority.name,
                    'channel': item.formatted_channel,
                    'channel_id': item.channel_id,
                    'message_ts': item.message_ts,
                    'user': item.formatted_user,
                    'text_preview': item.text_preview,
                    'timestamp': item.timestamp.isoformat() if item.timestamp else None,
                    'link': item.link,
                    'reason': item.reason,
                    'thread_ts': item.thread_ts,
                }
            )

        return result
