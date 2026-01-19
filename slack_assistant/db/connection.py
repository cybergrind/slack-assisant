"""Async database connection using SQLAlchemy."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from slack_assistant.config import get_config


_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_async_url(url: str) -> str:
    """Convert database URL to async version if needed."""
    if url.startswith('postgresql://'):
        return url.replace('postgresql://', 'postgresql+asyncpg://', 1)
    return url


async def init_db(database_url: str | None = None) -> None:
    """Initialize the database engine and session factory."""
    global _engine, _session_factory

    if _engine is not None:
        return

    if database_url is None:
        config = get_config()
        database_url = config.database_url

    async_url = _get_async_url(database_url)
    _engine = create_async_engine(
        async_url,
        echo=False,
        pool_size=5,
        max_overflow=10,
    )
    _session_factory = async_sessionmaker(
        _engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )


async def close_db() -> None:
    """Close the database engine."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async session from the pool."""
    if _session_factory is None:
        await init_db()

    async with _session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_engine():
    """Get the database engine (for Alembic migrations)."""
    return _engine


# Backward compatibility aliases
async def get_pool():
    """Deprecated: Use init_db() instead."""
    await init_db()


async def close_pool():
    """Deprecated: Use close_db() instead."""
    await close_db()
