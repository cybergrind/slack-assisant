"""Slack polling daemon for syncing messages and reactions."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from slack_assistant.config import get_config
from slack_assistant.db.models import Channel, Message, SyncState, User
from slack_assistant.db.repository import Repository
from slack_assistant.slack.client import SlackClient


logger = logging.getLogger(__name__)


@dataclass
class ChannelSyncInfo:
    """Information about a channel for smart sync decisions."""

    channel: Channel
    conv_data: dict[str, Any]
    sync_state: SyncState | None
    latest_ts: str | None  # Latest message ts from Slack API
    has_new_messages: bool  # Whether there are new messages to sync
    priority: int  # Lower = higher priority (DMs first)


class SlackPoller:
    """Background poller that syncs Slack data to the database."""

    def __init__(
        self,
        client: SlackClient,
        repository: Repository,
        poll_interval: int | None = None,
    ):
        self.client = client
        self.repository = repository
        self.poll_interval = poll_interval or get_config().poll_interval_seconds
        self._running = False
        self._channels: dict[str, dict[str, Any]] = {}

    async def start(self) -> None:
        """Start the polling loop."""
        if not self.client.user_id:
            if not await self.client.authenticate():
                raise RuntimeError('Failed to authenticate with Slack')

        self._running = True
        logger.info(f'Starting poller (interval: {self.poll_interval}s)')

        # Initial sync - fetch metadata and persist to DB
        await self._refresh_channel_metadata()
        await self._sync_channels_to_db()
        await self._sync_all_messages()

        # Main polling loop
        poll_count = 0
        while self._running:
            try:
                await asyncio.sleep(self.poll_interval)
                poll_count += 1
                logger.debug(f'Poll #{poll_count}')

                # Always refresh metadata (fast, just updates _channels dict)
                # This ensures smart sync has fresh 'latest' timestamps
                await self._refresh_channel_metadata()

                # Persist channel changes to DB less frequently
                if poll_count % 10 == 0:
                    await self._sync_channels_to_db()

                # Smart sync now uses FRESH metadata
                await self._sync_all_messages()

            except asyncio.CancelledError:
                logger.info('Poller cancelled')
                break
            except Exception as e:
                logger.exception(f'Error in polling loop: {e}')
                await asyncio.sleep(5)  # Brief pause before retrying

    def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        logger.info('Poller stopping...')

    async def _refresh_channel_metadata(self) -> None:
        """Fetch fresh channel metadata from Slack (lightweight, every poll).

        This updates the _channels cache with the latest conversation data
        including the 'latest' field which contains the most recent message
        timestamp. This is essential for smart sync to detect new messages.
        """
        conversations = await self.client.get_conversations()
        for conv in conversations:
            self._channels[conv['id']] = conv
        logger.debug(f'Refreshed metadata for {len(conversations)} channels')

    async def _sync_channels_to_db(self) -> None:
        """Persist channel changes to database (full sync, less frequent).

        This writes channel information to the database, which is needed for
        new channels to appear in queries. Run less frequently since channel
        metadata (name, archived status) changes rarely.
        """
        for channel_id, conv in self._channels.items():
            channel_type = self._get_channel_type(conv)

            # Detect self-DM: IM channel where the other user is self
            is_self_dm = channel_type == 'im' and conv.get('user') == self.client.user_id

            channel = Channel(
                id=conv['id'],
                name=conv.get('name') or conv.get('user'),
                channel_type=channel_type,
                is_archived=conv.get('is_archived', False),
                is_self_dm=is_self_dm,
                created_at=datetime.fromtimestamp(conv['created']) if conv.get('created') else None,
                metadata_={k: v for k, v in conv.items() if k not in ('id', 'name', 'is_archived', 'created')},
            )
            await self.repository.upsert_channel(channel)

            if is_self_dm:
                logger.debug(f'Detected self-DM channel: {channel.id}')

        logger.info(f'Synced {len(self._channels)} channels to database')

    def _get_channel_type(self, conv: dict[str, Any]) -> str:
        """Determine channel type from conversation data."""
        if conv.get('is_im'):
            return 'im'
        if conv.get('is_mpim'):
            return 'mpim'
        if conv.get('is_private'):
            return 'private_channel'
        return 'public_channel'

    async def _sync_all_messages(self, max_concurrent: int = 10) -> None:
        """Sync messages from channels that have new activity.

        Uses smart sync to skip channels with no new messages by comparing
        the latest message timestamp from Slack API with our sync state.

        Args:
            max_concurrent: Maximum number of channels to sync concurrently.
        """
        # Build list of channels that need syncing
        channels_to_sync = await self._get_channels_needing_sync()

        if not channels_to_sync:
            logger.debug('No channels need syncing')
            return

        logger.info(f'Syncing {len(channels_to_sync)} channels with new activity')

        # Use semaphore to limit concurrent channel syncs
        semaphore = asyncio.Semaphore(max_concurrent)

        async def sync_with_semaphore(sync_info: ChannelSyncInfo) -> None:
            async with semaphore:
                await self._sync_channel_messages(sync_info.channel)

        # Run all channel syncs concurrently (semaphore limits parallelism)
        await asyncio.gather(
            *[sync_with_semaphore(info) for info in channels_to_sync],
            return_exceptions=True,
        )

    async def _get_channels_needing_sync(self) -> list[ChannelSyncInfo]:
        """Determine which channels have new messages to sync.

        Compares the latest message timestamp from cached conversation data
        with our sync state to skip channels with no new activity.

        Returns:
            List of ChannelSyncInfo for channels that need syncing,
            sorted by priority (DMs first, then by activity).
        """
        channels = await self.repository.get_all_channels()
        if not channels:
            return []

        # Batch fetch sync states
        sync_states = await self.repository.get_sync_states_batch([ch.id for ch in channels])

        channels_to_sync: list[ChannelSyncInfo] = []

        for channel in channels:
            conv_data = self._channels.get(channel.id, {})
            sync_state = sync_states.get(channel.id)

            # Get latest message ts from conversation metadata
            latest = conv_data.get('latest', {})
            latest_ts = latest.get('ts') if isinstance(latest, dict) else None

            # Determine if channel has new messages
            has_new = self._channel_has_new_messages(sync_state, latest_ts)

            # Assign priority (lower = higher priority)
            priority = self._get_channel_priority(channel, conv_data)

            if has_new:
                channels_to_sync.append(
                    ChannelSyncInfo(
                        channel=channel,
                        conv_data=conv_data,
                        sync_state=sync_state,
                        latest_ts=latest_ts,
                        has_new_messages=True,
                        priority=priority,
                    )
                )
            else:
                logger.debug(f'Skipping {channel.name or channel.id}: no new messages')

        # Sort by priority (DMs and active channels first)
        channels_to_sync.sort(key=lambda x: x.priority)

        return channels_to_sync

    def _channel_has_new_messages(self, sync_state: SyncState | None, latest_ts: str | None) -> bool:
        """Check if a channel has new messages since last sync.

        Args:
            sync_state: Our last sync state for this channel.
            latest_ts: Latest message timestamp from Slack API.

        Returns:
            True if channel needs syncing.
        """
        # No sync state = never synced, needs sync
        if sync_state is None or sync_state.last_ts is None:
            return True

        # No latest message info = can't determine, assume needs sync
        if latest_ts is None:
            return True

        # Compare timestamps (Slack ts format: "1234567890.123456")
        return latest_ts > sync_state.last_ts

    def _get_channel_priority(self, channel: Channel, conv_data: dict[str, Any]) -> int:
        """Get sync priority for a channel (lower = higher priority).

        Priority order:
        1. Self-DM (priority 0) - messages to yourself are urgent
        2. DMs (priority 1) - direct messages are high priority
        3. Group DMs (priority 2) - mpim
        4. Channels with unread (priority 3)
        5. Other channels (priority 10)

        Args:
            channel: Channel model.
            conv_data: Raw conversation data from Slack API.

        Returns:
            Priority value (lower = sync first).
        """
        if channel.is_self_dm:
            return 0
        if channel.channel_type == 'im':
            return 1
        if channel.channel_type == 'mpim':
            return 2

        # Check unread count (available in conv_data)
        unread = conv_data.get('unread_count', 0)
        if unread and unread > 0:
            return 3

        return 10

    async def _get_channel_display_name(self, channel: Channel) -> str:
        """Get human-readable display name for a channel."""
        return await self.repository.get_channel_display_name(channel)

    async def _sync_channel_messages(self, channel: Channel) -> None:
        """Sync messages from a single channel."""
        # Get sync state
        sync_state = await self.repository.get_sync_state(channel.id)
        oldest = sync_state.last_ts if sync_state else None

        # Get human-readable channel name
        display_name = await self._get_channel_display_name(channel)
        logger.debug(f'Syncing {display_name}: oldest={oldest}')

        # Fetch new messages
        messages = await self.client.get_channel_history(channel.id, oldest=oldest)
        if not messages:
            logger.debug(f'No new messages in {display_name}')
            return

        # Messages are returned newest-first
        newest_ts = messages[0].get('ts')
        messages = list(reversed(messages))  # Process oldest first

        new_count = 0
        for msg_data in messages:
            msg = Message.from_slack(channel.id, msg_data)

            # Skip if we've already seen this exact timestamp
            if oldest and msg.ts <= oldest:
                continue

            # Store message
            message_id = await self.repository.upsert_message(msg)

            # Store reactions
            if reactions := msg_data.get('reactions'):
                await self.repository.upsert_reactions(message_id, reactions)

            # Sync thread replies if this is a thread parent
            if msg.reply_count > 0:
                await self._sync_thread_replies(channel.id, msg.ts)

            new_count += 1

            # Cache user info if not seen before
            if msg.user_id:
                await self._ensure_user_cached(msg.user_id)

        if new_count > 0:
            logger.info(f'Synced {new_count} new messages from {display_name}')

        # Update sync state
        if newest_ts:
            await self.repository.upsert_sync_state(SyncState(channel_id=channel.id, last_ts=newest_ts))

    async def _sync_thread_replies(self, channel_id: str, thread_ts: str) -> None:
        """Sync all messages in a thread including the parent.

        This ensures parent message reactions are captured during thread sync,
        since conversations.replies returns the parent with up-to-date reactions.
        """
        # include_parent=True (default) ensures we get parent with current reactions
        thread_messages = await self.client.get_thread_replies(channel_id, thread_ts, include_parent=True)

        for msg_data in thread_messages:
            msg = Message.from_slack(channel_id, msg_data)
            message_id = await self.repository.upsert_message(msg)

            if reactions := msg_data.get('reactions'):
                await self.repository.upsert_reactions(message_id, reactions)

            if msg.user_id:
                await self._ensure_user_cached(msg.user_id)

    async def _ensure_user_cached(self, user_id: str) -> None:
        """Ensure user info is cached in the database."""
        existing = await self.repository.get_user(user_id)
        if existing:
            return

        user_info = await self.client.get_user_info(user_id)
        if not user_info:
            return

        user = User(
            id=user_info['id'],
            name=user_info.get('name'),
            real_name=user_info.get('real_name'),
            display_name=user_info.get('profile', {}).get('display_name'),
            is_bot=user_info.get('is_bot', False),
            metadata_={k: v for k, v in user_info.items() if k not in ('id', 'name', 'real_name', 'is_bot')},
        )
        await self.repository.upsert_user(user)
