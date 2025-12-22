"""Tests for external API connectors."""

import asyncio

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.ingestion.app.connectors.base import BaseConnector, RateLimiter
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
        assert result.year == 2024
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
        limiter = RateLimiter(rate=1.0, burst=5)

        assert limiter.tokens == 5

    @pytest.mark.asyncio
    async def test_rate_limiter_acquire(self):
        """Test rate limiter acquire."""
        limiter = RateLimiter(rate=10.0, burst=1)

        # First acquire should be instant
        await limiter.acquire()

        # Should have used the token
        assert limiter.tokens < 1

    @pytest.mark.asyncio
    async def test_rate_limiter_waits_when_no_tokens(self):
        """Test rate limiter waits when tokens exhausted."""
        limiter = RateLimiter(rate=100.0, burst=1)  # High rate for fast test

        # Use up the burst token
        await limiter.acquire()
        assert limiter.tokens < 1

        # Second acquire should wait briefly
        await limiter.acquire()
        # Should have waited and reset tokens


class TestBaseConnector:
    """Tests for base connector functionality."""

    @pytest.fixture
    def mock_connector(self):
        """Create a concrete connector for testing."""
        # Create a simple concrete implementation for testing
        class TestConnector(BaseConnector):
            SOURCE_NAME = "test"

            async def search(self, query, limit=10, **kwargs):
                return []

            async def get_paper(self, external_id):
                return None

        return TestConnector(base_url="https://api.example.com")

    @pytest.mark.asyncio
    async def test_get_client_creates_client(self, mock_connector):
        """Test get_client creates HTTP client."""
        client = await mock_connector.get_client()

        assert client is not None
        assert isinstance(client, httpx.AsyncClient)

        await mock_connector.close()

    @pytest.mark.asyncio
    async def test_get_client_reuses_client(self, mock_connector):
        """Test get_client reuses existing client."""
        client1 = await mock_connector.get_client()
        client2 = await mock_connector.get_client()

        assert client1 is client2

        await mock_connector.close()

    @pytest.mark.asyncio
    async def test_close_closes_client(self, mock_connector):
        """Test close properly closes client."""
        await mock_connector.get_client()
        await mock_connector.close()

        assert mock_connector._client is None

    @pytest.mark.asyncio
    async def test_close_safe_when_no_client(self, mock_connector):
        """Test close is safe when no client exists."""
        await mock_connector.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_request_makes_http_request(self, mock_connector):
        """Test _request makes HTTP request."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(mock_connector, "get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            response = await mock_connector._request(
                "GET", "/test", params={"q": "test"}
            )

            assert response == mock_response
            mock_client.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_method(self, mock_connector):
        """Test _get method."""
        mock_response = MagicMock()

        with patch.object(mock_connector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response

            response = await mock_connector._get("/test", params={"q": "test"})

            mock_req.assert_called_once_with(
                "GET", "/test", params={"q": "test"}, headers=None
            )

    @pytest.mark.asyncio
    async def test_post_method(self, mock_connector):
        """Test _post method."""
        mock_response = MagicMock()

        with patch.object(mock_connector, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response

            response = await mock_connector._post("/test", json={"data": "test"})

            mock_req.assert_called_once_with(
                "POST", "/test", json={"data": "test"}, headers=None
            )

    @pytest.mark.asyncio
    async def test_get_pdf_url(self, mock_connector):
        """Test get_pdf_url returns PDF URL from paper."""
        mock_paper = MagicMock()
        mock_paper.pdf_url = "https://example.com/paper.pdf"

        with patch.object(
            mock_connector, "get_paper", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_paper

            result = await mock_connector.get_pdf_url("test-id")

            assert result == "https://example.com/paper.pdf"

    @pytest.mark.asyncio
    async def test_get_pdf_url_returns_none_when_no_paper(self, mock_connector):
        """Test get_pdf_url returns None when paper not found."""
        with patch.object(
            mock_connector, "get_paper", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None

            result = await mock_connector.get_pdf_url("nonexistent")

            assert result is None


class TestCrossrefConnectorSearch:
    """Tests for Crossref search functionality."""

    @pytest.fixture
    def connector(self):
        """Create connector instance."""
        return CrossrefConnector(mailto="test@example.com")

    @pytest.mark.asyncio
    async def test_search_success(self, connector, sample_crossref_response):
        """Test successful search."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_crossref_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            results = await connector.search("solar physics", limit=10)

            assert len(results) == 1
            assert results[0].title == "Test Paper on Solar Physics"

    @pytest.mark.asyncio
    async def test_search_with_year_filter(self, connector):
        """Test search with year filter."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"items": []}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            await connector.search("test", year_from=2020, year_to=2024)

            call_args = mock_get.call_args
            params = call_args[1]["params"]
            assert "filter" in params
            assert "2020" in params["filter"]
            assert "2024" in params["filter"]

    @pytest.mark.asyncio
    async def test_search_error_returns_empty(self, connector):
        """Test search returns empty list on error."""
        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("API error")

            results = await connector.search("test")

            assert results == []

    @pytest.mark.asyncio
    async def test_get_paper_success(self, connector, sample_crossref_response):
        """Test get_paper success."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": sample_crossref_response["message"]["items"][0]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            result = await connector.get_paper("10.1234/test.2024.001")

            assert result is not None
            assert result.doi == "10.1234/test.2024.001"

    @pytest.mark.asyncio
    async def test_get_paper_normalizes_doi(self, connector):
        """Test get_paper normalizes DOI formats."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            # Test with https://doi.org/ prefix
            await connector.get_paper("https://doi.org/10.1234/test")
            call_args = mock_get.call_args
            assert "/works/10.1234/test" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_paper_error_returns_none(self, connector):
        """Test get_paper returns None on error."""
        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("Not found")

            result = await connector.get_paper("invalid-doi")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_citations_success(self, connector):
        """Test get_citations success."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {
                "items": [
                    {"DOI": "10.1234/citing.001"},
                    {"DOI": "10.1234/citing.002"},
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            citations = await connector.get_citations("10.1234/test")

            assert len(citations) == 2
            assert "10.1234/citing.001" in citations

    @pytest.mark.asyncio
    async def test_get_citations_error_returns_empty(self, connector):
        """Test get_citations returns empty on error."""
        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("Error")

            citations = await connector.get_citations("10.1234/test")

            assert citations == []

    @pytest.mark.asyncio
    async def test_get_headers(self, connector):
        """Test _get_headers returns correct headers."""
        headers = connector._get_headers()

        assert headers["Accept"] == "application/json"
        assert "User-Agent" in headers


class TestArxivConnectorSearch:
    """Tests for arXiv search functionality."""

    @pytest.fixture
    def connector(self):
        """Create connector instance."""
        return ArxivConnector()

    @pytest.mark.asyncio
    async def test_search_success(self, connector, sample_arxiv_response):
        """Test successful search."""
        mock_response = MagicMock()
        mock_response.text = "<feed></feed>"  # Minimal Atom feed
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            with patch("feedparser.parse") as mock_parse:
                mock_parse.return_value = sample_arxiv_response

                results = await connector.search("solar physics")

                assert len(results) == 1
                assert results[0].external_id == "2401.12345"

    @pytest.mark.asyncio
    async def test_search_with_categories(self, connector):
        """Test search with category filter."""
        mock_response = MagicMock()
        mock_response.text = "<feed></feed>"
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            with patch("feedparser.parse") as mock_parse:
                mock_parse.return_value = {"entries": []}

                await connector.search("test", categories=["astro-ph.SR"])

                call_args = mock_get.call_args
                params = call_args[1]["params"]
                assert "cat:astro-ph.SR" in params["search_query"]

    @pytest.mark.asyncio
    async def test_search_with_year_filter(self, connector, sample_arxiv_response):
        """Test search filters results by year."""
        mock_response = MagicMock()
        mock_response.text = "<feed></feed>"
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            with patch("feedparser.parse") as mock_parse:
                mock_parse.return_value = sample_arxiv_response

                # Filter should exclude 2024 paper
                results = await connector.search("test", year_from=2025)

                assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_error_returns_empty(self, connector):
        """Test search returns empty on error."""
        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("API error")

            results = await connector.search("test")

            assert results == []

    @pytest.mark.asyncio
    async def test_get_paper_success(self, connector, sample_arxiv_response):
        """Test get_paper success."""
        mock_response = MagicMock()
        mock_response.text = "<feed></feed>"
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            with patch("feedparser.parse") as mock_parse:
                mock_parse.return_value = sample_arxiv_response

                result = await connector.get_paper("2401.12345")

                assert result is not None
                assert result.external_id == "2401.12345"

    @pytest.mark.asyncio
    async def test_get_paper_normalizes_id(self, connector):
        """Test get_paper normalizes arXiv ID formats."""
        mock_response = MagicMock()
        mock_response.text = "<feed></feed>"
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            with patch("feedparser.parse") as mock_parse:
                mock_parse.return_value = {"entries": []}

                # Test with arXiv: prefix
                await connector.get_paper("arXiv:2401.12345")
                call_args = mock_get.call_args
                params = call_args[1]["params"]
                assert params["id_list"] == "2401.12345"

    @pytest.mark.asyncio
    async def test_get_paper_not_found(self, connector):
        """Test get_paper returns None when not found."""
        mock_response = MagicMock()
        mock_response.text = "<feed></feed>"
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            with patch("feedparser.parse") as mock_parse:
                mock_parse.return_value = {"entries": []}

                result = await connector.get_paper("nonexistent")

                assert result is None

    @pytest.mark.asyncio
    async def test_get_paper_error_returns_none(self, connector):
        """Test get_paper returns None on error."""
        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("Error")

            result = await connector.get_paper("2401.12345")

            assert result is None

    @pytest.mark.asyncio
    async def test_search_heliophysics(self, connector):
        """Test search_heliophysics uses correct categories."""
        with patch.object(connector, "search", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []

            await connector.search_heliophysics("solar flares", limit=20)

            mock_search.assert_called_once()
            call_args = mock_search.call_args
            assert call_args[1]["categories"] == connector.HELIO_CATEGORIES
            assert call_args[1]["limit"] == 20


class TestSemanticScholarConnectorSearch:
    """Tests for Semantic Scholar search functionality."""

    @pytest.fixture
    def connector(self):
        """Create connector instance."""
        return SemanticScholarConnector(api_key="test-key")

    @pytest.mark.asyncio
    async def test_get_headers_with_api_key(self, connector):
        """Test headers include API key."""
        headers = connector._get_headers()

        assert headers["x-api-key"] == "test-key"
        assert headers["Accept"] == "application/json"

    @pytest.mark.asyncio
    async def test_get_headers_without_api_key(self):
        """Test headers without API key."""
        connector = SemanticScholarConnector()
        headers = connector._get_headers()

        assert "x-api-key" not in headers

    @pytest.mark.asyncio
    async def test_search_success(self, connector, sample_semantic_scholar_response):
        """Test successful search."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_semantic_scholar_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            results = await connector.search("solar physics")

            assert len(results) == 1
            assert results[0].external_id == "abc123"

    @pytest.mark.asyncio
    async def test_search_with_year_filter(self, connector):
        """Test search with year filter."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            await connector.search("test", year_from=2020, year_to=2024)

            call_args = mock_get.call_args
            params = call_args[1]["params"]
            assert params["year"] == "2020-2024"

    @pytest.mark.asyncio
    async def test_search_error_returns_empty(self, connector):
        """Test search returns empty on error."""
        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("API error")

            results = await connector.search("test")

            assert results == []

    @pytest.mark.asyncio
    async def test_get_paper_with_doi(self, connector, sample_semantic_scholar_response):
        """Test get_paper with DOI."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_semantic_scholar_response["data"][0]
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            await connector.get_paper("10.1234/test")

            call_args = mock_get.call_args
            assert "DOI:10.1234/test" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_paper_with_arxiv_id(self, connector):
        """Test get_paper with arXiv ID."""
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            await connector.get_paper("2401.12345")

            call_args = mock_get.call_args
            assert "ARXIV:2401.12345" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_paper_error_returns_none(self, connector):
        """Test get_paper returns None on error."""
        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("Error")

            result = await connector.get_paper("abc123")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_citations_success(self, connector):
        """Test get_citations success."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"citingPaper": {"paperId": "cite1", "title": "Citing Paper 1"}},
                {"citingPaper": {"paperId": "cite2", "title": "Citing Paper 2"}},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            citations = await connector.get_citations("abc123")

            assert len(citations) == 2

    @pytest.mark.asyncio
    async def test_get_citations_error_returns_empty(self, connector):
        """Test get_citations returns empty on error."""
        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("Error")

            citations = await connector.get_citations("abc123")

            assert citations == []

    @pytest.mark.asyncio
    async def test_get_references_success(self, connector):
        """Test get_references success."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"citedPaper": {"paperId": "ref1", "title": "Referenced Paper 1"}},
                {"citedPaper": {"paperId": "ref2", "title": "Referenced Paper 2"}},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            references = await connector.get_references("abc123")

            assert len(references) == 2

    @pytest.mark.asyncio
    async def test_get_references_error_returns_empty(self, connector):
        """Test get_references returns empty on error."""
        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("Error")

            references = await connector.get_references("abc123")

            assert references == []


class TestSciXplorerConnectorSearch:
    """Tests for SciXplorer/ADS search functionality."""

    @pytest.fixture
    def connector(self):
        """Create connector instance."""
        return SciXplorerConnector(api_token="test-token")

    @pytest.mark.asyncio
    async def test_search_success(self, connector, sample_ads_response):
        """Test successful search."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_ads_response
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {}

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            results = await connector.search("solar physics")

            assert len(results) == 1
            assert results[0].external_id == "2024SoPh..299....1S"

    @pytest.mark.asyncio
    async def test_search_with_year_filter(self, connector):
        """Test search with year filter."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": {"docs": []}}
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {}

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            await connector.search("test", year_from=2020, year_to=2024)

            call_args = mock_get.call_args
            params = call_args[1]["params"]
            assert "year:[2020 TO 2024]" in params["q"]

    @pytest.mark.asyncio
    async def test_search_with_collection(self, connector):
        """Test search with collection filter."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": {"docs": []}}
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {}

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            await connector.search("test", collection="astronomy")

            call_args = mock_get.call_args
            params = call_args[1]["params"]
            assert "collection:astronomy" in params["q"]

    @pytest.mark.asyncio
    async def test_search_rate_limit_warning(self, connector):
        """Test search logs warning on low rate limit."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": {"docs": []}}
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {
            "X-RateLimit-Remaining": "50",
            "X-RateLimit-Reset": "3600",
        }

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            # Should not raise, just log warning
            results = await connector.search("test")

            assert results == []

    @pytest.mark.asyncio
    async def test_search_error_returns_empty(self, connector):
        """Test search returns empty on error."""
        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("API error")

            results = await connector.search("test")

            assert results == []

    @pytest.mark.asyncio
    async def test_get_paper_success(self, connector, sample_ads_response):
        """Test get_paper success."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_ads_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            result = await connector.get_paper("2024SoPh..299....1S")

            assert result is not None
            assert result.external_id == "2024SoPh..299....1S"

    @pytest.mark.asyncio
    async def test_get_paper_not_found(self, connector):
        """Test get_paper returns None when not found."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": {"docs": []}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            result = await connector.get_paper("nonexistent")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_paper_error_returns_none(self, connector):
        """Test get_paper returns None on error."""
        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("Error")

            result = await connector.get_paper("2024SoPh..299....1S")

            assert result is None

    @pytest.mark.asyncio
    async def test_search_heliophysics(self, connector):
        """Test search_heliophysics adds journal filter."""
        with patch.object(connector, "search", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []

            await connector.search_heliophysics("solar flares", limit=20)

            mock_search.assert_called_once()
            call_args = mock_search.call_args
            query = call_args[1]["query"]
            assert "bibstem:" in query
            assert "SoPh" in query

    @pytest.mark.asyncio
    async def test_get_citations_success(self, connector, sample_ads_response):
        """Test get_citations success."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_ads_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            citations = await connector.get_citations("2024SoPh..299....1S")

            assert len(citations) == 1

    @pytest.mark.asyncio
    async def test_get_citations_error_returns_empty(self, connector):
        """Test get_citations returns empty on error."""
        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("Error")

            citations = await connector.get_citations("2024SoPh..299....1S")

            assert citations == []

    @pytest.mark.asyncio
    async def test_get_references_success(self, connector, sample_ads_response):
        """Test get_references success."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_ads_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            references = await connector.get_references("2024SoPh..299....1S")

            assert len(references) == 1

    @pytest.mark.asyncio
    async def test_get_references_error_returns_empty(self, connector):
        """Test get_references returns empty on error."""
        with patch.object(connector, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("Error")

            references = await connector.get_references("2024SoPh..299....1S")

            assert references == []


class TestCrossrefParsing:
    """Additional tests for Crossref parsing edge cases."""

    @pytest.fixture
    def connector(self):
        """Create connector instance."""
        return CrossrefConnector()

    def test_parse_result_with_pdf_link(self, connector):
        """Test parsing result with PDF link."""
        item = {
            "DOI": "10.1234/test",
            "title": ["Test Paper"],
            "author": [],
            "link": [
                {"content-type": "application/pdf", "URL": "https://example.com/paper.pdf"}
            ],
        }

        result = connector._parse_result(item)

        assert result.pdf_url == "https://example.com/paper.pdf"

    def test_parse_result_without_title(self, connector):
        """Test parsing result without title."""
        item = {"DOI": "10.1234/test", "author": []}

        result = connector._parse_result(item)

        assert result.title == "Untitled"


class TestArxivParsing:
    """Additional tests for arXiv parsing edge cases."""

    @pytest.fixture
    def connector(self):
        """Create connector instance."""
        return ArxivConnector()

    def test_parse_result_constructs_pdf_url(self, connector):
        """Test PDF URL construction when not in links."""
        entry = {
            "id": "http://arxiv.org/abs/2401.12345v1",
            "title": "Test",
            "published": "2024-01-15T00:00:00Z",
            "summary": "Abstract",
            "authors": [],
            "links": [],
            "tags": [],
        }

        result = connector._parse_result(entry)

        assert result.pdf_url == "https://arxiv.org/pdf/2401.12345.pdf"

    def test_parse_author_single_word(self, connector):
        """Test parsing single-word author name."""
        author = connector._parse_author({"name": "Researcher"})

        assert author.family_name == "Researcher"
        assert author.given_name is None


class TestSciXplorerParsing:
    """Additional tests for SciXplorer parsing edge cases."""

    @pytest.fixture
    def connector(self):
        """Create connector instance."""
        return SciXplorerConnector(api_token="test")

    def test_parse_result_with_arxiv_pdf(self, connector):
        """Test parsing result uses arXiv PDF when no pub PDF."""
        doc = {
            "bibcode": "2024Test",
            "title": ["Test"],
            "author": [],
            "identifier": ["arXiv:2401.12345"],
            "esources": [],  # No PUB_PDF
        }

        result = connector._parse_result(doc)

        assert result.pdf_url == "https://arxiv.org/pdf/2401.12345.pdf"
        assert result.source_metadata["arxiv_id"] == "2401.12345"

    def test_parse_result_with_pub_pdf(self, connector):
        """Test parsing result with publisher PDF."""
        doc = {
            "bibcode": "2024Test",
            "title": ["Test"],
            "author": [],
            "esources": ["PUB_PDF"],
        }

        result = connector._parse_result(doc)

        assert "PUB_PDF" in result.pdf_url
