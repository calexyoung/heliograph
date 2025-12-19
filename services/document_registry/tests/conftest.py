"""Pytest fixtures for Document Registry tests."""

import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from services.document_registry.app.db.models import Base, DocumentModel, ProvenanceModel
from services.document_registry.app.main import app
from services.document_registry.app.dependencies import get_db, get_sqs_client
from services.document_registry.app.config import Settings, get_settings
from shared.schemas.document import DocumentStatus


# Patch JSONB to JSON for SQLite compatibility in tests
# This must happen before tables are created
def _patch_jsonb_for_sqlite():
    """Replace JSONB columns with JSON for SQLite compatibility."""
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db_engine():
    """Create in-memory SQLite database engine for testing."""
    # Patch JSONB to JSON for SQLite
    _patch_jsonb_for_sqlite()

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create database session for testing."""
    session_factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session


@pytest.fixture
def mock_sqs_client():
    """Create mock SQS client for testing."""
    mock = MagicMock()
    mock.send_message = AsyncMock(return_value="test-message-id-123")
    mock.queue_url = "http://test/queue"
    return mock


@pytest.fixture
def test_settings():
    """Create test settings."""
    return Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        sqs_queue_url="http://test/queue",
        sqs_endpoint_url=None,
        rate_limit_enabled=False,  # Disable rate limiting in tests
    )


@pytest.fixture
async def test_client(db_engine, mock_sqs_client, test_settings) -> AsyncGenerator[AsyncClient, None]:
    """Create test client with mocked dependencies."""
    session_factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def override_get_sqs_client():
        return mock_sqs_client

    def override_get_settings():
        return test_settings

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_sqs_client] = override_get_sqs_client
    app.dependency_overrides[get_settings] = override_get_settings

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Test-Bypass-RateLimit": "true"},  # Bypass rate limiting in tests
    ) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def sample_document_data() -> dict:
    """Sample document data for testing."""
    return {
        "document_id": uuid4(),
        "doi": "10.1234/test.2024.001",
        "content_hash": "a" * 64,
        "title": "Test Document Title: A Study of Something",
        "title_normalized": "test document title a study of something",
        "authors": [
            {"given_name": "John", "family_name": "Doe"},
            {"given_name": "Jane", "family_name": "Smith"},
        ],
        "journal": "Journal of Testing",
        "year": 2024,
        "source_metadata": {"source": "test"},
        "status": DocumentStatus.REGISTERED,
    }


@pytest.fixture
async def existing_document(
    db_session: AsyncSession,
    sample_document_data: dict,
) -> DocumentModel:
    """Create an existing document in the database."""
    document = DocumentModel(**sample_document_data)
    db_session.add(document)
    await db_session.flush()
    return document
