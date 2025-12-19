"""Tests for external API connectors."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.ingestion.app.connectors.crossref import CrossrefConnector
from services.ingestion.app.connectors.semantic_scholar import SemanticScholarConnector
from services.ingestion.app.connectors.arxiv import ArxivConnector
from services.ingestion.app.connectors.scixplorer import SciXplorerConnector


class TestCrossrefConnector:
    """Tests for Crossref connector."""

    @pytest.fixture
    def connector(self):
        """Create connector instance."""
        return CrossrefConnector(mailto="test@example.com")

    @pytest.mark.asyncio
    async def test_parse_result(self, connector, sample_crossref_response):
        """Test parsing Crossref response."""
        item = sample_crossref_response["message"]["items"][0]
        result = connector._parse_result(item)

        assert result.source == "crossref"
        assert result.doi == "10.1234/test.2024.001"
        assert result.title == "Test Paper on Solar Physics"
        assert len(result.authors) == 2
        assert result.authors[0].family_name == "Smith"
        assert result.year == 2024
        assert result.journal == "Solar Physics"

    @pytest.mark.asyncio
    async def test_parse_author(self, connector):
        """Test author parsing."""
        author_data = {"given": "John", "family": "Smith", "ORCID": "0000-0001-2345-6789"}
        author = connector._parse_author(author_data)

        assert author.given_name == "John"
        assert author.family_name == "Smith"
        assert author.orcid == "0000-0001-2345-6789"

    @pytest.mark.asyncio
    async def test_get_params_with_mailto(self, connector):
        """Test mailto parameter is added."""
        params = connector._get_params({"query": "test"})

        assert params["query"] == "test"
        assert params["mailto"] == "test@example.com"


class TestSemanticScholarConnector:
    """Tests for Semantic Scholar connector."""

    @pytest.fixture
    def connector(self):
        """Create connector instance."""
        return SemanticScholarConnector()

    @pytest.mark.asyncio
    async def test_parse_result(self, connector, sample_semantic_scholar_response):
        """Test parsing Semantic Scholar response."""
        item = sample_semantic_scholar_response["data"][0]
        result = connector._parse_result(item)

        assert result.source == "semantic_scholar"
        assert result.external_id == "abc123"
        assert result.doi == "10.1234/test.2024.001"
        assert result.title == "Test Paper on Solar Physics"
        assert len(result.authors) == 2
        assert result.year == 2024
        assert result.pdf_url == "https://example.com/paper.pdf"
        assert result.source_metadata["arxiv_id"] == "2401.12345"
        assert result.source_metadata["citation_count"] == 10

    @pytest.mark.asyncio
    async def test_parse_author(self, connector):
        """Test author parsing."""
        author_data = {"name": "John Smith"}
        author = connector._parse_author(author_data)

        assert author.given_name == "John"
        assert author.family_name == "Smith"

    @pytest.mark.asyncio
    async def test_parse_author_single_name(self, connector):
        """Test author parsing with single name."""
        author_data = {"name": "Madonna"}
        author = connector._parse_author(author_data)

        assert author.given_name is None
        assert author.family_name == "Madonna"


class TestArxivConnector:
    """Tests for arXiv connector."""

    @pytest.fixture
    def connector(self):
        """Create connector instance."""
        return ArxivConnector()

    @pytest.mark.asyncio
    async def test_parse_arxiv_id(self, connector):
        """Test arXiv ID parsing."""
        # New format
        assert connector._parse_arxiv_id("http://arxiv.org/abs/2401.12345v1") == "2401.12345"

        # Old format
        assert connector._parse_arxiv_id("http://arxiv.org/abs/hep-ph/0001234v1") == "hep-ph/0001234"

    @pytest.mark.asyncio
    async def test_parse_result(self, connector, sample_arxiv_response):
        """Test parsing arXiv response."""
        entry = sample_arxiv_response["entries"][0]
        result = connector._parse_result(entry)

        assert result.source == "arxiv"
        assert result.external_id == "2401.12345"
        assert result.title == "Test Paper on Solar Physics"
        assert len(result.authors) == 2
        assert result.year == 2024
        assert result.pdf_url == "http://arxiv.org/pdf/2401.12345v1"
        assert "astro-ph.SR" in result.source_metadata["categories"]

    @pytest.mark.asyncio
    async def test_helio_categories(self, connector):
        """Test heliophysics categories are defined."""
        assert "astro-ph.SR" in connector.HELIO_CATEGORIES
        assert "physics.space-ph" in connector.HELIO_CATEGORIES


class TestSciXplorerConnector:
    """Tests for NASA ADS / SciXplorer connector."""

    @pytest.fixture
    def connector(self):
        """Create connector instance."""
        return SciXplorerConnector(api_token="test-token")

    @pytest.mark.asyncio
    async def test_parse_result(self, connector, sample_ads_response):
        """Test parsing ADS response."""
        doc = sample_ads_response["response"]["docs"][0]
        result = connector._parse_result(doc)

        assert result.source == "scixplorer"
        assert result.external_id == "2024SoPh..299....1S"
        assert result.doi == "10.1234/test.2024.001"
        assert result.title == "Test Paper on Solar Physics"
        assert len(result.authors) == 2
        assert result.authors[0].family_name == "Smith"
        assert result.year == "2024"
        assert result.journal == "Solar Physics"
        assert result.source_metadata["bibcode"] == "2024SoPh..299....1S"
        assert result.source_metadata["arxiv_id"] == "2401.12345"

    @pytest.mark.asyncio
    async def test_parse_author(self, connector):
        """Test author parsing from ADS format."""
        author = connector._parse_author("Smith, John M.")

        assert author.family_name == "Smith"
        assert author.given_name == "John M."

    @pytest.mark.asyncio
    async def test_get_headers_with_token(self, connector):
        """Test headers include auth token."""
        headers = connector._get_headers()

        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Accept"] == "application/json"

    @pytest.mark.asyncio
    async def test_get_headers_without_token(self):
        """Test headers without auth token."""
        connector = SciXplorerConnector(api_token="")
        headers = connector._get_headers()

        assert "Authorization" not in headers


class TestRateLimiter:
    """Tests for rate limiting."""

    @pytest.mark.asyncio
    async def test_rate_limiter_initial_tokens(self):
        """Test rate limiter starts with burst tokens."""
        from services.ingestion.app.connectors.base import RateLimiter

        limiter = RateLimiter(rate=1.0, burst=5)

        assert limiter.tokens == 5

    @pytest.mark.asyncio
    async def test_rate_limiter_acquire(self):
        """Test rate limiter acquire."""
        from services.ingestion.app.connectors.base import RateLimiter

        limiter = RateLimiter(rate=10.0, burst=1)

        # First acquire should be instant
        await limiter.acquire()

        # Should have used the token
        assert limiter.tokens < 1
