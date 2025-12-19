"""arXiv API connector."""

import re
from typing import Any
from xml.etree import ElementTree

import feedparser

from services.ingestion.app.connectors.base import BaseConnector
from services.ingestion.app.core.schemas import SearchResult
from shared.schemas.author import AuthorSchema
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class ArxivConnector(BaseConnector):
    """Connector for arXiv API.

    https://arxiv.org/help/api/user-manual
    """

    SOURCE_NAME = "arxiv"

    # arXiv categories relevant to heliophysics
    HELIO_CATEGORIES = [
        "astro-ph.SR",  # Solar and Stellar Astrophysics
        "astro-ph.EP",  # Earth and Planetary Astrophysics
        "astro-ph.HE",  # High Energy Astrophysical Phenomena
        "physics.space-ph",  # Space Physics
        "physics.plasm-ph",  # Plasma Physics
        "physics.geo-ph",  # Geophysics
    ]

    def __init__(
        self,
        base_url: str = "http://export.arxiv.org/api/query",
        rate_limit: float = 0.33,  # 3 seconds between requests
    ):
        """Initialize arXiv connector.

        Args:
            base_url: API base URL
            rate_limit: Requests per second (arXiv requires 3s delay)
        """
        super().__init__(base_url, rate_limit)

    def _parse_arxiv_id(self, id_url: str) -> str:
        """Extract arXiv ID from URL."""
        # Handle both old and new arXiv ID formats
        # http://arxiv.org/abs/2301.12345v1 -> 2301.12345
        # http://arxiv.org/abs/hep-ph/0001234v1 -> hep-ph/0001234
        match = re.search(r"arxiv\.org/abs/(.+?)(?:v\d+)?$", id_url)
        if match:
            return match.group(1)
        return id_url

    def _parse_author(self, author_data: dict) -> AuthorSchema:
        """Parse author from arXiv Atom format."""
        name = author_data.get("name", "Unknown")
        name_parts = name.rsplit(" ", 1)
        return AuthorSchema(
            given_name=name_parts[0] if len(name_parts) > 1 else None,
            family_name=name_parts[-1],
        )

    def _parse_result(self, entry: dict) -> SearchResult:
        """Parse arXiv Atom entry to SearchResult."""
        # Get arXiv ID
        arxiv_id = self._parse_arxiv_id(entry.get("id", ""))

        # Extract authors
        authors_data = entry.get("authors", [])
        if not isinstance(authors_data, list):
            authors_data = [authors_data]
        authors = [self._parse_author(a) for a in authors_data]

        # Extract year from published date
        published = entry.get("published", "")
        year = int(published[:4]) if published and len(published) >= 4 else None

        # Get PDF URL
        pdf_url = None
        links = entry.get("links", [])
        if not isinstance(links, list):
            links = [links]
        for link in links:
            if isinstance(link, dict) and link.get("type") == "application/pdf":
                pdf_url = link.get("href")
                break

        if not pdf_url:
            # Construct PDF URL from ID
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        # Get DOI if available
        doi = entry.get("arxiv_doi")

        # Get categories
        categories = []
        tags = entry.get("tags", [])
        if not isinstance(tags, list):
            tags = [tags]
        for tag in tags:
            if isinstance(tag, dict):
                categories.append(tag.get("term", ""))

        return SearchResult(
            source=self.SOURCE_NAME,
            external_id=arxiv_id,
            title=entry.get("title", "Untitled").replace("\n", " ").strip(),
            authors=authors,
            year=year,
            doi=doi,
            abstract=entry.get("summary", "").replace("\n", " ").strip(),
            journal=entry.get("arxiv_journal_ref"),
            pdf_url=pdf_url,
            url=f"https://arxiv.org/abs/{arxiv_id}",
            source_metadata={
                "categories": categories,
                "primary_category": entry.get("arxiv_primary_category", {}).get("term"),
                "comment": entry.get("arxiv_comment"),
                "updated": entry.get("updated"),
            },
        )

    async def search(
        self,
        query: str,
        limit: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
        categories: list[str] | None = None,
        **kwargs,
    ) -> list[SearchResult]:
        """Search arXiv for papers.

        Args:
            query: Search query
            limit: Maximum results
            year_from: Filter by year (from)
            year_to: Filter by year (to)
            categories: arXiv categories to search

        Returns:
            List of search results
        """
        # Build search query
        search_parts = [f"all:{query}"]

        # Add category filter
        if categories:
            cat_query = " OR ".join(f"cat:{cat}" for cat in categories)
            search_parts.append(f"({cat_query})")

        search_query = " AND ".join(search_parts)

        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": min(limit, 100),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }

        try:
            response = await self._get("", params=params)
            response.raise_for_status()

            # Parse Atom feed
            feed = feedparser.parse(response.text)
            entries = feed.get("entries", [])

            results = []
            for entry in entries:
                result = self._parse_result(entry)

                # Filter by year if specified
                if year_from and result.year and result.year < year_from:
                    continue
                if year_to and result.year and result.year > year_to:
                    continue

                results.append(result)

            logger.info(
                "arxiv_search",
                query=query,
                results=len(results),
            )

            return results[:limit]

        except Exception as e:
            logger.error("arxiv_search_error", query=query, error=str(e))
            return []

    async def get_paper(self, external_id: str) -> SearchResult | None:
        """Get paper by arXiv ID.

        Args:
            external_id: arXiv ID (e.g., "2301.12345" or "hep-ph/0001234")

        Returns:
            Paper details or None
        """
        # Clean up ID
        arxiv_id = external_id
        if arxiv_id.startswith("arXiv:"):
            arxiv_id = arxiv_id[6:]
        if arxiv_id.startswith("https://arxiv.org/abs/"):
            arxiv_id = arxiv_id[22:]

        params = {
            "id_list": arxiv_id,
            "max_results": 1,
        }

        try:
            response = await self._get("", params=params)
            response.raise_for_status()

            feed = feedparser.parse(response.text)
            entries = feed.get("entries", [])

            if not entries:
                return None

            return self._parse_result(entries[0])

        except Exception as e:
            logger.error("arxiv_get_paper_error", id=arxiv_id, error=str(e))
            return None

    async def search_heliophysics(
        self,
        query: str,
        limit: int = 10,
        **kwargs,
    ) -> list[SearchResult]:
        """Search arXiv in heliophysics-related categories.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of search results
        """
        return await self.search(
            query=query,
            limit=limit,
            categories=self.HELIO_CATEGORIES,
            **kwargs,
        )
