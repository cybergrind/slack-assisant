"""Entity resolution with caching for Slack formatting."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from slack_assistant.formatting.patterns import CollectedEntities


if TYPE_CHECKING:
    from slack_assistant.db.repository import Repository


@dataclass
class ResolvedContext:
    """Pre-resolved entity mappings for formatting."""

    users: dict[str, str] = field(default_factory=dict)  # user_id -> display_name
    channels: dict[str, str] = field(default_factory=dict)  # channel_id -> name

    def get_user_name(self, user_id: str) -> str:
        """Get resolved user name or fallback to ID."""
        return self.users.get(user_id, user_id)

    def get_channel_name(self, channel_id: str) -> str:
        """Get resolved channel name or fallback to ID."""
        return self.channels.get(channel_id, channel_id)


@dataclass
class _CacheEntry:
    """Internal cache entry with expiration."""

    value: str
    expires_at: datetime


class EntityResolver:
    """Batch resolver for Slack entities with caching.

    Resolves user IDs and channel IDs to display names using batch
    database queries. Maintains an in-memory cache with TTL.

    Usage:
        resolver = EntityResolver(repository)
        entities = collect_entities(text)
        context = await resolver.resolve(entities)
        # Use context for formatting
    """

    def __init__(
        self,
        repository: 'Repository',
        cache_ttl_seconds: int = 300,  # 5 minutes
    ):
        self.repository = repository
        self.cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._user_cache: dict[str, _CacheEntry] = {}
        self._channel_cache: dict[str, _CacheEntry] = {}

    async def resolve(self, entities: CollectedEntities) -> ResolvedContext:
        """Resolve all entities in batch, returning a context object.

        Args:
            entities: CollectedEntities with user_ids and channel_ids.

        Returns:
            ResolvedContext with mappings from IDs to names.
        """
        now = datetime.now()

        # Resolve users
        users: dict[str, str] = {}
        uncached_user_ids: list[str] = []

        for user_id in entities.user_ids:
            cached = self._user_cache.get(user_id)
            if cached and cached.expires_at > now:
                users[user_id] = cached.value
            else:
                uncached_user_ids.append(user_id)

        if uncached_user_ids:
            db_users = await self.repository.get_users_batch(uncached_user_ids)
            for user in db_users:
                name = user.display_name or user.real_name or user.name or user.id
                users[user.id] = name
                self._user_cache[user.id] = _CacheEntry(
                    value=name,
                    expires_at=now + self.cache_ttl,
                )

        # Add fallback for users not in DB
        for user_id in entities.user_ids:
            if user_id not in users:
                users[user_id] = user_id  # Fallback to ID

        # Resolve channels
        channels: dict[str, str] = {}
        uncached_channel_ids: list[str] = []

        for channel_id in entities.channel_ids:
            cached = self._channel_cache.get(channel_id)
            if cached and cached.expires_at > now:
                channels[channel_id] = cached.value
            else:
                uncached_channel_ids.append(channel_id)

        if uncached_channel_ids:
            db_channels = await self.repository.get_channels_batch(uncached_channel_ids)
            for channel in db_channels:
                name = channel.name or channel.id
                channels[channel.id] = name
                self._channel_cache[channel.id] = _CacheEntry(
                    value=name,
                    expires_at=now + self.cache_ttl,
                )

        # Add fallback for channels not in DB
        for channel_id in entities.channel_ids:
            if channel_id not in channels:
                channels[channel_id] = channel_id

        return ResolvedContext(users=users, channels=channels)

    def clear_cache(self) -> None:
        """Clear all cached entries."""
        self._user_cache.clear()
        self._channel_cache.clear()
