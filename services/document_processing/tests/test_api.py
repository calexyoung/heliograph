"""Tests for API endpoints."""

import pytest
from unittest.mock import AsyncMock, patch


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Test basic health check."""
        response = await client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "document-processing"

    @pytest.mark.asyncio
    async def test_liveness_check(self, client):
        """Test liveness check."""
        response = await client.get("/api/v1/health/live")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"


class TestProcessingEndpoints:
    """Tests for processing endpoints."""

    @pytest.mark.asyncio
    async def test_list_jobs_empty(self, client, test_session):
        """Test listing jobs when empty."""
        response = await client.get("/api/v1/processing/jobs")

        assert response.status_code == 200
        data = response.json()
        assert data == []

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, client):
        """Test getting non-existent job."""
        response = await client.get(
            "/api/v1/processing/jobs/00000000-0000-0000-0000-000000000000"
        )

        assert response.status_code == 404


class TestChunkEndpoints:
    """Tests for chunk endpoints."""

    @pytest.mark.asyncio
    async def test_get_document_chunks_empty(self, client):
        """Test getting chunks for document with no chunks."""
        response = await client.get(
            "/api/v1/chunks/document/00000000-0000-0000-0000-000000000000"
        )

        assert response.status_code == 200
        data = response.json()
        assert data == []

    @pytest.mark.asyncio
    async def test_get_chunk_not_found(self, client):
        """Test getting non-existent chunk."""
        response = await client.get(
            "/api/v1/chunks/00000000-0000-0000-0000-000000000000"
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_search_chunks(self, client):
        """Test chunk search endpoint."""
        with patch(
            "services.document_processing.app.api.deps.get_embedding_generator"
        ) as mock_gen, patch(
            "services.document_processing.app.api.deps.get_qdrant_client"
        ) as mock_qdrant:
            # Mock embedding generator
            mock_generator = AsyncMock()
            mock_generator.generate_single = AsyncMock(return_value=[0.1] * 384)
            mock_gen.return_value = mock_generator

            # Mock Qdrant client
            mock_qdrant_client = AsyncMock()
            mock_qdrant_client.search = AsyncMock(return_value=[])
            mock_qdrant.return_value = mock_qdrant_client

            response = await client.post(
                "/api/v1/chunks/search",
                params={"query": "solar flares"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "results" in data
            assert "count" in data
