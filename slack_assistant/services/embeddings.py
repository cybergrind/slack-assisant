"""Embedding generation service for vector search."""

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from slack_assistant.config import get_config
from slack_assistant.db.connection import get_session
from slack_assistant.db.models import Message, MessageEmbedding
from slack_assistant.db.repository import Repository


logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for generating and storing message embeddings."""

    def __init__(self, repository: Repository, api_key: str | None = None):
        self.repository = repository
        self.api_key = api_key
        self.model = get_config().embedding_model

    async def generate_embedding(self, text: str) -> list[float] | None:
        """Generate embedding for text using configured model.

        This is a placeholder that returns None.
        In production, you would integrate with:
        - OpenAI's text-embedding-ada-002
        - Local models like sentence-transformers
        - Anthropic's embeddings (when available)
        """
        if not text or not text.strip():
            return None

        # TODO: Implement actual embedding generation
        # Example with OpenAI:
        # import openai
        # response = await openai.Embedding.acreate(
        #     input=text,
        #     model=self.model
        # )
        # return response['data'][0]['embedding']

        logger.warning('Embedding generation not implemented - returning None')
        return None

    async def embed_message(self, message_id: int, text: str) -> bool:
        """Generate and store embedding for a message."""
        embedding = await self.generate_embedding(text)
        if embedding is None:
            return False

        async with get_session() as session:
            stmt = insert(MessageEmbedding).values(
                message_id=message_id,
                embedding=embedding,
                model=self.model,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=['message_id'],
                set_={
                    'embedding': stmt.excluded.embedding,
                    'model': stmt.excluded.model,
                },
            )
            await session.execute(stmt)
            await session.commit()
        return True

    async def backfill_embeddings(self, limit: int = 100) -> int:
        """Generate embeddings for messages that don't have them yet."""
        async with get_session() as session:
            # Find messages without embeddings
            stmt = (
                select(Message.id, Message.text)
                .outerjoin(MessageEmbedding, Message.id == MessageEmbedding.message_id)
                .where(
                    MessageEmbedding.id.is_(None),
                    Message.text.isnot(None),
                    Message.text != '',
                )
                .order_by(Message.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.all()

        embedded_count = 0
        for msg_id, msg_text in rows:
            if await self.embed_message(msg_id, msg_text):
                embedded_count += 1

        logger.info(f'Generated embeddings for {embedded_count}/{len(rows)} messages')
        return embedded_count

    async def get_embedding_stats(self) -> dict[str, Any]:
        """Get statistics about embeddings."""
        async with get_session() as session:
            total_result = await session.execute(select(func.count()).select_from(Message))
            total_messages = total_result.scalar_one()

            embedded_result = await session.execute(select(func.count()).select_from(MessageEmbedding))
            embedded_messages = embedded_result.scalar_one()

        return {
            'total_messages': total_messages,
            'embedded_messages': embedded_messages,
            'coverage_pct': (embedded_messages / total_messages * 100) if total_messages > 0 else 0,
        }
