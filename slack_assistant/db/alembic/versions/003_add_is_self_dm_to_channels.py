"""Add is_self_dm column to channels table.

Revision ID: 003_add_is_self_dm
Revises: 002_embeddings_384
Create Date: 2026-01-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '003_add_is_self_dm'
down_revision: str | None = '002_embeddings_384'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('channels', sa.Column('is_self_dm', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('channels', 'is_self_dm')
