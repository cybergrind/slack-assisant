"""Database repository for CRUD operations using SQLAlchemy ORM."""

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from slack_assistant.db.connection import get_session
from slack_assistant.db.models import Channel, Message, Reaction, Reminder, SyncState, User


class Repository:
    """Database repository for Slack Assistant."""

    # Channel operations

    async def upsert_channel(self, channel: Channel) -> None:
        """Insert or update a channel."""
        async with get_session() as session:
            # Use __table__.c to reference columns to avoid metadata conflict
            metadata_col = Channel.__table__.c.metadata
            stmt = (
                insert(Channel)
                .values(
                    id=channel.id,
                    name=channel.name,
                    channel_type=channel.channel_type,
                    is_archived=channel.is_archived,
                    created_at=channel.created_at,
                )
                .values({metadata_col: channel.metadata_})
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=['id'],
                set_={
                    'name': stmt.excluded.name,
                    'channel_type': stmt.excluded.channel_type,
                    'is_archived': stmt.excluded.is_archived,
                    metadata_col: stmt.excluded.metadata,
                },
            )
            await session.execute(stmt)
            await session.commit()

    async def get_channel(self, channel_id: str) -> Channel | None:
        """Get a channel by ID."""
        async with get_session() as session:
            result = await session.execute(select(Channel).where(Channel.id == channel_id))
            return result.scalar_one_or_none()

    async def get_all_channels(self) -> list[Channel]:
        """Get all non-archived channels."""
        async with get_session() as session:
            result = await session.execute(select(Channel).where(Channel.is_archived == False))  # noqa: E712
            return list(result.scalars().all())

    # User operations

    async def upsert_user(self, user: User) -> None:
        """Insert or update a user."""
        async with get_session() as session:
            metadata_col = User.__table__.c.metadata
            stmt = (
                insert(User)
                .values(
                    id=user.id,
                    name=user.name,
                    real_name=user.real_name,
                    display_name=user.display_name,
                    is_bot=user.is_bot,
                )
                .values({metadata_col: user.metadata_})
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=['id'],
                set_={
                    'name': stmt.excluded.name,
                    'real_name': stmt.excluded.real_name,
                    'display_name': stmt.excluded.display_name,
                    'is_bot': stmt.excluded.is_bot,
                    metadata_col: stmt.excluded.metadata,
                },
            )
            await session.execute(stmt)
            await session.commit()

    async def get_user(self, user_id: str) -> User | None:
        """Get a user by ID."""
        async with get_session() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            return result.scalar_one_or_none()

    # Message operations

    async def upsert_message(self, message: Message) -> int:
        """Insert or update a message, returning the database ID."""
        async with get_session() as session:
            metadata_col = Message.__table__.c.metadata
            stmt = (
                insert(Message)
                .values(
                    channel_id=message.channel_id,
                    ts=message.ts,
                    user_id=message.user_id,
                    text=message.text,
                    thread_ts=message.thread_ts,
                    reply_count=message.reply_count,
                    is_edited=message.is_edited,
                    message_type=message.message_type,
                    created_at=message.created_at,
                )
                .values({metadata_col: message.metadata_})
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=['channel_id', 'ts'],
                set_={
                    'user_id': stmt.excluded.user_id,
                    'text': stmt.excluded.text,
                    'thread_ts': stmt.excluded.thread_ts,
                    'reply_count': stmt.excluded.reply_count,
                    'is_edited': stmt.excluded.is_edited,
                    metadata_col: stmt.excluded.metadata,
                },
            ).returning(Message.id)
            result = await session.execute(stmt)
            await session.commit()
            return result.scalar_one()

    async def get_message(self, channel_id: str, ts: str) -> Message | None:
        """Get a message by channel and timestamp."""
        async with get_session() as session:
            result = await session.execute(select(Message).where(Message.channel_id == channel_id, Message.ts == ts))
            return result.scalar_one_or_none()

    async def get_message_by_id(self, message_id: int) -> Message | None:
        """Get a message by database ID."""
        async with get_session() as session:
            result = await session.execute(select(Message).where(Message.id == message_id))
            return result.scalar_one_or_none()

    async def get_messages_since(
        self,
        channel_id: str,
        since_ts: str | None = None,
        limit: int = 100,
    ) -> list[Message]:
        """Get messages from a channel since a timestamp."""
        async with get_session() as session:
            if since_ts:
                stmt = (
                    select(Message)
                    .where(Message.channel_id == channel_id, Message.ts > since_ts)
                    .order_by(Message.ts.asc())
                    .limit(limit)
                )
            else:
                stmt = select(Message).where(Message.channel_id == channel_id).order_by(Message.ts.desc()).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_thread_messages(self, channel_id: str, thread_ts: str) -> list[Message]:
        """Get all messages in a thread."""
        async with get_session() as session:
            stmt = (
                select(Message)
                .where(
                    Message.channel_id == channel_id,
                    (Message.ts == thread_ts) | (Message.thread_ts == thread_ts),
                )
                .order_by(Message.ts.asc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # Reaction operations

    async def upsert_reactions(self, message_id: int, reactions: list[dict[str, Any]]) -> None:
        """Update reactions for a message (replace all)."""
        async with get_session() as session:
            # Delete existing reactions
            await session.execute(delete(Reaction).where(Reaction.message_id == message_id))

            # Insert new reactions
            for reaction in reactions:
                name = reaction.get('name', '')
                users = reaction.get('users', [])
                for user_id in users:
                    stmt = insert(Reaction).values(
                        message_id=message_id,
                        name=name,
                        user_id=user_id,
                    )
                    stmt = stmt.on_conflict_do_nothing()
                    await session.execute(stmt)

            await session.commit()

    async def get_reactions(self, message_id: int) -> list[Reaction]:
        """Get reactions for a message."""
        async with get_session() as session:
            result = await session.execute(select(Reaction).where(Reaction.message_id == message_id))
            return list(result.scalars().all())

    # Sync state operations

    async def get_sync_state(self, channel_id: str) -> SyncState | None:
        """Get sync state for a channel."""
        async with get_session() as session:
            result = await session.execute(select(SyncState).where(SyncState.channel_id == channel_id))
            return result.scalar_one_or_none()

    async def upsert_sync_state(self, sync_state: SyncState) -> None:
        """Update sync state for a channel."""
        async with get_session() as session:
            stmt = insert(SyncState).values(
                channel_id=sync_state.channel_id,
                last_ts=sync_state.last_ts,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=['channel_id'],
                set_={
                    'last_ts': stmt.excluded.last_ts,
                },
            )
            await session.execute(stmt)
            await session.commit()

    # Reminder operations

    async def upsert_reminder(self, reminder: Reminder) -> None:
        """Insert or update a reminder."""
        async with get_session() as session:
            metadata_col = Reminder.__table__.c.metadata
            stmt = (
                insert(Reminder)
                .values(
                    id=reminder.id,
                    user_id=reminder.user_id,
                    text=reminder.text,
                    time=reminder.time,
                    complete_ts=reminder.complete_ts,
                    recurring=reminder.recurring,
                )
                .values({metadata_col: reminder.metadata_})
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=['id'],
                set_={
                    'text': stmt.excluded.text,
                    'time': stmt.excluded.time,
                    'complete_ts': stmt.excluded.complete_ts,
                    'recurring': stmt.excluded.recurring,
                    metadata_col: stmt.excluded.metadata,
                },
            )
            await session.execute(stmt)
            await session.commit()

    async def get_pending_reminders(self, user_id: str) -> list[Reminder]:
        """Get pending (incomplete) reminders for a user."""
        async with get_session() as session:
            result = await session.execute(
                select(Reminder)
                .where(Reminder.user_id == user_id, Reminder.complete_ts.is_(None))
                .order_by(Reminder.time.asc())
            )
            return list(result.scalars().all())

    # Status queries

    async def get_unread_mentions(self, user_id: str, since: datetime | None = None) -> list[Message]:
        """Get messages that mention a user."""
        async with get_session() as session:
            mention_pattern = f'%<@{user_id}>%'
            stmt = select(Message).where(Message.text.like(mention_pattern))

            if since:
                stmt = stmt.where(Message.created_at > since)

            stmt = stmt.order_by(Message.created_at.desc()).limit(50)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_dm_messages(self, since: datetime | None = None) -> list[Message]:
        """Get recent DM messages."""
        async with get_session() as session:
            stmt = select(Message).join(Channel, Message.channel_id == Channel.id).where(Channel.channel_type == 'im')

            if since:
                stmt = stmt.where(Message.created_at > since)

            stmt = stmt.order_by(Message.created_at.desc()).limit(50)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_threads_with_replies(self, user_id: str, since: datetime | None = None) -> list[dict[str, Any]]:
        """Get threads where user participated that have new replies."""
        async with get_session() as session:
            # First, find all threads the user has participated in
            user_threads_stmt = (
                select(Message.channel_id, Message.thread_ts, Message.ts).where(Message.user_id == user_id).distinct()
            )
            user_threads_result = await session.execute(user_threads_stmt)
            user_threads = user_threads_result.all()

            # Build set of (channel_id, thread_ts) tuples
            thread_keys = set()
            for row in user_threads:
                channel_id, thread_ts, ts = row
                # Use thread_ts if available, otherwise ts
                effective_thread_ts = thread_ts or ts
                thread_keys.add((channel_id, effective_thread_ts))

            if not thread_keys:
                return []

            # Find replies in these threads from other users
            results = []
            for channel_id, thread_ts in thread_keys:
                stmt = (
                    select(Message, Channel.name.label('channel_name'))
                    .join(Channel, Message.channel_id == Channel.id)
                    .where(
                        Message.channel_id == channel_id,
                        (Message.ts == thread_ts) | (Message.thread_ts == thread_ts),
                        Message.user_id != user_id,
                    )
                )

                if since:
                    stmt = stmt.where(Message.created_at > since)

                stmt = stmt.order_by(Message.created_at.desc()).limit(10)
                result = await session.execute(stmt)

                for msg, channel_name in result:
                    results.append(
                        {
                            'id': msg.id,
                            'channel_id': msg.channel_id,
                            'ts': msg.ts,
                            'user_id': msg.user_id,
                            'text': msg.text,
                            'thread_ts': msg.thread_ts,
                            'reply_count': msg.reply_count,
                            'is_edited': msg.is_edited,
                            'message_type': msg.message_type,
                            'created_at': msg.created_at,
                            'updated_at': msg.updated_at,
                            'metadata': msg.metadata_,
                            'channel_name': channel_name,
                        }
                    )

            # Sort by created_at and limit
            results.sort(key=lambda x: x.get('created_at') or datetime.min, reverse=True)
            return results[:100]
