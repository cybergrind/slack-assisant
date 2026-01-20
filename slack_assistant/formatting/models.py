"""Pydantic models with automatic Slack formatting."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, PrivateAttr, computed_field

from slack_assistant.formatting.patterns import format_text
from slack_assistant.formatting.resolver import ResolvedContext


class Priority(Enum):
    """Message priority levels."""

    CRITICAL = 1  # Direct mentions
    HIGH = 2  # DMs
    MEDIUM = 3  # Threads you participated in
    LOW = 4  # Channel messages


class FormattedStatusItem(BaseModel):
    """A status item with automatic text formatting.

    Use the `from_raw()` factory method to create instances with
    a ResolvedContext for formatting.

    Attributes:
        priority: Item priority level.
        channel_id: Slack channel ID.
        channel_name: Channel name (may be None if not yet resolved).
        message_ts: Slack message timestamp.
        thread_ts: Thread parent timestamp if this is a reply.
        user_id: User ID who sent the message.
        user_name: User name (may be None if not yet resolved).
        raw_text: Original Slack markup text.
        timestamp: Message datetime.
        link: Slack permalink to the message.
        reason: Why this item needs attention.
        metadata: Additional metadata.

    Computed Fields:
        text_preview: Formatted text with resolved mentions (max 100 chars).
        formatted_user: Resolved user display name.
        formatted_channel: Resolved channel name with # prefix.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        populate_by_name=True,
    )

    # Core fields from raw data
    priority: Priority
    channel_id: str
    channel_name: str | None = None
    message_ts: str
    thread_ts: str | None = None
    user_id: str | None = None
    user_name: str | None = None
    raw_text: str = ''
    timestamp: datetime | None = None
    link: str = ''
    reason: str = ''
    metadata: dict[str, Any] = {}

    # Private context for formatting (not serialized)
    _context: ResolvedContext | None = PrivateAttr(default=None)

    @computed_field
    @property
    def text_preview(self) -> str:
        """Formatted text with resolved mentions (max 100 chars)."""
        users = self._context.users if self._context else {}
        channels = self._context.channels if self._context else {}
        formatted = format_text(self.raw_text, users, channels)
        return self._truncate(formatted, 100)

    @computed_field
    @property
    def formatted_user(self) -> str:
        """Resolved user display name."""
        if self.user_name:
            return self.user_name
        if self._context and self.user_id:
            return self._context.get_user_name(self.user_id)
        return self.user_id or 'unknown'

    @computed_field
    @property
    def formatted_channel(self) -> str:
        """Resolved channel name with # prefix."""
        if self.channel_name:
            return f'#{self.channel_name}'
        if self._context:
            return f'#{self._context.get_channel_name(self.channel_id)}'
        return f'#{self.channel_id}'

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        """Truncate text with ellipsis if needed."""
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + '...'

    @classmethod
    def from_raw(
        cls,
        *,
        priority: Priority,
        channel_id: str,
        channel_name: str | None = None,
        message_ts: str,
        thread_ts: str | None = None,
        user_id: str | None = None,
        user_name: str | None = None,
        text: str = '',
        timestamp: datetime | None = None,
        link: str = '',
        reason: str = '',
        metadata: dict[str, Any] | None = None,
        context: ResolvedContext | None = None,
    ) -> 'FormattedStatusItem':
        """Factory method to create item with context.

        Args:
            priority: Item priority level.
            channel_id: Slack channel ID.
            channel_name: Channel name if already known.
            message_ts: Slack message timestamp.
            thread_ts: Thread parent timestamp if reply.
            user_id: User ID who sent message.
            user_name: User name if already known.
            text: Raw Slack markup text.
            timestamp: Message datetime.
            link: Slack permalink.
            reason: Why this needs attention.
            metadata: Additional metadata.
            context: ResolvedContext for formatting.

        Returns:
            FormattedStatusItem with context set.
        """
        item = cls(
            priority=priority,
            channel_id=channel_id,
            channel_name=channel_name,
            message_ts=message_ts,
            thread_ts=thread_ts,
            user_id=user_id,
            user_name=user_name,
            raw_text=text,
            timestamp=timestamp,
            link=link,
            reason=reason,
            metadata=metadata or {},
        )
        item._context = context
        return item
