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
                    is_self_dm=channel.is_self_dm,
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
                    'is_self_dm': stmt.excluded.is_self_dm,
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

    async def get_self_dm_channel_ids(self) -> set[str]:
        """Get IDs of channels that are DMs to self."""
        async with get_session() as session:
            stmt = select(Channel.id).where(Channel.is_self_dm == True)  # noqa: E712
            result = await session.execute(stmt)
            return {row[0] for row in result.all()}

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

    async def get_sync_states_batch(self, channel_ids: list[str]) -> dict[str, SyncState]:
        """Get sync states for multiple channels in a single query.

        Args:
            channel_ids: List of channel IDs.

        Returns:
            Dict mapping channel_id to SyncState.
        """
        if not channel_ids:
            return {}
        async with get_session() as session:
            result = await session.execute(select(SyncState).where(SyncState.channel_id.in_(channel_ids)))
            return {state.channel_id: state for state in result.scalars().all()}

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

    # Batch operations

    async def get_users_batch(self, user_ids: list[str]) -> list[User]:
        """Get multiple users by IDs in a single query.

        Args:
            user_ids: List of Slack user IDs.

        Returns:
            List of User objects found in database.
        """
        if not user_ids:
            return []
        async with get_session() as session:
            result = await session.execute(select(User).where(User.id.in_(user_ids)))
            return list(result.scalars().all())

    async def get_channels_batch(self, channel_ids: list[str]) -> list[Channel]:
        """Get multiple channels by IDs in a single query.

        Args:
            channel_ids: List of Slack channel IDs.

        Returns:
            List of Channel objects found in database.
        """
        if not channel_ids:
            return []
        async with get_session() as session:
            result = await session.execute(select(Channel).where(Channel.id.in_(channel_ids)))
            return list(result.scalars().all())

    async def get_channel_display_name(self, channel: Channel) -> str:
        """Get human-readable display name for a channel.

        Resolves user names for IM channels by looking up the user.

        Args:
            channel: The Channel object to get display name for.

        Returns:
            Formatted channel name:
            - IM channels: "DM: @username" (with resolved user name)
            - MPIM channels: "Group DM: channel_name"
            - Regular channels: "#channel_name"
        """
        if channel.channel_type == 'im' and channel.name:
            user = await self.get_user(channel.name)
            if user:
                user_name = user.display_name_or_fallback
                return f'DM: @{user_name}'

        return channel.get_display_name()

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

    async def get_user_reply_status_batch(
        self,
        user_id: str,
        mention_contexts: list[tuple[str, str | None, str]],
    ) -> dict[str, bool]:
        """Check if user replied in each thread after the mention.

        Args:
            user_id: The user ID to check for replies.
            mention_contexts: List of (channel_id, thread_ts, mention_ts) tuples.
                thread_ts may be None for top-level messages.

        Returns:
            Dict mapping context key "channel_id:effective_thread_ts" to bool
            indicating whether user has replied after the mention timestamp.
        """
        if not mention_contexts:
            return {}

        result: dict[str, bool] = {}

        async with get_session() as session:
            for channel_id, thread_ts, mention_ts in mention_contexts:
                # For threads, effective_thread_ts is thread_ts
                # For top-level messages that might start threads, use mention_ts as thread root
                effective_thread_ts = thread_ts or mention_ts
                context_key = f'{channel_id}:{effective_thread_ts}'

                # Check if user has any message in this thread after the mention
                stmt = (
                    select(Message.id)
                    .where(
                        Message.channel_id == channel_id,
                        Message.user_id == user_id,
                        Message.ts > mention_ts,
                        # Match messages in the same thread
                        (Message.thread_ts == effective_thread_ts) | (Message.ts == effective_thread_ts),
                    )
                    .limit(1)
                )

                reply_result = await session.execute(stmt)
                has_replied = reply_result.scalar_one_or_none() is not None
                result[context_key] = has_replied

        return result

    # User reaction queries

    async def get_user_reactions(
        self,
        user_id: str,
        since: datetime | None = None,
        emoji_names: list[str] | None = None,
    ) -> list[Reaction]:
        """Get reactions made by a user.

        Args:
            user_id: The user ID to get reactions for.
            since: Optional datetime to filter reactions after.
            emoji_names: Optional list of emoji names to filter by.

        Returns:
            List of Reaction objects.
        """
        async with get_session() as session:
            stmt = select(Reaction).where(Reaction.user_id == user_id)

            if since:
                stmt = stmt.where(Reaction.created_at > since)

            if emoji_names:
                stmt = stmt.where(Reaction.name.in_(emoji_names))

            stmt = stmt.order_by(Reaction.created_at.desc()).limit(200)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_messages_with_user_reactions(
        self,
        user_id: str,
        message_keys: list[tuple[str, str]],
        emoji_names: list[str] | None = None,
    ) -> dict[str, list[str]]:
        """Check which messages have reactions from a user.

        Args:
            user_id: The user ID to check reactions for.
            message_keys: List of (channel_id, message_ts) tuples to check.
            emoji_names: Optional list of emoji names to filter by.

        Returns:
            Dict mapping "channel_id:message_ts" to list of emoji names
            the user reacted with.
        """
        if not message_keys:
            return {}

        result: dict[str, list[str]] = {}

        async with get_session() as session:
            # Get message IDs for the given keys
            for channel_id, message_ts in message_keys:
                key = f'{channel_id}:{message_ts}'

                # Find the message
                msg_stmt = select(Message.id).where(Message.channel_id == channel_id, Message.ts == message_ts)
                msg_result = await session.execute(msg_stmt)
                message_id = msg_result.scalar_one_or_none()

                if message_id is None:
                    continue

                # Find user's reactions on this message
                reaction_stmt = select(Reaction.name).where(
                    Reaction.message_id == message_id, Reaction.user_id == user_id
                )

                if emoji_names:
                    reaction_stmt = reaction_stmt.where(Reaction.name.in_(emoji_names))

                reaction_result = await session.execute(reaction_stmt)
                emojis = [row[0] for row in reaction_result.all()]

                if emojis:
                    result[key] = emojis

        return result

    async def get_user_reactions_on_status_items(
        self,
        user_id: str,
        status_items: list[dict[str, Any]],
        acknowledgment_emojis: list[str],
    ) -> dict[str, list[str]]:
        """Check which status items have acknowledgment reactions from user.

        Args:
            user_id: The user ID to check reactions for.
            status_items: List of status item dicts with 'channel_id' and 'message_ts'.
            acknowledgment_emojis: List of emoji names that mean "acknowledged".

        Returns:
            Dict mapping "channel_id:message_ts" to list of emoji names.
        """
        if not status_items or not acknowledgment_emojis:
            return {}

        # Extract message keys from status items
        message_keys = [
            (item['channel_id'], item['message_ts'])
            for item in status_items
            if 'channel_id' in item and 'message_ts' in item
        ]

        return await self.get_messages_with_user_reactions(
            user_id=user_id,
            message_keys=message_keys,
            emoji_names=acknowledgment_emojis,
        )

    async def get_reactions_for_messages_batch(
        self,
        message_ids: list[int],
    ) -> dict[int, list[Reaction]]:
        """Get reactions for multiple messages in one query.

        Args:
            message_ids: List of message database IDs.

        Returns:
            Dict mapping message_id to list of Reaction objects.
        """
        if not message_ids:
            return {}

        async with get_session() as session:
            stmt = select(Reaction).where(Reaction.message_id.in_(message_ids))
            result = await session.execute(stmt)
            reactions = result.scalars().all()

            # Group by message_id
            grouped: dict[int, list[Reaction]] = {mid: [] for mid in message_ids}
            for reaction in reactions:
                grouped[reaction.message_id].append(reaction)
            return grouped

    # Analysis queries

    async def get_recent_messages_for_analysis(
        self,
        user_id: str,
        since: datetime,
        limit: int = 100,
        include_own_messages: bool = True,
    ) -> list[dict[str, Any]]:
        """Get recent messages for LLM analysis without pre-filtering.

        Unlike get_status which pre-filters by message type and priority,
        this method returns ALL recent messages with full text for the LLM
        to analyze and categorize based on content.

        Args:
            user_id: The current user's ID (to identify own messages).
            since: Datetime to look back from.
            limit: Maximum number of messages to return.
            include_own_messages: Whether to include messages sent by the user.

        Returns:
            List of message dicts with channel context for LLM analysis.
        """
        async with get_session() as session:
            # Build query joining messages with channels for context
            stmt = (
                select(
                    Message.id,
                    Message.channel_id,
                    Message.ts,
                    Message.user_id,
                    Message.text,
                    Message.thread_ts,
                    Message.reply_count,
                    Message.created_at,
                    Channel.name.label('channel_name'),
                    Channel.channel_type,
                    Channel.is_self_dm,
                )
                .join(Channel, Message.channel_id == Channel.id)
                .where(
                    Message.created_at > since,
                    Channel.is_archived == False,  # noqa: E712
                )
                .order_by(Message.created_at.desc())
                .limit(limit)
            )

            # Optionally exclude user's own messages
            if not include_own_messages:
                stmt = stmt.where(Message.user_id != user_id)

            result = await session.execute(stmt)
            rows = result.all()

            messages = []
            for row in rows:
                # Determine if this is a DM
                is_dm = row.channel_type == 'im' and not row.is_self_dm

                # Check if user is mentioned
                is_mention = f'<@{user_id}>' in (row.text or '')

                # Determine metadata-based priority hint
                if is_mention:
                    metadata_priority = 'CRITICAL'
                elif is_dm:
                    metadata_priority = 'HIGH'
                elif row.thread_ts:
                    metadata_priority = 'MEDIUM'
                else:
                    metadata_priority = 'LOW'

                messages.append({
                    'id': f'{row.channel_id}:{row.ts}',
                    'db_id': row.id,
                    'channel_id': row.channel_id,
                    'channel': f'#{row.channel_name}' if row.channel_name else row.channel_id,
                    'channel_type': row.channel_type,
                    'user_id': row.user_id,
                    'is_own_message': row.user_id == user_id,
                    'is_mention': is_mention,
                    'is_dm': is_dm,
                    'is_self_dm': row.is_self_dm,
                    'text': row.text,
                    'thread_ts': row.thread_ts,
                    'timestamp': row.created_at.isoformat() if row.created_at else None,
                    'metadata_priority': metadata_priority,
                })

            return messages
