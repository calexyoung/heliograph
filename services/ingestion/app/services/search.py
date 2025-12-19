"""Unified search orchestration across multiple sources."""

import asyncio
from collections import defaultdict
from typing import Any

from services.ingestion.app.config import settings
from services.ingestion.app.connectors.arxiv import ArxivConnector
from services.ingestion.app.connectors.crossref import CrossrefConnector
from services.ingestion.app.connectors.scixplorer import SciXplorerConnector
from services.ingestion.app.connectors.semantic_scholar import SemanticScholarConnector
from services.ingestion.app.core.schemas import (
    SearchRequest,
    SearchResponse,
    SearchResult,
    SourceStatus,
)
from shared.utils.logging import get_logger
from shared.utils.metrics import MetricsClient

logger = get_logger(__name__)


class SearchOrchestrator:
    """Orchestrate searches across multiple academic sources."""

    def __init__(self, metrics: MetricsClient | None = None):
        """Initialize search orchestrator.

        Args:
            metrics: Metrics client for monitoring
        """
        self.metrics = metrics

        # Initialize connectors
        self.connectors = {
            "crossref": CrossrefConnector(
                mailto=settings.crossref_mailto,
            ),
            "semantic_scholar": SemanticScholarConnector(
                api_key=settings.semantic_scholar_api_key,
            ),
            "arxiv": ArxivConnector(),
            "scixplorer": SciXplorerConnector(
                api_token=settings.ads_api_token,
            ),
        }

    async def close(self) -> None:
        """Close all connector clients."""
        for connector in self.connectors.values():
            await connector.close()

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Execute search across configured sources.

        Args:
            request: Search request parameters

        Returns:
            Aggregated search response
        """
        # Determine which sources to search
        sources = request.sources or list(self.connectors.keys())

        # Filter to enabled sources
        enabled_sources = [s for s in sources if s in self.connectors]

        if not enabled_sources:
            return SearchResponse(
                query=request.query,
                results=[],
                total_results=0,
                sources_searched=[],
                source_statuses={},
            )

        # Execute searches in parallel
        tasks = []
        for source in enabled_sources:
            tasks.append(
                self._search_source(
                    source=source,
                    query=request.query,
                    limit=request.limit,
                    year_from=request.year_from,
                    year_to=request.year_to,
                )
            )

        results_by_source = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        all_results: list[SearchResult] = []
        source_statuses: dict[str, SourceStatus] = {}

        for source, result in zip(enabled_sources, results_by_source):
            if isinstance(result, Exception):
                logger.error(
                    "search_source_error",
                    source=source,
                    error=str(result),
                )
                source_statuses[source] = SourceStatus(
                    source=source,
                    success=False,
                    error=str(result),
                    result_count=0,
                )
            else:
                results, status = result
                all_results.extend(results)
                source_statuses[source] = status

        # Deduplicate results
        deduplicated = self._deduplicate_results(all_results)

        # Sort by relevance score
        deduplicated.sort(key=lambda r: r.relevance_score or 0, reverse=True)

        # Apply limit
        final_results = deduplicated[: request.limit]

        logger.info(
            "search_completed",
            query=request.query,
            sources=enabled_sources,
            total_raw=len(all_results),
            total_deduped=len(deduplicated),
            returned=len(final_results),
        )

        return SearchResponse(
            query=request.query,
            results=final_results,
            total_results=len(deduplicated),
            sources_searched=enabled_sources,
            source_statuses=source_statuses,
        )

    async def _search_source(
        self,
        source: str,
        query: str,
        limit: int,
        year_from: int | None,
        year_to: int | None,
    ) -> tuple[list[SearchResult], SourceStatus]:
        """Search a single source.

        Args:
            source: Source name
            query: Search query
            limit: Maximum results
            year_from: Year filter start
            year_to: Year filter end

        Returns:
            Tuple of results and status
        """
        connector = self.connectors[source]

        try:
            results = await connector.search(
                query=query,
                limit=limit,
                year_from=year_from,
                year_to=year_to,
            )

            return results, SourceStatus(
                source=source,
                success=True,
                result_count=len(results),
            )

        except Exception as e:
            logger.error(f"{source}_search_error", query=query, error=str(e))
            return [], SourceStatus(
                source=source,
                success=False,
                error=str(e),
                result_count=0,
            )

    def _deduplicate_results(
        self,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """Deduplicate results across sources.

        Priority:
        1. DOI match (exact)
        2. arXiv ID match (exact)
        3. Title + year match (fuzzy)

        Args:
            results: List of search results

        Returns:
            Deduplicated results with merged metadata
        """
        # Group by DOI
        by_doi: dict[str, list[SearchResult]] = defaultdict(list)
        by_arxiv: dict[str, list[SearchResult]] = defaultdict(list)
        by_title_year: dict[str, list[SearchResult]] = defaultdict(list)

        for result in results:
            if result.doi:
                by_doi[result.doi.lower()].append(result)
            elif result.source_metadata and result.source_metadata.get("arxiv_id"):
                by_arxiv[result.source_metadata["arxiv_id"]].append(result)
            else:
                # Normalize title for matching
                title_key = self._normalize_title(result.title)
                year_key = str(result.year) if result.year else "unknown"
                by_title_year[f"{title_key}|{year_key}"].append(result)

        # Merge duplicates
        deduplicated: list[SearchResult] = []

        # Process DOI groups
        for doi, group in by_doi.items():
            merged = self._merge_results(group)
            deduplicated.append(merged)

        # Process arXiv groups (exclude if DOI already captured)
        seen_arxiv = set()
        for result in deduplicated:
            if result.source_metadata and result.source_metadata.get("arxiv_id"):
                seen_arxiv.add(result.source_metadata["arxiv_id"])

        for arxiv_id, group in by_arxiv.items():
            if arxiv_id not in seen_arxiv:
                merged = self._merge_results(group)
                deduplicated.append(merged)

        # Process title+year groups (exclude if DOI or arXiv captured)
        seen_titles = set()
        for result in deduplicated:
            title_key = self._normalize_title(result.title)
            year_key = str(result.year) if result.year else "unknown"
            seen_titles.add(f"{title_key}|{year_key}")

        for key, group in by_title_year.items():
            if key not in seen_titles:
                merged = self._merge_results(group)
                deduplicated.append(merged)

        return deduplicated

    def _normalize_title(self, title: str) -> str:
        """Normalize title for deduplication.

        Args:
            title: Raw title

        Returns:
            Normalized title
        """
        import re

        # Lowercase
        normalized = title.lower()

        # Remove punctuation
        normalized = re.sub(r"[^\w\s]", "", normalized)

        # Remove extra whitespace
        normalized = " ".join(normalized.split())

        return normalized

    def _merge_results(self, group: list[SearchResult]) -> SearchResult:
        """Merge multiple results for the same paper.

        Prefers more complete data from any source.

        Args:
            group: List of results to merge

        Returns:
            Merged result
        """
        if len(group) == 1:
            return group[0]

        # Start with first result
        base = group[0]

        # Merge data from other sources
        merged_metadata = dict(base.source_metadata or {})
        sources_found = [base.source]

        for result in group[1:]:
            sources_found.append(result.source)

            # Prefer non-None values
            if not base.doi and result.doi:
                base = base.model_copy(update={"doi": result.doi})

            if not base.abstract and result.abstract:
                base = base.model_copy(update={"abstract": result.abstract})

            if not base.pdf_url and result.pdf_url:
                base = base.model_copy(update={"pdf_url": result.pdf_url})

            if not base.journal and result.journal:
                base = base.model_copy(update={"journal": result.journal})

            # Merge metadata
            if result.source_metadata:
                for key, value in result.source_metadata.items():
                    if key not in merged_metadata or merged_metadata[key] is None:
                        merged_metadata[key] = value

        # Add sources found
        merged_metadata["sources_found"] = sources_found

        # Calculate combined relevance score
        scores = [r.relevance_score for r in group if r.relevance_score]
        avg_score = sum(scores) / len(scores) if scores else None

        return base.model_copy(
            update={
                "source_metadata": merged_metadata,
                "relevance_score": avg_score,
            }
        )

    async def get_paper_by_doi(self, doi: str) -> SearchResult | None:
        """Get paper details by DOI.

        Tries multiple sources until found.

        Args:
            doi: Paper DOI

        Returns:
            Paper details or None
        """
        # Try Crossref first (authoritative for DOIs)
        result = await self.connectors["crossref"].get_paper(doi)
        if result:
            return result

        # Try Semantic Scholar
        result = await self.connectors["semantic_scholar"].get_paper(doi)
        if result:
            return result

        return None

    async def get_paper_by_arxiv(self, arxiv_id: str) -> SearchResult | None:
        """Get paper details by arXiv ID.

        Args:
            arxiv_id: arXiv identifier

        Returns:
            Paper details or None
        """
        # Try arXiv first
        result = await self.connectors["arxiv"].get_paper(arxiv_id)
        if result:
            return result

        # Try Semantic Scholar
        result = await self.connectors["semantic_scholar"].get_paper(f"arXiv:{arxiv_id}")
        if result:
            return result

        return None

    async def get_citations(
        self,
        doi: str | None = None,
        arxiv_id: str | None = None,
        bibcode: str | None = None,
        limit: int = 100,
    ) -> list[SearchResult]:
        """Get papers citing a given paper.

        Args:
            doi: Paper DOI
            arxiv_id: arXiv ID
            bibcode: ADS bibcode
            limit: Maximum results

        Returns:
            List of citing papers
        """
        results: list[SearchResult] = []

        # Use Semantic Scholar for DOI/arXiv citations
        if doi:
            ss_results = await self.connectors["semantic_scholar"].get_citations(
                f"DOI:{doi}", limit=limit
            )
            results.extend(ss_results)

        # Use SciXplorer for bibcode citations
        if bibcode:
            ads_results = await self.connectors["scixplorer"].get_citations(
                bibcode, limit=limit
            )
            results.extend(ads_results)

        # Deduplicate
        return self._deduplicate_results(results)[:limit]

    async def get_references(
        self,
        doi: str | None = None,
        arxiv_id: str | None = None,
        bibcode: str | None = None,
        limit: int = 100,
    ) -> list[SearchResult]:
        """Get papers referenced by a given paper.

        Args:
            doi: Paper DOI
            arxiv_id: arXiv ID
            bibcode: ADS bibcode
            limit: Maximum results

        Returns:
            List of referenced papers
        """
        results: list[SearchResult] = []

        # Use Semantic Scholar for DOI references
        if doi:
            ss_results = await self.connectors["semantic_scholar"].get_references(
                f"DOI:{doi}", limit=limit
            )
            results.extend(ss_results)

        # Use SciXplorer for bibcode references
        if bibcode:
            ads_results = await self.connectors["scixplorer"].get_references(
                bibcode, limit=limit
            )
            results.extend(ads_results)

        # Deduplicate
        return self._deduplicate_results(results)[:limit]

    async def search_heliophysics(
        self,
        query: str,
        limit: int = 20,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> SearchResponse:
        """Search specifically for heliophysics papers.

        Uses specialized queries for relevant sources.

        Args:
            query: Search query
            limit: Maximum results
            year_from: Year filter start
            year_to: Year filter end

        Returns:
            Search response
        """
        tasks = [
            # arXiv heliophysics categories
            self.connectors["arxiv"].search_heliophysics(
                query=query,
                limit=limit,
                year_from=year_from,
                year_to=year_to,
            ),
            # ADS heliophysics search
            self.connectors["scixplorer"].search_heliophysics(
                query=query,
                limit=limit,
                year_from=year_from,
                year_to=year_to,
            ),
            # General Semantic Scholar search
            self.connectors["semantic_scholar"].search(
                query=f"{query} heliophysics solar",
                limit=limit,
                year_from=year_from,
                year_to=year_to,
            ),
        ]

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: list[SearchResult] = []
        for result in results_list:
            if isinstance(result, list):
                all_results.extend(result)

        deduplicated = self._deduplicate_results(all_results)
        deduplicated.sort(key=lambda r: r.relevance_score or 0, reverse=True)

        return SearchResponse(
            query=query,
            results=deduplicated[:limit],
            total_results=len(deduplicated),
            sources_searched=["arxiv", "scixplorer", "semantic_scholar"],
            source_statuses={},
        )
