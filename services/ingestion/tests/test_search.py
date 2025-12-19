"""Tests for search orchestration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.ingestion.app.core.schemas import SearchRequest, SearchResult
from services.ingestion.app.services.search import SearchOrchestrator
from shared.schemas.author import AuthorSchema


class TestSearchOrchestrator:
    """Tests for search orchestration."""

    @pytest.fixture
    def mock_connectors(self):
        """Create mock connectors."""
        return {
            "crossref": AsyncMock(),
            "semantic_scholar": AsyncMock(),
            "arxiv": AsyncMock(),
            "scixplorer": AsyncMock(),
        }

    @pytest.fixture
    def orchestrator(self, mock_connectors):
        """Create orchestrator with mock connectors."""
        orchestrator = SearchOrchestrator()
        orchestrator.connectors = mock_connectors
        return orchestrator

    def create_search_result(
        self,
        source: str,
        doi: str | None = None,
        title: str = "Test Paper",
        arxiv_id: str | None = None,
    ) -> SearchResult:
        """Helper to create search results."""
        return SearchResult(
            source=source,
            external_id=doi or f"{source}-123",
            title=title,
            authors=[AuthorSchema(given_name="John", family_name="Smith")],
            year=2024,
            doi=doi,
            abstract="Test abstract",
            source_metadata={"arxiv_id": arxiv_id} if arxiv_id else {},
        )

    @pytest.mark.asyncio
    async def test_search_single_source(self, orchestrator, mock_connectors):
        """Test search with single source."""
        mock_connectors["crossref"].search.return_value = [
            self.create_search_result("crossref", doi="10.1234/test")
        ]

        request = SearchRequest(
            query="solar physics",
            sources=["crossref"],
            limit=10,
        )

        response = await orchestrator.search(request)

        assert len(response.results) == 1
        assert response.results[0].source == "crossref"
        assert "crossref" in response.sources_searched
        mock_connectors["crossref"].search.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_multiple_sources(self, orchestrator, mock_connectors):
        """Test search across multiple sources."""
        mock_connectors["crossref"].search.return_value = [
            self.create_search_result("crossref", doi="10.1234/test1")
        ]
        mock_connectors["semantic_scholar"].search.return_value = [
            self.create_search_result("semantic_scholar", doi="10.1234/test2")
        ]

        request = SearchRequest(
            query="solar physics",
            sources=["crossref", "semantic_scholar"],
            limit=10,
        )

        response = await orchestrator.search(request)

        assert len(response.results) == 2
        assert set(response.sources_searched) == {"crossref", "semantic_scholar"}

    @pytest.mark.asyncio
    async def test_deduplication_by_doi(self, orchestrator, mock_connectors):
        """Test deduplication of results with same DOI."""
        doi = "10.1234/duplicate"

        mock_connectors["crossref"].search.return_value = [
            self.create_search_result("crossref", doi=doi)
        ]
        mock_connectors["semantic_scholar"].search.return_value = [
            self.create_search_result("semantic_scholar", doi=doi)
        ]

        request = SearchRequest(
            query="test",
            sources=["crossref", "semantic_scholar"],
            limit=10,
        )

        response = await orchestrator.search(request)

        # Should be deduplicated to 1 result
        assert len(response.results) == 1
        assert response.results[0].doi == doi
        # Should track that it was found in multiple sources
        assert "sources_found" in response.results[0].source_metadata

    @pytest.mark.asyncio
    async def test_deduplication_by_arxiv(self, orchestrator, mock_connectors):
        """Test deduplication of results with same arXiv ID."""
        arxiv_id = "2401.12345"

        mock_connectors["arxiv"].search.return_value = [
            self.create_search_result("arxiv", arxiv_id=arxiv_id)
        ]
        mock_connectors["semantic_scholar"].search.return_value = [
            self.create_search_result("semantic_scholar", arxiv_id=arxiv_id)
        ]

        request = SearchRequest(
            query="test",
            sources=["arxiv", "semantic_scholar"],
            limit=10,
        )

        response = await orchestrator.search(request)

        # Should be deduplicated
        assert len(response.results) == 1

    @pytest.mark.asyncio
    async def test_source_error_handling(self, orchestrator, mock_connectors):
        """Test handling of source errors."""
        mock_connectors["crossref"].search.return_value = [
            self.create_search_result("crossref", doi="10.1234/test")
        ]
        mock_connectors["semantic_scholar"].search.side_effect = Exception("API Error")

        request = SearchRequest(
            query="test",
            sources=["crossref", "semantic_scholar"],
            limit=10,
        )

        response = await orchestrator.search(request)

        # Should still return results from working source
        assert len(response.results) == 1

        # Should report error in status
        assert response.source_statuses["semantic_scholar"].success is False
        assert "API Error" in response.source_statuses["semantic_scholar"].error

    @pytest.mark.asyncio
    async def test_normalize_title(self, orchestrator):
        """Test title normalization."""
        title1 = "Solar Physics: A Review"
        title2 = "solar physics  a review"

        normalized1 = orchestrator._normalize_title(title1)
        normalized2 = orchestrator._normalize_title(title2)

        assert normalized1 == normalized2

    @pytest.mark.asyncio
    async def test_merge_results(self, orchestrator):
        """Test merging of duplicate results."""
        result1 = SearchResult(
            source="crossref",
            external_id="10.1234/test",
            title="Test Paper",
            authors=[AuthorSchema(given_name="John", family_name="Smith")],
            year=2024,
            doi="10.1234/test",
            abstract=None,  # Missing abstract
        )

        result2 = SearchResult(
            source="semantic_scholar",
            external_id="ss-123",
            title="Test Paper",
            authors=[AuthorSchema(given_name="John", family_name="Smith")],
            year=2024,
            doi="10.1234/test",
            abstract="This is the abstract",  # Has abstract
            pdf_url="https://example.com/paper.pdf",
        )

        merged = orchestrator._merge_results([result1, result2])

        # Should have abstract from result2
        assert merged.abstract == "This is the abstract"
        # Should have PDF URL from result2
        assert merged.pdf_url == "https://example.com/paper.pdf"
        # Should track both sources
        assert "sources_found" in merged.source_metadata

    @pytest.mark.asyncio
    async def test_year_filtering(self, orchestrator, mock_connectors):
        """Test year range filtering is passed to connectors."""
        mock_connectors["crossref"].search.return_value = []

        request = SearchRequest(
            query="test",
            sources=["crossref"],
            year_from=2020,
            year_to=2024,
            limit=10,
        )

        await orchestrator.search(request)

        mock_connectors["crossref"].search.assert_called_once_with(
            query="test",
            limit=10,
            year_from=2020,
            year_to=2024,
        )

    @pytest.mark.asyncio
    async def test_empty_sources_uses_all_defaults(self, orchestrator):
        """Test that empty sources list uses all default sources."""
        request = SearchRequest(
            query="test",
            sources=[],  # Empty source list - should use all defaults
            limit=10,
        )

        response = await orchestrator.search(request)

        # Empty list means use all available sources (the 'or' fallback behavior)
        assert len(response.sources_searched) == len(orchestrator.connectors)
