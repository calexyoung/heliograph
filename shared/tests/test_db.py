"""Tests for database session management utilities."""

import tempfile
import os

import pytest
from sqlalchemy import Column, Integer, String, text
from sqlalchemy.orm import declarative_base

import shared.utils.db as db_module
from shared.utils.db import (
    close_db,
    get_db_session,
    get_engine,
    get_session,
    get_session_factory,
    init_db,
)

# Create a test model (prefixed with underscore to avoid pytest collection)
_Base = declarative_base()


class _SampleModel(_Base):
    """Simple model for database operations testing."""

    __tablename__ = "sample_table"

    id = Column(Integer, primary_key=True)
    name = Column(String(100))


class TestInitDb:
    """Tests for init_db function."""

    def teardown_method(self):
        """Reset global state after each test."""
        db_module._engine = None
        db_module._session_factory = None

    def test_init_db_creates_engine(self):
        """Test that init_db creates an engine."""
        init_db("sqlite+aiosqlite:///:memory:")

        engine = get_engine()
        assert engine is not None
        assert "sqlite" in str(engine.url)

    def test_init_db_creates_session_factory(self):
        """Test that init_db creates a session factory."""
        init_db("sqlite+aiosqlite:///:memory:")

        factory = get_session_factory()
        assert factory is not None

    def test_init_db_with_echo(self):
        """Test init_db with echo parameter."""
        init_db("sqlite+aiosqlite:///:memory:", echo=True)

        engine = get_engine()
        assert engine.echo is True

    def test_init_db_with_echo_false(self):
        """Test init_db with echo=False (default)."""
        init_db("sqlite+aiosqlite:///:memory:", echo=False)

        engine = get_engine()
        assert engine.echo is False

    def test_init_db_reinitialize(self):
        """Test that init_db can be called again to reinitialize."""
        init_db("sqlite+aiosqlite:///:memory:")
        first_engine = get_engine()

        init_db("sqlite+aiosqlite:///:memory:")
        second_engine = get_engine()

        # Should be different engine instances
        assert first_engine is not second_engine


class TestGetEngine:
    """Tests for get_engine function."""

    def teardown_method(self):
        """Reset global state after each test."""
        db_module._engine = None
        db_module._session_factory = None

    def test_get_engine_not_initialized_raises(self):
        """Test that get_engine raises RuntimeError when not initialized."""
        with pytest.raises(RuntimeError) as exc_info:
            get_engine()

        assert "Database not initialized" in str(exc_info.value)
        assert "Call init_db()" in str(exc_info.value)

    def test_get_engine_after_init(self):
        """Test get_engine returns engine after initialization."""
        init_db("sqlite+aiosqlite:///:memory:")

        engine = get_engine()
        assert engine is not None


class TestGetSessionFactory:
    """Tests for get_session_factory function."""

    def teardown_method(self):
        """Reset global state after each test."""
        db_module._engine = None
        db_module._session_factory = None

    def test_get_session_factory_not_initialized_raises(self):
        """Test that get_session_factory raises RuntimeError when not initialized."""
        with pytest.raises(RuntimeError) as exc_info:
            get_session_factory()

        assert "Database not initialized" in str(exc_info.value)
        assert "Call init_db()" in str(exc_info.value)

    def test_get_session_factory_after_init(self):
        """Test get_session_factory returns factory after initialization."""
        init_db("sqlite+aiosqlite:///:memory:")

        factory = get_session_factory()
        assert factory is not None


class TestGetDbSession:
    """Tests for get_db_session context manager."""

    @pytest.fixture(autouse=True)
    async def setup_db(self, tmp_path):
        """Initialize database with file-based SQLite before each test."""
        db_path = tmp_path / "test.db"
        db_url = f"sqlite+aiosqlite:///{db_path}"
        init_db(db_url)

        # Create the test table
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(_Base.metadata.create_all)

        yield

        await close_db()

    @pytest.mark.asyncio
    async def test_get_db_session_returns_session(self):
        """Test that get_db_session yields a session."""
        async with get_db_session() as session:
            assert session is not None

    @pytest.mark.asyncio
    async def test_get_db_session_commits_on_success(self):
        """Test that session commits on successful exit."""
        async with get_db_session() as session:
            await session.execute(
                text("INSERT INTO sample_table (id, name) VALUES (1, 'test')")
            )

        # Verify data was committed by querying again
        async with get_db_session() as session:
            result = await session.execute(
                text("SELECT name FROM sample_table WHERE id = 1")
            )
            row = result.fetchone()
            assert row is not None
            assert row[0] == "test"

    @pytest.mark.asyncio
    async def test_get_db_session_rollback_on_exception(self):
        """Test that session rolls back on exception."""
        try:
            async with get_db_session() as session:
                await session.execute(
                    text("INSERT INTO sample_table (id, name) VALUES (2, 'rollback_test')")
                )
                raise ValueError("Simulated error")
        except ValueError:
            pass

        # Verify data was not committed
        async with get_db_session() as session:
            result = await session.execute(
                text("SELECT name FROM sample_table WHERE id = 2")
            )
            row = result.fetchone()
            assert row is None

    @pytest.mark.asyncio
    async def test_get_db_session_propagates_exception(self):
        """Test that exceptions are re-raised after rollback."""
        with pytest.raises(ValueError) as exc_info:
            async with get_db_session() as session:
                raise ValueError("Test error message")

        assert "Test error message" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_db_session_multiple_operations(self):
        """Test multiple operations in a single session."""
        async with get_db_session() as session:
            await session.execute(
                text("INSERT INTO sample_table (id, name) VALUES (10, 'first')")
            )
            await session.execute(
                text("INSERT INTO sample_table (id, name) VALUES (11, 'second')")
            )
            await session.execute(
                text("UPDATE sample_table SET name = 'updated' WHERE id = 10")
            )

        async with get_db_session() as session:
            result = await session.execute(
                text("SELECT name FROM sample_table WHERE id = 10")
            )
            assert result.fetchone()[0] == "updated"

            result = await session.execute(
                text("SELECT name FROM sample_table WHERE id = 11")
            )
            assert result.fetchone()[0] == "second"

    @pytest.mark.asyncio
    async def test_get_db_session_execute_query(self):
        """Test executing a simple query."""
        async with get_db_session() as session:
            result = await session.execute(text("SELECT 1 + 1"))
            assert result.fetchone()[0] == 2


