"""SQLAlchemy ORM models for Slack Assistant."""

from datetime import datetime
from typing import Any, Callable

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, func, text as sa_text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


class Channel(Base):
    """Slack channel/conversation."""

    __tablename__ = 'channels'

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False)  # public_channel, private_channel, mpim, im
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_self_dm: Mapped[bool] = mapped_column(Boolean, default=False)  # True if this is a DM to self
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    metadata_: Mapped[dict] = mapped_column('metadata', JSONB, default=dict)

    messages: Mapped[list['Message']] = relationship(back_populates='channel')
    sync_state: Mapped['SyncState | None'] = relationship(back_populates='channel', uselist=False)

    def get_display_name(self, user_resolver: Callable[[str], str] | None = None) -> str:
        """Get formatted display name based on channel type.

        Args:
            user_resolver: Optional function to resolve user IDs to names.
                          Required for proper IM channel formatting.

        Returns:
            Formatted channel name:
            - IM channels: "DM: @username" (if user_resolver provided)
            - MPIM channels: "Group DM: channel_name"
            - Regular channels: "#channel_name"
        """
        if self.channel_type == 'im':
            user_id = self.name
            if user_id and user_resolver:
                user_name = user_resolver(user_id)
                return f'DM: @{user_name}'
            return f'DM: {user_id or self.id}'

        elif self.channel_type == 'mpim':
            return f'Group DM: {self.name or self.id}'

        else:  # public_channel or private_channel
            return f'#{self.name or self.id}'


class User(Base):
    """Slack user cache."""

    __tablename__ = 'users'

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    real_name: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    metadata_: Mapped[dict] = mapped_column('metadata', JSONB, default=dict)

    @property
    def display_name_or_fallback(self) -> str:
        """Get best available display name.

        Priority: display_name > real_name > name > id
        """
        return self.display_name or self.real_name or self.name or self.id


class Message(Base):
    """Slack message."""

    __tablename__ = 'messages'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(20), ForeignKey('channels.id'), nullable=False)
    ts: Mapped[str] = mapped_column(String(20), nullable=False)  # Slack timestamp
    user_id: Mapped[str | None] = mapped_column(String(20))
    text: Mapped[str | None] = mapped_column(Text)
    thread_ts: Mapped[str | None] = mapped_column(String(20))  # Parent message ts if this is a reply
    reply_count: Mapped[int] = mapped_column(Integer, default=0)
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    message_type: Mapped[str] = mapped_column(String(50), default='message')
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    metadata_: Mapped[dict] = mapped_column('metadata', JSONB, default=dict)

    __table_args__ = (
        Index('idx_messages_channel_ts', 'channel_id', 'ts', unique=True),
        Index('idx_messages_thread', 'channel_id', 'thread_ts', postgresql_where=sa_text('thread_ts IS NOT NULL')),
        Index('idx_messages_user', 'user_id'),
        Index('idx_messages_created', 'created_at'),
    )

    channel: Mapped['Channel'] = relationship(back_populates='messages')
    reactions: Mapped[list['Reaction']] = relationship(back_populates='message', cascade='all, delete-orphan')
    embedding: Mapped['MessageEmbedding | None'] = relationship(
        back_populates='message', uselist=False, cascade='all, delete-orphan'
    )

    @property
    def is_thread_reply(self) -> bool:
        """Check if message is a reply in a thread."""
        return self.thread_ts is not None and self.thread_ts != self.ts

    @property
    def is_thread_parent(self) -> bool:
        """Check if message is the parent of a thread."""
        return self.reply_count > 0

    @classmethod
    def from_slack(cls, channel_id: str, msg: dict[str, Any]) -> 'Message':
        """Create Message from Slack API response."""
        ts = msg.get('ts', '')
        created_at = None
        if ts:
            try:
                created_at = datetime.fromtimestamp(float(ts))
            except (ValueError, TypeError):
                pass

        return cls(
            channel_id=channel_id,
            ts=ts,
            user_id=msg.get('user'),
            text=msg.get('text'),
            thread_ts=msg.get('thread_ts'),
            reply_count=msg.get('reply_count', 0),
            is_edited='edited' in msg,
            message_type=msg.get('type', 'message'),
            created_at=created_at,
            metadata_={
                k: v
                for k, v in msg.items()
                if k not in ('ts', 'user', 'text', 'thread_ts', 'reply_count', 'type', 'edited')
            },
        )


class Reaction(Base):
    """Reaction on a message."""

    __tablename__ = 'reactions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(Integer, ForeignKey('messages.id', ondelete='CASCADE'), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # Emoji name without colons
    user_id: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('idx_reactions_unique', 'message_id', 'name', 'user_id', unique=True),
        Index('idx_reactions_message', 'message_id'),
        Index('idx_reactions_user', 'user_id'),
    )

    message: Mapped['Message'] = relationship(back_populates='reactions')


class MessageEmbedding(Base):
    """Vector embedding for a message."""

    __tablename__ = 'message_embeddings'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('messages.id', ondelete='CASCADE'), unique=True, nullable=False
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384))  # all-MiniLM-L6-v2 dimension
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    message: Mapped['Message'] = relationship(back_populates='embedding')


class SyncState(Base):
    """Sync state for a channel."""

    __tablename__ = 'sync_state'

    channel_id: Mapped[str] = mapped_column(String(20), ForeignKey('channels.id'), primary_key=True)
    last_ts: Mapped[str | None] = mapped_column(String(20))  # Last synced message timestamp
    last_sync_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    channel: Mapped['Channel'] = relationship(back_populates='sync_state')


class Reminder(Base):
    """Slack reminder."""

    __tablename__ = 'reminders'

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    complete_ts: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    metadata_: Mapped[dict] = mapped_column('metadata', JSONB, default=dict)
