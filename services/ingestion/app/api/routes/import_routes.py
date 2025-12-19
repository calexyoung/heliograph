"""Import API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from services.ingestion.app.api.deps import get_db, get_import_manager
from services.ingestion.app.core.schemas import (
    ImportRecord,
    ImportRequest,
    ImportResponse,
    ImportStatus,
    SearchResult,
)
from services.ingestion.app.services.import_manager import ImportManager
from shared.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("", response_model=ImportResponse)
async def import_paper(
    request: ImportRequest,
    import_manager: ImportManager = Depends(get_import_manager),
):
    """Import a paper from external source.

    Provide at least one identifier:
    - doi: Paper DOI
    - arxiv_id: arXiv identifier
    - bibcode: NASA ADS bibcode
    - url: Direct URL to paper page

    The system will:
    1. Fetch metadata from available sources
    2. Download PDF if available and requested
    3. Register with Document Registry
    4. Return import status and document ID
    """
    # Validate at least one identifier
    if not any([request.doi, request.arxiv_id, request.bibcode, request.url]):
        raise HTTPException(
            status_code=400,
            detail="At least one identifier required (doi, arxiv_id, bibcode, or url)",
        )

    return await import_manager.import_paper(request)


@router.post("/batch", response_model=list[ImportResponse])
async def batch_import(
    papers: list[SearchResult],
    download_pdf: bool = Query(True, description="Download PDFs if available"),
    import_manager: ImportManager = Depends(get_import_manager),
):
    """Import multiple papers from search results.

    Use this after searching to import selected papers.
    """
    return await import_manager.batch_import(papers, download_pdf=download_pdf)


@router.get("/{document_id}", response_model=ImportRecord)
async def get_import(
    document_id: str,
    import_manager: ImportManager = Depends(get_import_manager),
):
    """Get import record by document ID."""
    record = await import_manager.get_import_record(document_id)

    if not record:
        raise HTTPException(status_code=404, detail="Import record not found")

    return record


@router.get("", response_model=list[ImportRecord])
async def list_imports(
    source: str | None = Query(None, description="Filter by source"),
    status: ImportStatus | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    import_manager: ImportManager = Depends(get_import_manager),
):
    """List import records."""
    return await import_manager.list_imports(
        source=source,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.post("/doi/{doi:path}", response_model=ImportResponse)
async def import_by_doi(
    doi: str,
    download_pdf: bool = Query(True, description="Download PDF if available"),
    import_manager: ImportManager = Depends(get_import_manager),
):
    """Import paper by DOI.

    Convenience endpoint for DOI-based imports.
    """
    request = ImportRequest(
        doi=doi,
        download_pdf=download_pdf,
    )

    return await import_manager.import_paper(request)


@router.post("/arxiv/{arxiv_id}", response_model=ImportResponse)
async def import_by_arxiv(
    arxiv_id: str,
    download_pdf: bool = Query(True, description="Download PDF if available"),
    import_manager: ImportManager = Depends(get_import_manager),
):
    """Import paper by arXiv ID.

    Convenience endpoint for arXiv-based imports.
    """
    request = ImportRequest(
        arxiv_id=arxiv_id,
        download_pdf=download_pdf,
    )

    return await import_manager.import_paper(request)


@router.post("/bibcode/{bibcode}", response_model=ImportResponse)
async def import_by_bibcode(
    bibcode: str,
    download_pdf: bool = Query(True, description="Download PDF if available"),
    import_manager: ImportManager = Depends(get_import_manager),
):
    """Import paper by ADS bibcode.

    Convenience endpoint for ADS-based imports.
    """
    request = ImportRequest(
        bibcode=bibcode,
        download_pdf=download_pdf,
    )

    return await import_manager.import_paper(request)
