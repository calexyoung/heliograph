"""Test fixtures for ingestion service."""

import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from services.ingestion.app.config import settings
from services.ingestion.app.core.models import Base
from services.ingestion.app.main import app
from services.ingestion.app.api import deps


# Test database URL
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def test_engine():
    """Create test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session."""
    async_session = sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session


@pytest_asyncio.fixture
async def client(test_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client."""
    # Override database dependency
    async def override_get_db():
        yield test_session

    app.dependency_overrides[deps.get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def mock_httpx_client():
    """Create mock HTTP client for external API calls."""
    mock = AsyncMock()
    mock.get = AsyncMock()
    mock.post = AsyncMock()
    return mock


@pytest.fixture
def sample_crossref_response():
    """Sample Crossref API response."""
    return {
        "message": {
            "items": [
                {
                    "DOI": "10.1234/test.2024.001",
                    "title": ["Test Paper on Solar Physics"],
                    "author": [
                        {"given": "John", "family": "Smith"},
                        {"given": "Jane", "family": "Doe"},
                    ],
                    "published-print": {"date-parts": [[2024, 1, 15]]},
                    "container-title": ["Solar Physics"],
                    "abstract": "This is a test abstract about solar phenomena.",
                    "type": "journal-article",
                    "publisher": "Test Publisher",
                }
            ]
        }
    }


@pytest.fixture
def sample_semantic_scholar_response():
    """Sample Semantic Scholar API response."""
    return {
        "data": [
            {
                "paperId": "abc123",
                "externalIds": {
                    "DOI": "10.1234/test.2024.001",
                    "ArXiv": "2401.12345",
                },
                "title": "Test Paper on Solar Physics",
                "abstract": "This is a test abstract about solar phenomena.",
                "year": 2024,
                "authors": [
                    {"name": "John Smith"},
                    {"name": "Jane Doe"},
                ],
                "venue": "Solar Physics",
                "citationCount": 10,
                "referenceCount": 25,
                "isOpenAccess": True,
                "openAccessPdf": {
                    "url": "https://example.com/paper.pdf"
                },
            }
        ]
    }


@pytest.fixture
def sample_arxiv_response():
    """Sample arXiv API response (Atom feed parsed)."""
    return {
        "entries": [
            {
                "id": "http://arxiv.org/abs/2401.12345v1",
                "title": "Test Paper on Solar Physics\n",
                "summary": "This is a test abstract about solar phenomena.\n",
                "published": "2024-01-15T00:00:00Z",
                "authors": [
                    {"name": "John Smith"},
                    {"name": "Jane Doe"},
                ],
                "links": [
                    {"href": "http://arxiv.org/abs/2401.12345v1"},
                    {"href": "http://arxiv.org/pdf/2401.12345v1", "type": "application/pdf"},
                ],
                "tags": [
                    {"term": "astro-ph.SR"},
                    {"term": "physics.space-ph"},
                ],
                "arxiv_primary_category": {"term": "astro-ph.SR"},
            }
        ]
    }


@pytest.fixture
def sample_ads_response():
    """Sample NASA ADS API response."""
    return {
        "response": {
            "docs": [
                {
                    "bibcode": "2024SoPh..299....1S",
                    "title": ["Test Paper on Solar Physics"],
                    "author": ["Smith, John", "Doe, Jane"],
                    "year": "2024",
                    "doi": ["10.1234/test.2024.001"],
                    "abstract": "This is a test abstract about solar phenomena.",
                    "pub": "Solar Physics",
                    "citation_count": 10,
                    "read_count": 100,
                    "esources": ["PUB_PDF", "ADS_PDF"],
                    "property": ["REFEREED", "ARTICLE"],
                    "identifier": ["arXiv:2401.12345"],
                }
            ]
        }
    }


@pytest.fixture
def sample_search_result():
    """Sample SearchResult object."""
    from services.ingestion.app.core.schemas import SearchResult
    from shared.schemas.author import AuthorSchema

    return SearchResult(
        source="crossref",
        external_id="10.1234/test.2024.001",
        title="Test Paper on Solar Physics",
        authors=[
            AuthorSchema(given_name="John", family_name="Smith"),
            AuthorSchema(given_name="Jane", family_name="Doe"),
        ],
        year=2024,
        doi="10.1234/test.2024.001",
        abstract="This is a test abstract about solar phenomena.",
        journal="Solar Physics",
        pdf_url="https://example.com/paper.pdf",
        url="https://doi.org/10.1234/test.2024.001",
    )
