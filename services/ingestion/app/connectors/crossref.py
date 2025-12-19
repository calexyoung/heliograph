"""Crossref API connector."""

from typing import Any

from services.ingestion.app.connectors.base import BaseConnector
from services.ingestion.app.core.schemas import SearchResult
from shared.schemas.author import AuthorSchema
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class CrossrefConnector(BaseConnector):
    """Connector for Crossref API.

    https://api.crossref.org/swagger-ui/index.html
    """

    SOURCE_NAME = "crossref"

    def __init__(
        self,
        base_url: str = "https://api.crossref.org",
        mailto: str = "",
        rate_limit: float = 50.0,
    ):
        """Initialize Crossref connector.

        Args:
            base_url: API base URL
            mailto: Email for polite pool (higher rate limits)
            rate_limit: Requests per second
        """
        super().__init__(base_url, rate_limit)
        self.mailto = mailto

    def _get_headers(self) -> dict:
        """Get request headers."""
        headers = {
            "Accept": "application/json",
            "User-Agent": "HelioGraph/0.1.0 (https://heliograph.io; mailto:contact@heliograph.io)",
        }
        return headers

    def _get_params(self, params: dict | None = None) -> dict:
        """Add mailto parameter for polite pool."""
        result = params or {}
        if self.mailto:
            result["mailto"] = self.mailto
        return result

    def _parse_author(self, author_data: dict) -> AuthorSchema:
        """Parse author from Crossref format."""
        return AuthorSchema(
            given_name=author_data.get("given"),
            family_name=author_data.get("family", "Unknown"),
            orcid=author_data.get("ORCID"),
            affiliation=author_data.get("affiliation", [{}])[0].get("name") if author_data.get("affiliation") else None,
            sequence=author_data.get("sequence"),
        )

    def _parse_result(self, item: dict) -> SearchResult:
        """Parse Crossref work item to SearchResult."""
        # Extract title
        title = item.get("title", ["Untitled"])[0] if item.get("title") else "Untitled"

        # Extract authors
        authors = [
            self._parse_author(a)
            for a in item.get("author", [])
        ]

        # Extract year from published-print or published-online
        year = None
        for date_field in ["published-print", "published-online", "created"]:
            if date_field in item:
                date_parts = item[date_field].get("date-parts", [[None]])[0]
                if date_parts and date_parts[0]:
                    year = date_parts[0]
                    break

        # Extract PDF link
        pdf_url = None
        for link in item.get("link", []):
            if link.get("content-type") == "application/pdf":
                pdf_url = link.get("URL")
                break

        # Build URL
        doi = item.get("DOI")
        url = f"https://doi.org/{doi}" if doi else None

        return SearchResult(
            source=self.SOURCE_NAME,
            external_id=doi or item.get("URL", ""),
            title=title,
            authors=authors,
            year=year,
            doi=doi,
            abstract=item.get("abstract"),
            journal=item.get("container-title", [None])[0] if item.get("container-title") else None,
            pdf_url=pdf_url,
            url=url,
            source_metadata={
                "type": item.get("type"),
                "publisher": item.get("publisher"),
                "issn": item.get("ISSN"),
                "subject": item.get("subject"),
                "reference_count": item.get("reference-count"),
                "is_referenced_by_count": item.get("is-referenced-by-count"),
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
        """Search Crossref for works.

        Args:
            query: Search query
            limit: Maximum results
            year_from: Filter by year (from)
            year_to: Filter by year (to)

        Returns:
            List of search results
        """
        params = self._get_params({
            "query": query,
            "rows": min(limit, 100),
        })

        # Add date filter
        if year_from or year_to:
            from_date = f"{year_from}-01-01" if year_from else "*"
            to_date = f"{year_to}-12-31" if year_to else "*"
            params["filter"] = f"from-pub-date:{from_date},until-pub-date:{to_date}"

        try:
            response = await self._get("/works", params=params, headers=self._get_headers())
            response.raise_for_status()
            data = response.json()

            items = data.get("message", {}).get("items", [])
            results = [self._parse_result(item) for item in items]

            logger.info(
                "crossref_search",
                query=query,
                results=len(results),
            )

            return results

        except Exception as e:
            logger.error("crossref_search_error", query=query, error=str(e))
            return []

    async def get_paper(self, external_id: str) -> SearchResult | None:
        """Get paper by DOI.

        Args:
            external_id: DOI

        Returns:
            Paper details or None
        """
        # Normalize DOI
        doi = external_id.lower()
        if doi.startswith("https://doi.org/"):
            doi = doi[16:]
        elif doi.startswith("doi:"):
            doi = doi[4:]

        try:
            response = await self._get(
                f"/works/{doi}",
                params=self._get_params(),
                headers=self._get_headers(),
            )
            response.raise_for_status()
            data = response.json()

            item = data.get("message", {})
            if not item:
                return None

            return self._parse_result(item)

        except Exception as e:
            logger.error("crossref_get_paper_error", doi=doi, error=str(e))
            return None

    async def get_citations(self, doi: str, limit: int = 100) -> list[str]:
        """Get DOIs of papers that cite this paper.

        Args:
            doi: Paper DOI
            limit: Maximum citations

        Returns:
            List of citing DOIs
        """
        params = self._get_params({
            "filter": f"cites:{doi}",
            "rows": min(limit, 100),
            "select": "DOI",
        })

        try:
            response = await self._get("/works", params=params, headers=self._get_headers())
            response.raise_for_status()
            data = response.json()

            items = data.get("message", {}).get("items", [])
            return [item.get("DOI") for item in items if item.get("DOI")]

        except Exception as e:
            logger.error("crossref_citations_error", doi=doi, error=str(e))
            return []
