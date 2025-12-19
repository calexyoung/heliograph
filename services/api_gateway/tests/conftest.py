"""Pytest fixtures for API Gateway tests."""

import asyncio
from typing import AsyncGenerator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from services.api_gateway.app.auth.models import Base, UserModel
from services.api_gateway.app.auth.password import hash_password


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create in-memory SQLite database session for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def test_user(db_session: AsyncSession) -> UserModel:
    """Create a test user."""
    user = UserModel(
        email="test@example.com",
        hashed_password=hash_password("testpassword123"),
        full_name="Test User",
        is_active=True,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def test_admin_user(db_session: AsyncSession) -> UserModel:
    """Create a test admin user."""
    user = UserModel(
        email="admin@example.com",
        hashed_password=hash_password("adminpassword123"),
        full_name="Admin User",
        is_active=True,
        is_superuser=True,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user
