"""API dependencies."""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from services.ingestion.app.services.import_manager import ImportManager
from services.ingestion.app.services.search import SearchOrchestrator
from services.ingestion.app.upload.handler import UploadHandler
from shared.utils.db import get_session

# Singleton instances
_search_orchestrator: SearchOrchestrator | None = None
_upload_handler: UploadHandler | None = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with get_session() as session:
        yield session


def get_search_orchestrator() -> SearchOrchestrator:
    """Get search orchestrator singleton."""
    global _search_orchestrator
    if _search_orchestrator is None:
        _search_orchestrator = SearchOrchestrator()
    return _search_orchestrator


def get_upload_handler() -> UploadHandler:
    """Get upload handler singleton."""
    global _upload_handler
    if _upload_handler is None:
        _upload_handler = UploadHandler()
    return _upload_handler


async def get_import_manager() -> AsyncGenerator[ImportManager, None]:
    """Get import manager with database session."""
    async with get_session() as session:
        manager = ImportManager(
            db=session,
            search_orchestrator=get_search_orchestrator(),
            upload_handler=get_upload_handler(),
        )
        try:
            yield manager
        finally:
            await manager.close()


async def cleanup_dependencies() -> None:
    """Cleanup singleton instances on shutdown."""
    global _search_orchestrator, _upload_handler

    if _search_orchestrator:
        await _search_orchestrator.close()
        _search_orchestrator = None

    _upload_handler = None
