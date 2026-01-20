"""Status service for generating attention-needed items."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from slack_assistant.db.repository import Repository
from slack_assistant.formatting import (
    CollectedEntities,
    EntityResolver,
    FormattedStatusItem,
    collect_entities,
)
from slack_assistant.formatting.models import Priority
from slack_assistant.slack.client import SlackClient


logger = logging.getLogger(__name__)


@dataclass
class Status:
    """Complete status report."""

    items: list[FormattedStatusItem]
    reminders: list[dict[str, Any]]
    generated_at: datetime

    @property
    def by_priority(self) -> dict[Priority, list[FormattedStatusItem]]:
        """Group items by priority."""
        result: dict[Priority, list[FormattedStatusItem]] = {p: [] for p in Priority}
        for item in self.items:
            result[item.priority].append(item)
        return result


class StatusService:
    """Service for generating status reports."""

    def __init__(self, client: SlackClient, repository: Repository):
        self.client = client
        self.repository = repository
        self.resolver = EntityResolver(repository)

    async def get_status(self, hours_back: int = 24) -> Status:
        """Generate a status report of items needing attention.

        Uses two-phase approach:
        1. Collect raw data and entity IDs
        2. Batch resolve entities
        3. Create formatted items
        """
        if not self.client.user_id:
            raise RuntimeError('Client not authenticated')

        since = datetime.now() - timedelta(hours=hours_back)

        # Phase 1: Collect raw data and entity IDs
        raw_items: list[dict[str, Any]] = []
        all_entities = CollectedEntities()

        # Collect mentions
        mentions = await self.repository.get_unread_mentions(self.client.user_id, since)
        for msg in mentions:
            entities = collect_entities(msg.text)
            if msg.user_id:
                entities.user_ids.add(msg.user_id)
            entities.channel_ids.add(msg.channel_id)
            all_entities.merge(entities)

            raw_items.append(
                {
                    'priority': Priority.CRITICAL,
                    'channel_id': msg.channel_id,
                    'message_ts': msg.ts,
                    'thread_ts': msg.thread_ts,
                    'user_id': msg.user_id,
                    'text': msg.text or '',
                    'timestamp': msg.created_at,
                    'reason': 'You were mentioned',
                }
            )

        # Collect DMs
        dms = await self.repository.get_dm_messages(since)
        dms = [m for m in dms if m.user_id != self.client.user_id]
        for msg in dms:
            entities = collect_entities(msg.text)
            if msg.user_id:
                entities.user_ids.add(msg.user_id)
            entities.channel_ids.add(msg.channel_id)
            all_entities.merge(entities)

            raw_items.append(
                {
                    'priority': Priority.HIGH,
                    'channel_id': msg.channel_id,
                    'message_ts': msg.ts,
                    'thread_ts': msg.thread_ts,
                    'user_id': msg.user_id,
                    'text': msg.text or '',
                    'timestamp': msg.created_at,
                    'reason': 'Direct message',
                }
            )

        # Collect thread replies
        thread_data = await self.repository.get_threads_with_replies(self.client.user_id, since)
        seen_threads = set()
        for row in thread_data:
            thread_key = f'{row["channel_id"]}:{row.get("thread_ts") or row["ts"]}'
            if thread_key in seen_threads:
                continue
            seen_threads.add(thread_key)

            entities = collect_entities(row.get('text'))
            if row.get('user_id'):
                entities.user_ids.add(row['user_id'])
            entities.channel_ids.add(row['channel_id'])
            all_entities.merge(entities)

            raw_items.append(
                {
                    'priority': Priority.MEDIUM,
                    'channel_id': row['channel_id'],
                    'channel_name': row.get('channel_name'),
                    'message_ts': row['ts'],
                    'thread_ts': row.get('thread_ts'),
                    'user_id': row.get('user_id'),
                    'text': row.get('text') or '',
                    'timestamp': row.get('created_at'),
                    'reason': 'Reply in thread you participated in',
                }
            )

        # Phase 2: Batch resolve all entities
        context = await self.resolver.resolve(all_entities)

        # Phase 3: Create formatted items
        items: list[FormattedStatusItem] = []
        for raw in raw_items:
            item = FormattedStatusItem.from_raw(
                priority=raw['priority'],
                channel_id=raw['channel_id'],
                channel_name=raw.get('channel_name') or context.channels.get(raw['channel_id']),
                message_ts=raw['message_ts'],
                thread_ts=raw['thread_ts'],
                user_id=raw['user_id'],
                user_name=context.users.get(raw['user_id']) if raw['user_id'] else None,
                text=raw['text'],
                timestamp=raw['timestamp'],
                link=self.client.get_message_link(raw['channel_id'], raw['message_ts'], raw['thread_ts']),
                reason=raw['reason'],
                context=context,
            )
            items.append(item)

        # Sort by priority then timestamp
        items.sort(key=lambda x: (x.priority.value, -(x.timestamp.timestamp() if x.timestamp else 0)))

        # Get reminders
        reminders = await self._get_reminders()

        return Status(
            items=items,
            reminders=reminders,
            generated_at=datetime.now(),
        )

    async def _get_reminders(self) -> list[dict[str, Any]]:
        """Get pending reminders (Later section)."""
        reminders = await self.repository.get_pending_reminders(self.client.user_id)
        return [
            {
                'id': r.id,
                'text': r.text,
                'time': r.time.isoformat() if r.time else None,
                'recurring': r.recurring,
            }
            for r in reminders
        ]
