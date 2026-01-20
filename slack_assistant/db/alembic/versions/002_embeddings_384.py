"""Change embedding dimension from 1536 to 384.

Revision ID: 002_embeddings_384
Revises: 001_initial_schema
Create Date: 2026-01-20
"""

from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '002_embeddings_384'
down_revision: str | None = '001_initial_schema'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop existing embeddings (incompatible dimensions)
    op.execute('TRUNCATE TABLE message_embeddings')
    # Change vector dimension
    op.execute('ALTER TABLE message_embeddings ALTER COLUMN embedding TYPE vector(384)')


def downgrade() -> None:
    op.execute('TRUNCATE TABLE message_embeddings')
    op.execute('ALTER TABLE message_embeddings ALTER COLUMN embedding TYPE vector(1536)')
