"""Search API endpoints."""

from fastapi import APIRouter, Depends, Query

from services.ingestion.app.api.deps import get_search_orchestrator
from services.ingestion.app.core.schemas import (
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from services.ingestion.app.services.search import SearchOrchestrator
from shared.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("", response_model=SearchResponse)
async def search_papers(
    request: SearchRequest,
    search: SearchOrchestrator = Depends(get_search_orchestrator),
):
    """Search for papers across multiple sources.

    Searches Crossref, Semantic Scholar, arXiv, and NASA ADS/SciXplorer
    in parallel and returns deduplicated results.
    """
    return await search.search(request)


@router.get("", response_model=SearchResponse)
async def search_papers_get(
    query: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    sources: str | None = Query(None, description="Comma-separated source list"),
    year_from: int | None = Query(None, description="Filter from year"),
    year_to: int | None = Query(None, description="Filter to year"),
    search: SearchOrchestrator = Depends(get_search_orchestrator),
):
    """Search for papers (GET endpoint).

    Alternative to POST for simple queries.
    """
    source_list = sources.split(",") if sources else None

    request = SearchRequest(
        query=query,
        limit=limit,
        sources=source_list,
        year_from=year_from,
        year_to=year_to,
    )

    return await search.search(request)


@router.get("/heliophysics", response_model=SearchResponse)
async def search_heliophysics(
    query: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    year_from: int | None = Query(None, description="Filter from year"),
    year_to: int | None = Query(None, description="Filter to year"),
    search: SearchOrchestrator = Depends(get_search_orchestrator),
):
    """Search specifically for heliophysics papers.

    Uses specialized queries and categories for heliophysics-relevant sources.
    """
    return await search.search_heliophysics(
        query=query,
        limit=limit,
        year_from=year_from,
        year_to=year_to,
    )


@router.get("/doi/{doi:path}", response_model=SearchResult | None)
async def get_by_doi(
    doi: str,
    search: SearchOrchestrator = Depends(get_search_orchestrator),
):
    """Get paper by DOI.

    Args:
        doi: Paper DOI (e.g., "10.1234/example")
    """
    return await search.get_paper_by_doi(doi)


@router.get("/arxiv/{arxiv_id}", response_model=SearchResult | None)
async def get_by_arxiv(
    arxiv_id: str,
    search: SearchOrchestrator = Depends(get_search_orchestrator),
):
    """Get paper by arXiv ID.

    Args:
        arxiv_id: arXiv identifier (e.g., "2301.12345")
    """
    return await search.get_paper_by_arxiv(arxiv_id)


@router.get("/citations", response_model=list[SearchResult])
async def get_citations(
    doi: str | None = Query(None, description="Paper DOI"),
    bibcode: str | None = Query(None, description="ADS bibcode"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    search: SearchOrchestrator = Depends(get_search_orchestrator),
):
    """Get papers that cite the specified paper.

    Provide either DOI or bibcode.
    """
    if not doi and not bibcode:
        return []

    return await search.get_citations(doi=doi, bibcode=bibcode, limit=limit)


@router.get("/references", response_model=list[SearchResult])
async def get_references(
    doi: str | None = Query(None, description="Paper DOI"),
    bibcode: str | None = Query(None, description="ADS bibcode"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    search: SearchOrchestrator = Depends(get_search_orchestrator),
):
    """Get papers referenced by the specified paper.

    Provide either DOI or bibcode.
    """
    if not doi and not bibcode:
        return []

    return await search.get_references(doi=doi, bibcode=bibcode, limit=limit)


@router.get("/sources")
async def list_sources():
    """List available search sources."""
    return {
        "sources": [
            {
                "name": "crossref",
                "description": "Crossref metadata API",
                "capabilities": ["search", "lookup_by_doi"],
            },
            {
                "name": "semantic_scholar",
                "description": "Semantic Scholar Academic Graph API",
                "capabilities": ["search", "lookup_by_doi", "lookup_by_arxiv", "citations", "references"],
            },
            {
                "name": "arxiv",
                "description": "arXiv preprint server",
                "capabilities": ["search", "lookup_by_arxiv"],
            },
            {
                "name": "scixplorer",
                "description": "NASA ADS / SciXplorer",
                "capabilities": ["search", "lookup_by_bibcode", "citations", "references", "heliophysics"],
            },
        ]
    }
