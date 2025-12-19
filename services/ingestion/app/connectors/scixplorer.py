"""NASA ADS / SciXplorer API connector."""

from typing import Any

from services.ingestion.app.connectors.base import BaseConnector
from services.ingestion.app.core.schemas import SearchResult
from shared.schemas.author import AuthorSchema
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class SciXplorerConnector(BaseConnector):
    """Connector for NASA ADS / SciXplorer API.

    https://ui.adsabs.harvard.edu/help/api/
    """

    SOURCE_NAME = "scixplorer"

    # Fields to request
    SEARCH_FIELDS = [
        "bibcode",
        "title",
        "author",
        "year",
        "doi",
        "abstract",
        "pub",
        "citation_count",
        "read_count",
        "esources",
        "property",
        "identifier",
    ]

    def __init__(
        self,
        base_url: str = "https://api.adsabs.harvard.edu/v1",
        api_token: str = "",
        rate_limit: float = 5.0,  # ~5000 requests/day
    ):
        """Initialize SciXplorer connector.

        Args:
            base_url: API base URL
            api_token: ADS API token
            rate_limit: Requests per second
        """
        super().__init__(base_url, rate_limit)
        self.api_token = api_token

    def _get_headers(self) -> dict:
        """Get request headers."""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def _parse_author(self, author_str: str) -> AuthorSchema:
        """Parse author from ADS format (Last, First M.)."""
        parts = author_str.split(", ", 1)
        return AuthorSchema(
            family_name=parts[0] if parts else "Unknown",
            given_name=parts[1] if len(parts) > 1 else None,
        )

    def _parse_result(self, doc: dict) -> SearchResult:
        """Parse ADS document to SearchResult."""
        # Extract authors
        authors = [
            self._parse_author(a)
            for a in doc.get("author", [])
        ]

        # Get title (ADS returns list)
        title = doc.get("title", ["Untitled"])
        if isinstance(title, list):
            title = title[0] if title else "Untitled"

        # Get DOI (ADS returns list)
        doi = doc.get("doi", [None])
        if isinstance(doi, list):
            doi = doi[0] if doi else None

        # Get PDF URL from esources
        pdf_url = None
        esources = doc.get("esources", [])
        if "PUB_PDF" in esources or "EPRINT_PDF" in esources:
            bibcode = doc.get("bibcode", "")
            # Link through ADS resolver
            pdf_url = f"https://ui.adsabs.harvard.edu/link_gateway/{bibcode}/PUB_PDF"

        # Check for arXiv
        arxiv_id = None
        for identifier in doc.get("identifier", []):
            if identifier.startswith("arXiv:"):
                arxiv_id = identifier[6:]
                if not pdf_url:
                    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                break

        bibcode = doc.get("bibcode", "")

        return SearchResult(
            source=self.SOURCE_NAME,
            external_id=bibcode,
            title=title,
            authors=authors,
            year=doc.get("year"),
            doi=doi,
            abstract=doc.get("abstract"),
            journal=doc.get("pub"),
            pdf_url=pdf_url,
            url=f"https://ui.adsabs.harvard.edu/abs/{bibcode}/abstract" if bibcode else None,
            source_metadata={
                "bibcode": bibcode,
                "arxiv_id": arxiv_id,
                "citation_count": doc.get("citation_count"),
                "read_count": doc.get("read_count"),
                "properties": doc.get("property", []),
                "esources": esources,
            },
        )

    async def search(
        self,
        query: str,
        limit: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
        collection: str | None = None,
        **kwargs,
    ) -> list[SearchResult]:
        """Search ADS for papers.

        Args:
            query: Search query (ADS query syntax)
            limit: Maximum results
            year_from: Filter by year (from)
            year_to: Filter by year (to)
            collection: ADS collection (astronomy, physics, etc.)

        Returns:
            List of search results
        """
        # Build query
        q_parts = [query]

        if year_from and year_to:
            q_parts.append(f"year:[{year_from} TO {year_to}]")
        elif year_from:
            q_parts.append(f"year:[{year_from} TO *]")
        elif year_to:
            q_parts.append(f"year:[* TO {year_to}]")

        if collection:
            q_parts.append(f"collection:{collection}")

        params = {
            "q": " ".join(q_parts),
            "fl": ",".join(self.SEARCH_FIELDS),
            "rows": min(limit, 200),
            "sort": "score desc",
        }

        try:
            response = await self._get(
                "/search/query",
                params=params,
                headers=self._get_headers(),
            )

            # Check rate limit headers
            remaining = response.headers.get("X-RateLimit-Remaining")
            if remaining and int(remaining) < 100:
                logger.warning(
                    "ads_rate_limit_low",
                    remaining=remaining,
                    reset=response.headers.get("X-RateLimit-Reset"),
                )

            response.raise_for_status()
            data = response.json()

            docs = data.get("response", {}).get("docs", [])
            results = [self._parse_result(doc) for doc in docs]

            logger.info(
                "scixplorer_search",
                query=query,
                results=len(results),
            )

            return results

        except Exception as e:
            logger.error("scixplorer_search_error", query=query, error=str(e))
            return []

    async def get_paper(self, external_id: str) -> SearchResult | None:
        """Get paper by bibcode.

        Args:
            external_id: ADS bibcode

        Returns:
            Paper details or None
        """
        params = {
            "q": f"bibcode:{external_id}",
            "fl": ",".join(self.SEARCH_FIELDS),
            "rows": 1,
        }

        try:
            response = await self._get(
                "/search/query",
                params=params,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            data = response.json()

            docs = data.get("response", {}).get("docs", [])
            if not docs:
                return None

            return self._parse_result(docs[0])

        except Exception as e:
            logger.error("scixplorer_get_paper_error", bibcode=external_id, error=str(e))
            return None

    async def search_heliophysics(
        self,
        query: str,
        limit: int = 10,
        **kwargs,
    ) -> list[SearchResult]:
        """Search ADS specifically for heliophysics papers.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of search results
        """
        # Add heliophysics-specific filters
        helio_query = f"({query}) AND (bibstem:(SoPh OR JGRA OR GeoRL OR SpWea OR ApJ OR A&A))"

        return await self.search(
            query=helio_query,
            limit=limit,
            **kwargs,
        )

    async def get_citations(self, bibcode: str, limit: int = 100) -> list[SearchResult]:
        """Get papers that cite this paper.

        Args:
            bibcode: ADS bibcode
            limit: Maximum results

        Returns:
            List of citing papers
        """
        params = {
            "q": f"citations(bibcode:{bibcode})",
            "fl": ",".join(self.SEARCH_FIELDS),
            "rows": min(limit, 200),
            "sort": "citation_count desc",
        }

        try:
            response = await self._get(
                "/search/query",
                params=params,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            data = response.json()

            docs = data.get("response", {}).get("docs", [])
            return [self._parse_result(doc) for doc in docs]

        except Exception as e:
            logger.error("scixplorer_citations_error", bibcode=bibcode, error=str(e))
            return []

    async def get_references(self, bibcode: str, limit: int = 100) -> list[SearchResult]:
        """Get papers referenced by this paper.

        Args:
            bibcode: ADS bibcode
            limit: Maximum results

        Returns:
            List of referenced papers
        """
        params = {
            "q": f"references(bibcode:{bibcode})",
            "fl": ",".join(self.SEARCH_FIELDS),
            "rows": min(limit, 200),
        }

        try:
            response = await self._get(
                "/search/query",
                params=params,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            data = response.json()

            docs = data.get("response", {}).get("docs", [])
            return [self._parse_result(doc) for doc in docs]

        except Exception as e:
            logger.error("scixplorer_references_error", bibcode=bibcode, error=str(e))
            return []