class TestGetSession:
    """Tests for get_session alias."""

    def teardown_method(self):
        """Reset global state after each test."""
        db_module._engine = None
        db_module._session_factory = None

    def test_get_session_is_alias(self):
        """Test that get_session is an alias for get_db_session."""
        assert get_session is get_db_session

    @pytest.mark.asyncio
    async def test_get_session_works(self):
        """Test that get_session alias works correctly."""
        init_db("sqlite+aiosqlite:///:memory:")

        async with get_session() as session:
            result = await session.execute(text("SELECT 1"))
            assert result.fetchone()[0] == 1

        await close_db()


class TestCloseDb:
    """Tests for close_db function."""

    def teardown_method(self):
        """Reset global state after each test."""
        db_module._engine = None
        db_module._session_factory = None

    @pytest.mark.asyncio
    async def test_close_db_disposes_engine(self):
        """Test that close_db disposes the engine."""
        init_db("sqlite+aiosqlite:///:memory:")

        assert db_module._engine is not None
        assert db_module._session_factory is not None

        await close_db()

        assert db_module._engine is None
        assert db_module._session_factory is None

    @pytest.mark.asyncio
    async def test_close_db_when_not_initialized(self):
        """Test that close_db is safe to call when not initialized."""
        # Should not raise
        await close_db()

        assert db_module._engine is None
        assert db_module._session_factory is None

    @pytest.mark.asyncio
    async def test_close_db_then_reinitialize(self):
        """Test that database can be reinitialized after close."""
        init_db("sqlite+aiosqlite:///:memory:")
        await close_db()

        # Reinitialize
        init_db("sqlite+aiosqlite:///:memory:")

        async with get_db_session() as session:
            result = await session.execute(text("SELECT 1"))
            assert result.fetchone()[0] == 1

        await close_db()


class TestDatabaseIntegration:
    """Integration tests for database operations."""

    @pytest.fixture(autouse=True)
    async def setup_db(self, tmp_path):
        """Initialize database with file-based SQLite before each test."""
        db_path = tmp_path / "test_integration.db"
        db_url = f"sqlite+aiosqlite:///{db_path}"
        init_db(db_url)

        # Create the test table
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(_Base.metadata.create_all)

        yield

        await close_db()

    @pytest.mark.asyncio
    async def test_transaction_isolation(self):
        """Test that transactions are isolated."""
        # Insert data in one session
        async with get_db_session() as session:
            await session.execute(
                text("INSERT INTO sample_table (id, name) VALUES (100, 'isolated')")
            )

        # Read in another session
        async with get_db_session() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM sample_table WHERE id = 100")
            )
            assert result.fetchone()[0] == 1

    @pytest.mark.asyncio
    async def test_concurrent_sessions(self):
        """Test that multiple sessions can be created."""
        factory = get_session_factory()

        async with factory() as session1:
            async with factory() as session2:
                # Both sessions should work
                await session1.execute(text("SELECT 1"))
                await session2.execute(text("SELECT 2"))

    @pytest.mark.asyncio
    async def test_sequential_sessions(self):
        """Test behavior with sequential get_db_session calls."""
        # First session
        async with get_db_session() as session1:
            await session1.execute(
                text("INSERT INTO sample_table (id, name) VALUES (200, 'first')")
            )

        # Second session (after first completes)
        async with get_db_session() as session2:
            await session2.execute(
                text("INSERT INTO sample_table (id, name) VALUES (201, 'second')")
            )

        # Both should be committed
        async with get_db_session() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM sample_table WHERE id IN (200, 201)")
            )
            assert result.fetchone()[0] == 2

    @pytest.mark.asyncio
    async def test_session_autoflush_disabled(self):
        """Test that autoflush is disabled on sessions."""
        factory = get_session_factory()
        async with factory() as session:
            # autoflush should be False per init_db configuration
            assert session.autoflush is False

    @pytest.mark.asyncio
    async def test_delete_and_verify(self):
        """Test delete operations."""
        # Insert
        async with get_db_session() as session:
            await session.execute(
                text("INSERT INTO sample_table (id, name) VALUES (300, 'to_delete')")
            )

        # Delete
        async with get_db_session() as session:
            await session.execute(
                text("DELETE FROM sample_table WHERE id = 300")
            )

        # Verify deleted
        async with get_db_session() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM sample_table WHERE id = 300")
            )
            assert result.fetchone()[0] == 0

    @pytest.mark.asyncio
    async def test_update_and_verify(self):
        """Test update operations."""
        # Insert
        async with get_db_session() as session:
            await session.execute(
                text("INSERT INTO sample_table (id, name) VALUES (400, 'original')")
            )

        # Update
        async with get_db_session() as session:
            await session.execute(
                text("UPDATE sample_table SET name = 'modified' WHERE id = 400")
            )

        # Verify updated
        async with get_db_session() as session:
            result = await session.execute(
                text("SELECT name FROM sample_table WHERE id = 400")
            )
            assert result.fetchone()[0] == "modified"
