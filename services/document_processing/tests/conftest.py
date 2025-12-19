"""Test fixtures for document processing service."""

import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from services.document_processing.app.config import settings
from services.document_processing.app.core.models import Base
from services.document_processing.app.core.schemas import (
    ExtractedText,
    ParsedSection,
    SectionType,
)
from services.document_processing.app.main import app
from services.document_processing.app.api import deps


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
    async def override_get_db():
        yield test_session

    app.dependency_overrides[deps.get_db] = override_get_db

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def sample_extracted_text():
    """Sample extracted text from PDF."""
    return ExtractedText(
        full_text="This is a test document about solar physics. The abstract summarizes the key findings. The introduction provides background. The methods describe the approach. The results show the findings. The conclusion summarizes everything.",
        sections=[
            ParsedSection(
                section_type=SectionType.ABSTRACT,
                title="Abstract",
                text="The abstract summarizes the key findings about solar flares and their effects.",
                char_offset_start=0,
                char_offset_end=80,
            ),
            ParsedSection(
                section_type=SectionType.INTRODUCTION,
                title="Introduction",
                text="The introduction provides background on heliophysics research and solar phenomena.",
                char_offset_start=82,
                char_offset_end=170,
            ),
            ParsedSection(
                section_type=SectionType.METHODS,
                title="Methods",
                text="The methods describe the observational approach using SDO data and analysis techniques.",
                char_offset_start=172,
                char_offset_end=265,
            ),
            ParsedSection(
                section_type=SectionType.RESULTS,
                title="Results",
                text="The results show significant correlation between solar activity and geomagnetic storms.",
                char_offset_start=267,
                char_offset_end=360,
            ),
            ParsedSection(
                section_type=SectionType.CONCLUSION,
                title="Conclusion",
                text="The conclusion summarizes the findings and suggests future research directions.",
                char_offset_start=362,
                char_offset_end=445,
            ),
        ],
        references=[],
        page_count=10,
        metadata={"title": "Solar Flare Analysis"},
    )


@pytest.fixture
def mock_grobid_response():
    """Mock GROBID TEI XML response."""
    return """<?xml version="1.0" encoding="UTF-8"?>
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
        <teiHeader>
            <fileDesc>
                <titleStmt>
                    <title>Test Paper on Solar Physics</title>
                </titleStmt>
            </fileDesc>
        </teiHeader>
        <text>
            <abstract>
                <p>This is the abstract about solar phenomena.</p>
            </abstract>
            <body>
                <div>
                    <head>Introduction</head>
                    <p>This is the introduction section.</p>
                </div>
                <div>
                    <head>Methods</head>
                    <p>This is the methods section.</p>
                </div>
                <div>
                    <head>Results</head>
                    <p>This is the results section.</p>
                </div>
            </body>
        </text>
    </TEI>
    """
