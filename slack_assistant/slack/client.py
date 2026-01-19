"""Slack API client wrapper with rate limiting."""

import logging
from typing import Any

from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from slack_assistant.slack.rate_limiter import SLACK_RATE_LIMITS, RateLimitConfig, RateLimiter


logger = logging.getLogger(__name__)


class SlackClient:
    """Async Slack API client wrapper with rate limiting.

    All API methods are rate-limited using method-specific configurations
    based on Slack's tier system.
    """

    def __init__(self, token: str, rate_limit_enabled: bool = True):
        """Initialize Slack client.

        Args:
            token: Slack user OAuth token (xoxp-...).
            rate_limit_enabled: Whether to enable rate limiting.
        """
        self.client = AsyncWebClient(token=token)
        self.user_id: str | None = None
        self.user_name: str | None = None
        self.team_id: str | None = None

        self._rate_limit_enabled = rate_limit_enabled
        self._rate_limiters: dict[str, RateLimiter] = {}

    def _get_rate_limiter(self, method_name: str) -> RateLimiter:
        """Get or create a rate limiter for a Slack API method.

        Args:
            method_name: Slack API method name.

        Returns:
            RateLimiter configured for the method.
        """
        if method_name not in self._rate_limiters:
            config = SLACK_RATE_LIMITS.get(method_name, RateLimitConfig())
            self._rate_limiters[method_name] = RateLimiter(config)
        return self._rate_limiters[method_name]

    async def _execute(self, method_name: str, func, *args, **kwargs):
        """Execute an API call with optional rate limiting.

        Args:
            method_name: Slack API method name for rate limit config.
            func: Async function to execute.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            Result of the API call.
        """
        if self._rate_limit_enabled:
            limiter = self._get_rate_limiter(method_name)
            return await limiter.execute(func, *args, **kwargs)
        return await func(*args, **kwargs)

    async def authenticate(self) -> bool:
        """Verify token and get current user info."""
        try:
            response = await self._execute(
                'auth.test',
                self.client.auth_test,
            )
            self.user_id = response['user_id']
            self.user_name = response['user']
            self.team_id = response['team_id']
            logger.info(f'Authenticated as {self.user_name} (ID: {self.user_id})')
            return True
        except SlackApiError as e:
            logger.error(f'Authentication failed: {e.response["error"]}')
            return False

    async def get_conversations(self, types: str = 'public_channel,private_channel,mpim,im') -> list[dict[str, Any]]:
        """Fetch all conversations the user is a member of."""
        conversations = []
        cursor = None

        try:
            while True:
                response = await self._execute(
                    'conversations.list',
                    self.client.conversations_list,
                    types=types,
                    exclude_archived=True,
                    limit=200,
                    cursor=cursor,
                )

                for channel in response.get('channels', []):
                    if channel.get('is_member', True):  # DMs don't have is_member
                        conversations.append(channel)

                cursor = response.get('response_metadata', {}).get('next_cursor')
                if not cursor:
                    break

            logger.debug(f'Found {len(conversations)} conversations')
            return conversations

        except SlackApiError as e:
            logger.error(f'Failed to fetch conversations: {e.response["error"]}')
            return []

    async def get_channel_history(
        self,
        channel_id: str,
        oldest: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch messages from a channel."""
        messages = []
        cursor = None

        try:
            while True:
                kwargs: dict[str, Any] = {
                    'channel': channel_id,
                    'limit': min(limit - len(messages), 100),
                }
                if oldest:
                    kwargs['oldest'] = oldest
                if cursor:
                    kwargs['cursor'] = cursor

                response = await self._execute(
                    'conversations.history',
                    self.client.conversations_history,
                    **kwargs,
                )
                messages.extend(response.get('messages', []))

                if len(messages) >= limit:
                    break

                cursor = response.get('response_metadata', {}).get('next_cursor')
                if not cursor:
                    break

            return messages

        except SlackApiError as e:
            error = e.response.get('error', 'unknown')
            if error not in ('channel_not_found', 'not_in_channel'):
                logger.warning(f'Failed to fetch history for {channel_id}: {error}')
            return []

    async def get_thread_replies(
        self,
        channel_id: str,
        thread_ts: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch replies in a thread."""
        try:
            response = await self._execute(
                'conversations.replies',
                self.client.conversations_replies,
                channel=channel_id,
                ts=thread_ts,
                limit=limit,
            )
            # First message is the parent, rest are replies
            messages = response.get('messages', [])
            return messages[1:] if len(messages) > 1 else []
        except SlackApiError as e:
            logger.warning(f'Failed to fetch thread {thread_ts}: {e.response["error"]}')
            return []

    async def get_user_info(self, user_id: str) -> dict[str, Any] | None:
        """Get user information."""
        try:
            response = await self._execute(
                'users.info',
                self.client.users_info,
                user=user_id,
            )
            return response.get('user')
        except SlackApiError as e:
            logger.warning(f'Failed to get user {user_id}: {e.response["error"]}')
            return None

    async def get_reminders(self) -> list[dict[str, Any]]:
        """Get all reminders for the authenticated user."""
        try:
            response = await self._execute(
                'reminders.list',
                self.client.reminders_list,
            )
            return response.get('reminders', [])
        except SlackApiError as e:
            logger.warning(f'Failed to fetch reminders: {e.response["error"]}')
            return []

    async def search_messages(self, query: str, count: int = 20) -> list[dict[str, Any]]:
        """Search messages (requires search:read scope)."""
        try:
            response = await self._execute(
                'search.messages',
                self.client.search_messages,
                query=query,
                count=count,
                sort='timestamp',
                sort_dir='desc',
            )
            return response.get('messages', {}).get('matches', [])
        except SlackApiError as e:
            logger.warning(f'Failed to search messages: {e.response["error"]}')
            return []

    def get_message_link(self, channel_id: str, message_ts: str, thread_ts: str | None = None) -> str:
        """Generate a Slack message permalink."""
        ts_formatted = message_ts.replace('.', '')
        base_url = f'https://slack.com/archives/{channel_id}/p{ts_formatted}'
        if thread_ts and thread_ts != message_ts:
            thread_formatted = thread_ts.replace('.', '')
            base_url += f'?thread_ts={thread_formatted}'
        return base_url
