"""Initial schema migration.

Revision ID: 001_initial_schema
Revises:
Create Date: 2025-01-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create channels table
    op.create_table(
        'channels',
        sa.Column('id', sa.String(20), primary_key=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('channel_type', sa.String(20), nullable=False),
        sa.Column('is_archived', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('metadata', sa.dialects.postgresql.JSONB(), server_default='{}', nullable=False),
    )

    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.String(20), primary_key=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('real_name', sa.String(255), nullable=True),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('is_bot', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('metadata', sa.dialects.postgresql.JSONB(), server_default='{}', nullable=False),
    )

    # Create messages table
    op.create_table(
        'messages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('channel_id', sa.String(20), sa.ForeignKey('channels.id'), nullable=False),
        sa.Column('ts', sa.String(20), nullable=False),
        sa.Column('user_id', sa.String(20), nullable=True),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('thread_ts', sa.String(20), nullable=True),
        sa.Column('reply_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('is_edited', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('message_type', sa.String(50), server_default='message', nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('metadata', sa.dialects.postgresql.JSONB(), server_default='{}', nullable=False),
    )

    # Create unique constraint and indexes for messages
    op.create_index('idx_messages_channel_ts', 'messages', ['channel_id', 'ts'], unique=True)
    op.create_index(
        'idx_messages_thread',
        'messages',
        ['channel_id', 'thread_ts'],
        postgresql_where=sa.text('thread_ts IS NOT NULL'),
    )
    op.create_index('idx_messages_user', 'messages', ['user_id'])
    op.create_index('idx_messages_created', 'messages', ['created_at'])

    # Create reactions table
    op.create_table(
        'reactions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('message_id', sa.Integer(), sa.ForeignKey('messages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('user_id', sa.String(20), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Create indexes for reactions
    op.create_index('idx_reactions_unique', 'reactions', ['message_id', 'name', 'user_id'], unique=True)
    op.create_index('idx_reactions_message', 'reactions', ['message_id'])
    op.create_index('idx_reactions_user', 'reactions', ['user_id'])

    # Create message_embeddings table
    op.create_table(
        'message_embeddings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'message_id', sa.Integer(), sa.ForeignKey('messages.id', ondelete='CASCADE'), nullable=False, unique=True
        ),
        sa.Column('embedding', Vector(1536), nullable=True),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Create sync_state table
    op.create_table(
        'sync_state',
        sa.Column('channel_id', sa.String(20), sa.ForeignKey('channels.id'), primary_key=True),
        sa.Column('last_ts', sa.String(20), nullable=True),
        sa.Column('last_sync_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Create reminders table
    op.create_table(
        'reminders',
        sa.Column('id', sa.String(20), primary_key=True),
        sa.Column('user_id', sa.String(20), nullable=False),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('time', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('complete_ts', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('recurring', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('metadata', sa.dialects.postgresql.JSONB(), server_default='{}', nullable=False),
    )


def downgrade() -> None:
    op.drop_table('reminders')
    op.drop_table('sync_state')
    op.drop_table('message_embeddings')
    op.drop_index('idx_reactions_user', table_name='reactions')
    op.drop_index('idx_reactions_message', table_name='reactions')
    op.drop_index('idx_reactions_unique', table_name='reactions')
    op.drop_table('reactions')
    op.drop_index('idx_messages_created', table_name='messages')
    op.drop_index('idx_messages_user', table_name='messages')
    op.drop_index('idx_messages_thread', table_name='messages')
    op.drop_index('idx_messages_channel_ts', table_name='messages')
    op.drop_table('messages')
    op.drop_table('users')
    op.drop_table('channels')
