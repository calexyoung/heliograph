"""Database session management with async SQLAlchemy."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Global engine and session factory
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(
    database_url: str,
    pool_size: int = 5,
    max_overflow: int = 10,
    echo: bool = False,
) -> None:
    """Initialize the database engine and session factory.

    Args:
        database_url: PostgreSQL connection URL (postgresql+asyncpg://...)
        pool_size: Number of connections to keep in pool
        max_overflow: Maximum overflow connections beyond pool_size
        echo: Whether to log SQL statements
    """
    global _engine, _session_factory

    _engine = create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        echo=echo,
        pool_pre_ping=True,  # Enable connection health checks
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


def get_engine() -> AsyncEngine:
    """Get the database engine."""
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get the session factory."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _session_factory


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session as an async context manager.

    Usage:
        async with get_db_session() as session:
            result = await session.execute(query)
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_db() -> None:
    """Close the database engine and all connections."""
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


# Alias for convenience
get_session = get_db_session
