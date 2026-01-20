"""Session state models."""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ItemDisposition(str, Enum):
    """Disposition of a processed item."""

    REVIEWED = 'reviewed'  # User saw and acknowledged
    DEFERRED = 'deferred'  # Handle later
    ACTED_ON = 'acted_on'  # User took action


class ProcessedItem(BaseModel):
    """A message/thread that has been processed in this session."""

    channel_id: str
    message_ts: str
    thread_ts: str | None = None
    disposition: ItemDisposition
    processed_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    notes: str | None = None

    @property
    def key(self) -> str:
        """Get unique key for this item."""
        return f'{self.channel_id}:{self.message_ts}'


class AnalyzedItem(BaseModel):
    """LLM's analysis of a message item."""

    channel_id: str
    message_ts: str
    thread_ts: str | None = None
    priority: str  # 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
    summary: str
    action_needed: str | None = None
    context_notes: str | None = None
    analyzed_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    @property
    def key(self) -> str:
        """Get unique key for this item."""
        return f'{self.channel_id}:{self.message_ts}'


class ConversationSummary(BaseModel):
    """Summary of a conversation session."""

    summary_text: str
    key_topics: list[str] = Field(default_factory=list)
    pending_follow_ups: list[str] = Field(default_factory=list)


class SessionState(BaseModel):
    """Complete session state."""

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    started_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    last_activity_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    processed_items: list[ProcessedItem] = Field(default_factory=list)
    analyzed_items: list[AnalyzedItem] = Field(default_factory=list)
    conversation_summary: ConversationSummary | None = None
    current_focus: str | None = None

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity_at = datetime.now().isoformat()

    def add_processed_item(
        self,
        channel_id: str,
        message_ts: str,
        disposition: ItemDisposition,
        thread_ts: str | None = None,
        notes: str | None = None,
    ) -> ProcessedItem:
        """Add a processed item to the session.

        Args:
            channel_id: Slack channel ID.
            message_ts: Message timestamp.
            disposition: How the item was handled.
            thread_ts: Optional thread timestamp.
            notes: Optional notes about the item.

        Returns:
            The created ProcessedItem.
        """
        item = ProcessedItem(
            channel_id=channel_id,
            message_ts=message_ts,
            thread_ts=thread_ts,
            disposition=disposition,
            notes=notes,
        )
        self.processed_items.append(item)
        self.touch()
        return item

    def get_processed_keys(self) -> set[str]:
        """Get set of processed item keys.

        Returns:
            Set of "channel_id:message_ts" keys.
        """
        return {item.key for item in self.processed_items}

    def add_analyzed_item(
        self,
        channel_id: str,
        message_ts: str,
        priority: str,
        summary: str,
        thread_ts: str | None = None,
        action_needed: str | None = None,
        context_notes: str | None = None,
    ) -> AnalyzedItem:
        """Add or update an analyzed item in the session.

        Upserts by key - if an item with the same channel_id:message_ts exists,
        it will be replaced.

        Args:
            channel_id: Slack channel ID.
            message_ts: Message timestamp.
            priority: Priority level (CRITICAL, HIGH, MEDIUM, LOW).
            summary: Brief description of the message.
            thread_ts: Optional thread timestamp.
            action_needed: What action is required (optional).
            context_notes: Relevant context (optional).

        Returns:
            The created/updated AnalyzedItem.
        """
        item = AnalyzedItem(
            channel_id=channel_id,
            message_ts=message_ts,
            thread_ts=thread_ts,
            priority=priority,
            summary=summary,
            action_needed=action_needed,
            context_notes=context_notes,
        )

        # Upsert by key - remove existing item with same key if present
        key = item.key
        self.analyzed_items = [i for i in self.analyzed_items if i.key != key]
        self.analyzed_items.append(item)
        self.touch()
        return item

    def get_analyzed_item(self, channel_id: str, message_ts: str) -> AnalyzedItem | None:
        """Get an analyzed item by channel and message.

        Args:
            channel_id: Slack channel ID.
            message_ts: Message timestamp.

        Returns:
            The AnalyzedItem if found, None otherwise.
        """
        key = f'{channel_id}:{message_ts}'
        for item in self.analyzed_items:
            if item.key == key:
                return item
        return None

    def get_analyzed_keys(self) -> set[str]:
        """Get set of analyzed item keys.

        Returns:
            Set of "channel_id:message_ts" keys.
        """
        return {item.key for item in self.analyzed_items}

    def is_item_processed(self, channel_id: str, message_ts: str) -> bool:
        """Check if an item has been processed.

        Args:
            channel_id: Slack channel ID.
            message_ts: Message timestamp.

        Returns:
            True if item has been processed.
        """
        key = f'{channel_id}:{message_ts}'
        return key in self.get_processed_keys()

    def get_session_age_hours(self) -> float:
        """Get session age in hours.

        Returns:
            Hours since session started.
        """
        started = datetime.fromisoformat(self.started_at)
        return (datetime.now() - started).total_seconds() / 3600

    def get_summary_text(self) -> str:
        """Get formatted summary text for prompts.

        Returns:
            Human-readable session summary.
        """
        lines = [f'Session ID: {self.session_id}']
        lines.append(f'Started: {self.started_at}')
        lines.append(f'Items processed: {len(self.processed_items)}')
        lines.append(f'Items analyzed: {len(self.analyzed_items)}')

        if self.current_focus:
            lines.append(f'Current focus: {self.current_focus}')

        if self.conversation_summary:
            lines.append('')
            lines.append('Last summary:')
            lines.append(self.conversation_summary.summary_text)

            if self.conversation_summary.pending_follow_ups:
                lines.append('')
                lines.append('Pending follow-ups:')
                for follow_up in self.conversation_summary.pending_follow_ups:
                    lines.append(f'  - {follow_up}')

        return '\n'.join(lines)
