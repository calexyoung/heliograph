"""Dependency injection for Knowledge Extraction service."""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import get_settings
from ..graph.neo4j_client import Neo4jClient

settings = get_settings()

# Database engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
)

# Session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Neo4j client singleton
_neo4j_client: Neo4jClient | None = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_neo4j_client() -> Neo4jClient:
    """Get Neo4j client instance."""
    global _neo4j_client
    if _neo4j_client is None:
        _neo4j_client = Neo4jClient(settings)
        await _neo4j_client.connect()
    return _neo4j_client


async def close_neo4j_client() -> None:
    """Close Neo4j client."""
    global _neo4j_client
    if _neo4j_client is not None:
        await _neo4j_client.close()
        _neo4j_client = None
