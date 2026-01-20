"""Search tool for finding Slack messages."""

from typing import Any

from slack_assistant.agent.tools.base import BaseTool
from slack_assistant.db.repository import Repository
from slack_assistant.services.embeddings import EmbeddingService
from slack_assistant.services.search import SearchService
from slack_assistant.slack.client import SlackClient


class SearchTool(BaseTool):
    """Tool for searching Slack messages."""

    def __init__(self, client: SlackClient, repository: Repository, embedding_service: EmbeddingService | None = None):
        self._client = client
        self._repository = repository
        self._embedding_service = embedding_service
        self._service = SearchService(client, repository, embedding_service)

    @property
    def name(self) -> str:
        return 'search'

    @property
    def description(self) -> str:
        return """Search for Slack messages matching a query.
Uses text-based search and optionally vector similarity search.
Returns matching messages with relevance scores."""

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            'type': 'object',
            'properties': {
                'query': {
                    'type': 'string',
                    'description': 'Search query text',
                },
                'limit': {
                    'type': 'integer',
                    'description': 'Maximum number of results (default: 10)',
                    'default': 10,
                    'minimum': 1,
                    'maximum': 50,
                },
                'use_slack_api': {
                    'type': 'boolean',
                    'description': 'Also search using Slack API (slower but may find more)',
                    'default': False,
                },
            },
            'required': ['query'],
        }

    async def execute(
        self,
        query: str,
        limit: int = 10,
        use_slack_api: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Search for messages.

        Args:
            query: Search query text.
            limit: Maximum number of results.
            use_slack_api: Whether to also use Slack API.

        Returns:
            Search results as dict.
        """
        results = await self._service.search(
            query=query,
            limit=limit,
            use_vector=self._embedding_service is not None,
            use_text=True,
            use_slack_api=use_slack_api,
        )

        return {
            'query': query,
            'count': len(results),
            'results': [
                {
                    'channel': f'#{result.channel_name}' if result.channel_name else result.message.channel_id,
                    'user': result.user_name or result.message.user_id or 'unknown',
                    'text': result.message.text or '',
                    'timestamp': result.message.created_at.isoformat() if result.message.created_at else None,
                    'score': round(result.score, 3),
                    'match_type': result.match_type,
                    'link': result.link,
                    'thread_ts': result.message.thread_ts,
                }
                for result in results
            ],
        }
