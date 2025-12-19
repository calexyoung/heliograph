"""Semantic Scholar API connector."""

from typing import Any

from services.ingestion.app.connectors.base import BaseConnector
from services.ingestion.app.core.schemas import SearchResult
from shared.schemas.author import AuthorSchema
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class SemanticScholarConnector(BaseConnector):
    """Connector for Semantic Scholar API.

    https://api.semanticscholar.org/api-docs/graph
    """

    SOURCE_NAME = "semantic_scholar"

    # Fields to request from API
    PAPER_FIELDS = [
        "paperId",
        "externalIds",
        "title",
        "abstract",
        "year",
        "authors",
        "venue",
        "publicationVenue",
        "citationCount",
        "referenceCount",
        "isOpenAccess",
        "openAccessPdf",
    ]

    def __init__(
        self,
        base_url: str = "https://api.semanticscholar.org/graph/v1",
        api_key: str = "",
        rate_limit: float = 100.0,  # 100 requests per 5 minutes without key
    ):
        """Initialize Semantic Scholar connector.

        Args:
            base_url: API base URL
            api_key: API key (optional, for higher rate limits)
            rate_limit: Requests per second
        """
        super().__init__(base_url, rate_limit / 300)  # Convert to per-second
        self.api_key = api_key

    def _get_headers(self) -> dict:
        """Get request headers."""
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _parse_author(self, author_data: dict) -> AuthorSchema:
        """Parse author from Semantic Scholar format."""
        name_parts = author_data.get("name", "Unknown").split(" ", 1)
        return AuthorSchema(
            given_name=name_parts[0] if len(name_parts) > 1 else None,
            family_name=name_parts[-1],
        )

    def _parse_result(self, item: dict) -> SearchResult:
        """Parse Semantic Scholar paper to SearchResult."""
        # Extract authors
        authors = [
            self._parse_author(a)
            for a in item.get("authors", [])
        ]

        # Extract external IDs
        external_ids = item.get("externalIds", {})
        doi = external_ids.get("DOI")
        arxiv_id = external_ids.get("ArXiv")

        # Get PDF URL
        pdf_url = None
        if item.get("isOpenAccess") and item.get("openAccessPdf"):
            pdf_url = item["openAccessPdf"].get("url")

        # Build URL
        paper_id = item.get("paperId", "")
        url = f"https://www.semanticscholar.org/paper/{paper_id}" if paper_id else None

        # Get venue
        venue = item.get("venue") or ""
        if item.get("publicationVenue"):
            venue = item["publicationVenue"].get("name", venue)

        return SearchResult(
            source=self.SOURCE_NAME,
            external_id=paper_id,
            title=item.get("title", "Untitled"),
            authors=authors,
            year=item.get("year"),
            doi=doi,
            abstract=item.get("abstract"),
            journal=venue if venue else None,
            pdf_url=pdf_url,
            url=url,
            source_metadata={
                "arxiv_id": arxiv_id,
                "citation_count": item.get("citationCount"),
                "reference_count": item.get("referenceCount"),
                "is_open_access": item.get("isOpenAccess"),
            },
        )

    async def search(
        self,
        query: str,
        limit: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
        **kwargs,
    ) -> list[SearchResult]:
        """Search Semantic Scholar for papers.

        Args:
            query: Search query
            limit: Maximum results
            year_from: Filter by year (from)
            year_to: Filter by year (to)

        Returns:
            List of search results
        """
        params = {
            "query": query,
            "limit": min(limit, 100),
            "fields": ",".join(self.PAPER_FIELDS),
        }

        # Add year filter
        if year_from or year_to:
            year_filter = ""
            if year_from:
                year_filter = f"{year_from}-"
            if year_to:
                year_filter += str(year_to)
            params["year"] = year_filter

        try:
            response = await self._get(
                "/paper/search",
                params=params,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            data = response.json()

            papers = data.get("data", [])
            results = [self._parse_result(paper) for paper in papers]

            logger.info(
                "semantic_scholar_search",
                query=query,
                results=len(results),
            )

            return results

        except Exception as e:
            logger.error("semantic_scholar_search_error", query=query, error=str(e))
            return []

    async def get_paper(self, external_id: str) -> SearchResult | None:
        """Get paper by ID.

        Args:
            external_id: Paper ID, DOI, or arXiv ID

        Returns:
            Paper details or None
        """
        # Determine ID type and format
        if external_id.startswith("10."):
            paper_id = f"DOI:{external_id}"
        elif external_id.startswith("arXiv:"):
            paper_id = external_id
        elif "." in external_id and not "/" in external_id:
            paper_id = f"ARXIV:{external_id}"
        else:
            paper_id = external_id

        params = {"fields": ",".join(self.PAPER_FIELDS)}

        try:
            response = await self._get(
                f"/paper/{paper_id}",
                params=params,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            data = response.json()

            return self._parse_result(data)

        except Exception as e:
            logger.error("semantic_scholar_get_paper_error", id=external_id, error=str(e))
            return None

    async def get_citations(
        self,
        paper_id: str,
        limit: int = 100,
    ) -> list[SearchResult]:
        """Get papers that cite this paper.

        Args:
            paper_id: Paper ID
            limit: Maximum results

        Returns:
            List of citing papers
        """
        params = {
            "fields": ",".join(self.PAPER_FIELDS),
            "limit": min(limit, 1000),
        }

        try:
            response = await self._get(
                f"/paper/{paper_id}/citations",
                params=params,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            data = response.json()

            citations = data.get("data", [])
            return [
                self._parse_result(c.get("citingPaper", {}))
                for c in citations
                if c.get("citingPaper")
            ]

        except Exception as e:
            logger.error("semantic_scholar_citations_error", id=paper_id, error=str(e))
            return []

    async def get_references(
        self,
        paper_id: str,
        limit: int = 100,
    ) -> list[SearchResult]:
        """Get papers referenced by this paper.

        Args:
            paper_id: Paper ID
            limit: Maximum results

        Returns:
            List of referenced papers
        """
        params = {
            "fields": ",".join(self.PAPER_FIELDS),
            "limit": min(limit, 1000),
        }

        try:
            response = await self._get(
                f"/paper/{paper_id}/references",
                params=params,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            data = response.json()

            references = data.get("data", [])
            return [
                self._parse_result(r.get("citedPaper", {}))
                for r in references
                if r.get("citedPaper")
            ]

        except Exception as e:
            logger.error("semantic_scholar_references_error", id=paper_id, error=str(e))
            return []
