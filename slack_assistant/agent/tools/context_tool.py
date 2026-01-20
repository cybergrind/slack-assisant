"""Context tool for finding related messages."""

from typing import Any

from slack_assistant.agent.tools.base import BaseTool
from slack_assistant.db.repository import Repository
from slack_assistant.services.embeddings import EmbeddingService
from slack_assistant.services.search import SearchService
from slack_assistant.slack.client import SlackClient


class ContextTool(BaseTool):
    """Tool for finding context/related messages."""

    def __init__(self, client: SlackClient, repository: Repository, embedding_service: EmbeddingService | None = None):
        self._client = client
        self._repository = repository
        self._embedding_service = embedding_service
        self._service = SearchService(client, repository, embedding_service)

    @property
    def name(self) -> str:
        return 'find_context'

    @property
    def description(self) -> str:
        return """Find related messages for a given Slack message link.
Useful for understanding the broader context of a conversation.
Returns messages that are semantically related to the given message."""

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            'type': 'object',
            'properties': {
                'message_link': {
                    'type': 'string',
                    'description': 'Slack message permalink',
                },
                'limit': {
                    'type': 'integer',
                    'description': 'Maximum number of related messages (default: 10)',
                    'default': 10,
                    'minimum': 1,
                    'maximum': 25,
                },
            },
            'required': ['message_link'],
        }

    async def execute(
        self,
        message_link: str,
        limit: int = 10,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Find related messages.

        Args:
            message_link: Slack message permalink.
            limit: Maximum number of results.

        Returns:
            Related messages as dict.
        """
        results = await self._service.find_context(message_link, limit=limit)

        if not results:
            return {
                'message_link': message_link,
                'count': 0,
                'related_messages': [],
            }

        return {
            'message_link': message_link,
            'count': len(results),
            'related_messages': [
                {
                    'channel': f'#{result.channel_name}' if result.channel_name else result.message.channel_id,
                    'user': result.user_name or result.message.user_id or 'unknown',
                    'text': result.message.text or '',
                    'timestamp': result.message.created_at.isoformat() if result.message.created_at else None,
                    'score': round(result.score, 3),
                    'link': result.link,
                }
                for result in results
            ],
        }
