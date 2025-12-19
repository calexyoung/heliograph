"""Tests for API endpoints."""

import pytest
from unittest.mock import AsyncMock, patch

from services.ingestion.app.core.schemas import (
    SearchResponse,
    SearchResult,
    SourceStatus,
)
from services.ingestion.app.main import app
from services.ingestion.app.api import deps
from shared.schemas.author import AuthorSchema


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Test basic health check."""
        response = await client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "ingestion"

    @pytest.mark.asyncio
    async def test_liveness_check(self, client):
        """Test liveness check."""
        response = await client.get("/api/v1/health/live")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"


class TestSearchEndpoints:
    """Tests for search endpoints."""

    @pytest.fixture
    def mock_search_response(self):
        """Create mock search response."""
        return SearchResponse(
            query="solar physics",
            results=[
                SearchResult(
                    source="crossref",
                    external_id="10.1234/test",
                    title="Test Paper",
                    authors=[AuthorSchema(given_name="John", family_name="Smith")],
                    year=2024,
                    doi="10.1234/test",
                )
            ],
            total_results=1,
            sources_searched=["crossref"],
            source_statuses={
                "crossref": SourceStatus(
                    source="crossref",
                    success=True,
                    result_count=1,
                )
            },
        )

    @pytest.mark.asyncio
    async def test_search_post(self, client, mock_search_response):
        """Test POST search endpoint."""
        mock_orchestrator = AsyncMock()
        mock_orchestrator.search.return_value = mock_search_response

        app.dependency_overrides[deps.get_search_orchestrator] = lambda: mock_orchestrator

        try:
            response = await client.post(
                "/api/v1/search",
                json={
                    "query": "solar physics",
                    "limit": 10,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["query"] == "solar physics"
            assert len(data["results"]) == 1
        finally:
            app.dependency_overrides.pop(deps.get_search_orchestrator, None)

    @pytest.mark.asyncio
    async def test_search_get(self, client, mock_search_response):
        """Test GET search endpoint."""
        mock_orchestrator = AsyncMock()
        mock_orchestrator.search.return_value = mock_search_response

        app.dependency_overrides[deps.get_search_orchestrator] = lambda: mock_orchestrator

        try:
            response = await client.get(
                "/api/v1/search",
                params={"query": "solar physics", "limit": 10},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["query"] == "solar physics"
        finally:
            app.dependency_overrides.pop(deps.get_search_orchestrator, None)

    @pytest.mark.asyncio
    async def test_list_sources(self, client):
        """Test list sources endpoint."""
        response = await client.get("/api/v1/search/sources")

        assert response.status_code == 200
        data = response.json()
        assert "sources" in data
        assert len(data["sources"]) == 4

        source_names = [s["name"] for s in data["sources"]]
        assert "crossref" in source_names
        assert "semantic_scholar" in source_names
        assert "arxiv" in source_names
        assert "scixplorer" in source_names


class TestJobEndpoints:
    """Tests for job management endpoints."""

    @pytest.mark.asyncio
    async def test_list_jobs_empty(self, client, test_session):
        """Test listing jobs when empty."""
        response = await client.get("/api/v1/jobs")

        assert response.status_code == 200
        data = response.json()
        assert data == []

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, client):
        """Test getting non-existent job."""
        response = await client.get("/api/v1/jobs/nonexistent-id")

        assert response.status_code == 404


class TestUploadEndpoints:
    """Tests for upload endpoints."""

    @pytest.mark.asyncio
    async def test_check_existing_not_found(self, client):
        """Test checking for non-existent file."""
        mock_handler = AsyncMock()
        mock_handler.check_existing.return_value = None

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            response = await client.get(
                "/api/v1/upload/check-existing",
                params={"content_hash": "abc123"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["exists"] is False
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)

    @pytest.mark.asyncio
    async def test_check_existing_found(self, client):
        """Test checking for existing file."""
        mock_handler = AsyncMock()
        mock_handler.check_existing.return_value = "documents/doc-123/abc123.pdf"

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            response = await client.get(
                "/api/v1/upload/check-existing",
                params={"content_hash": "abc123"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["exists"] is True
            assert data["s3_key"] == "documents/doc-123/abc123.pdf"
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)


class TestImportEndpoints:
    """Tests for import endpoints."""

    @pytest.mark.asyncio
    async def test_import_requires_identifier(self, client):
        """Test import fails without identifier."""
        mock_manager = AsyncMock()

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.post(
                "/api/v1/import",
                json={},
            )

            assert response.status_code == 400
            assert "identifier required" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)
