"""Status tool for getting Slack attention items."""

from typing import Any

from slack_assistant.agent.tools.base import BaseTool
from slack_assistant.db.repository import Repository
from slack_assistant.formatting.models import Priority
from slack_assistant.services.status import StatusService
from slack_assistant.slack.client import SlackClient


class StatusTool(BaseTool):
    """Tool for getting Slack status and attention-needed items."""

    def __init__(self, client: SlackClient, repository: Repository):
        self._client = client
        self._repository = repository
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
- LOW: Already replied mentions

Also returns pending reminders (Later section)."""

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
                }
            },
            'required': [],
        }

    async def execute(self, hours_back: int = 24, **kwargs: Any) -> dict[str, Any]:
        """Get Slack status.

        Args:
            hours_back: Number of hours to look back.

        Returns:
            Status report as dict.
        """
        status = await self._service.get_status(hours_back=hours_back)

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

        for item in status.items:
            result['items'].append(
                {
                    'priority': item.priority.name,
                    'channel': item.formatted_channel,
                    'user': item.formatted_user,
                    'text_preview': item.text_preview,
                    'timestamp': item.timestamp.isoformat() if item.timestamp else None,
                    'link': item.link,
                    'reason': item.reason,
                    'thread_ts': item.thread_ts,
                }
            )

        return result
