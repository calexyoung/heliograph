"""Database repository for document operations."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update, and_, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


def utc_now() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)

from services.document_registry.app.db.models import (
    DocumentModel,
    ProvenanceModel,
    StateAuditModel,
)
from shared.schemas.document import DocumentStatus


class DocumentRepository:
    """Repository for document database operations."""

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session."""
        self.session = session

    async def get_by_id(
        self,
        document_id: UUID,
        include_provenance: bool = False,
    ) -> DocumentModel | None:
        """Get document by ID.

        Args:
            document_id: Document UUID
            include_provenance: Whether to eagerly load provenance records

        Returns:
            Document model or None if not found
        """
        query = select(DocumentModel).where(DocumentModel.document_id == document_id)

        if include_provenance:
            query = query.options(selectinload(DocumentModel.provenance_records))

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_doi(self, doi: str) -> DocumentModel | None:
        """Get document by DOI.

        Args:
            doi: Document DOI (normalized)

        Returns:
            Document model or None if not found
        """
        query = select(DocumentModel).where(DocumentModel.doi == doi)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_content_hash(self, content_hash: str) -> DocumentModel | None:
        """Get document by content hash.

        Args:
            content_hash: SHA-256 hash of document content

        Returns:
            Document model or None if not found
        """
        query = select(DocumentModel).where(DocumentModel.content_hash == content_hash)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_composite_key(
        self,
        content_hash: str,
        title_normalized: str,
        year: int | None,
    ) -> DocumentModel | None:
        """Get document by composite key (content_hash, title_normalized, year).

        Args:
            content_hash: SHA-256 hash
            title_normalized: Normalized title
            year: Publication year

        Returns:
            Document model or None if not found
        """
        query = select(DocumentModel).where(
            and_(
                DocumentModel.content_hash == content_hash,
                DocumentModel.title_normalized == title_normalized,
                DocumentModel.year == year,
            )
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def find_candidates_for_fuzzy_match(
        self,
        year: int | None,
        limit: int = 100,
    ) -> list[DocumentModel]:
        """Find documents from the same year for fuzzy title matching.

        Args:
            year: Publication year to match
            limit: Maximum candidates to return

        Returns:
            List of document models from the same year
        """
        query = select(DocumentModel).where(DocumentModel.year == year).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(
        self,
        doi: str | None,
        content_hash: str | None,
        title: str,
        title_normalized: str,
        authors: list[dict[str, Any]],
        subtitle: str | None = None,
        journal: str | None = None,
        year: int | None = None,
        source_metadata: dict[str, Any] | None = None,
    ) -> tuple[DocumentModel, bool]:
        """Create a new document using INSERT ON CONFLICT for race condition safety.

        Uses PostgreSQL INSERT ... ON CONFLICT DO NOTHING to safely handle
        concurrent registration attempts. If a document with the same
        content_hash or DOI already exists, returns the existing document.

        For SQLite (used in testing), falls back to check-then-insert pattern.

        Args:
            doi: Document DOI (optional)
            content_hash: SHA-256 hash (optional if DOI provided)
            title: Document title
            title_normalized: Normalized title
            authors: List of author dictionaries
            subtitle: Document subtitle
            journal: Journal name
            year: Publication year
            source_metadata: Additional metadata

        Returns:
            Tuple of (document model, created flag)
            - created=True: New document was inserted
            - created=False: Existing document was found (race condition)
        """
        from uuid import uuid4

        now = utc_now()
        document_id = uuid4()

        # Check dialect to use appropriate insert strategy
        dialect_name = self.session.bind.dialect.name if self.session.bind else "postgresql"

        if dialect_name == "sqlite":
            # SQLite fallback: check-then-insert pattern with race condition handling
            # First check if document already exists
            if content_hash:
                existing = await self.get_by_content_hash(content_hash)
                if existing:
                    return existing, False
            if doi:
                existing = await self.get_by_doi(doi)
                if existing:
                    return existing, False

            # No existing document found, create new one
            document = DocumentModel(
                document_id=document_id,
                doi=doi,
                content_hash=content_hash,
                title=title,
                title_normalized=title_normalized,
                subtitle=subtitle,
                journal=journal,
                year=year,
                authors=authors,
                source_metadata=source_metadata or {},
                status=DocumentStatus.REGISTERED,
                artifact_pointers={},
                created_at=now,
                updated_at=now,
            )
            self.session.add(document)
            try:
                await self.session.flush()
                return document, True
            except IntegrityError:
                # Race condition: another request inserted first
                await self.session.rollback()
                # Fetch the existing document
                if content_hash:
                    existing = await self.get_by_content_hash(content_hash)
                elif doi:
                    existing = await self.get_by_doi(doi)
                else:
                    raise ValueError("Either doi or content_hash must be provided")
                if existing:
                    return existing, False
                raise

        # PostgreSQL: Use INSERT ... ON CONFLICT DO NOTHING for atomic insert
        stmt = pg_insert(DocumentModel).values(
            document_id=document_id,
            doi=doi,
            content_hash=content_hash,
            title=title,
            title_normalized=title_normalized,
            subtitle=subtitle,
            journal=journal,
            year=year,
            authors=authors,
            source_metadata=source_metadata or {},
            status=DocumentStatus.REGISTERED,
            artifact_pointers={},
            created_at=now,
            updated_at=now,
        ).on_conflict_do_nothing(
            index_elements=["content_hash"] if content_hash else ["doi"]
        ).returning(DocumentModel)

        result = await self.session.execute(stmt)
        document = result.scalar_one_or_none()

        if document is not None:
            # Insert succeeded - this is a new document
            return document, True

        # Conflict occurred - fetch the existing document
        if content_hash:
            existing = await self.get_by_content_hash(content_hash)
        elif doi:
            existing = await self.get_by_doi(doi)
        else:
            # This shouldn't happen due to validation, but handle gracefully
            raise ValueError("Either doi or content_hash must be provided")

        if existing is None:
            # This shouldn't happen, but handle the edge case
            raise RuntimeError("Conflict detected but existing document not found")

        return existing, False

    async def add_provenance(
        self,
        document_id: UUID,
        source: str,
        user_id: UUID,
        metadata_snapshot: dict[str, Any],
        source_query: str | None = None,
        source_identifier: str | None = None,
        connector_job_id: UUID | None = None,
        upload_id: UUID | None = None,
    ) -> ProvenanceModel:
        """Add a provenance record for a document.

        Args:
            document_id: Document UUID
            source: Source type (upload, crossref, etc.)
            user_id: User who initiated the registration
            metadata_snapshot: Snapshot of metadata at registration time
            source_query: Search query used (if applicable)
            source_identifier: External identifier (if applicable)
            connector_job_id: Connector job ID (if applicable)
            upload_id: Upload ID (if applicable)

        Returns:
            Created provenance model
        """
        provenance = ProvenanceModel(
            document_id=document_id,
            source=source,
            user_id=user_id,
            metadata_snapshot=metadata_snapshot,
            source_query=source_query,
            source_identifier=source_identifier,
            connector_job_id=connector_job_id,
            upload_id=upload_id,
        )
        self.session.add(provenance)
        await self.session.flush()
        return provenance

    async def update_status(
        self,
        document_id: UUID,
        new_status: DocumentStatus,
        worker_id: str | None = None,
        error_message: str | None = None,
        artifact_pointers: dict[str, str] | None = None,
        expected_status: DocumentStatus | None = None,
    ) -> tuple[DocumentModel | None, bool]:
        """Update document status with atomic optimistic locking.

        Uses a single UPDATE query with WHERE clause to ensure atomicity.
        This prevents race conditions where status could change between
        read and write operations.

        Args:
            document_id: Document UUID
            new_status: New status to set
            worker_id: ID of worker making the update
            error_message: Error message (for failed status)
            artifact_pointers: Updated artifact pointers
            expected_status: Expected current status (optimistic lock)

        Returns:
            Tuple of (updated document, success flag)
            If expected_status doesn't match, returns (current document, False)
            If document not found, returns (None, False)
        """
        # First, get current document to capture previous state for audit
        document = await self.get_by_id(document_id)
        if document is None:
            return None, False

        previous_state = document.status

        # Build atomic UPDATE with WHERE clause for optimistic locking
        now = utc_now()
        update_values: dict[str, Any] = {
            "status": new_status,
            "updated_at": now,
        }

        if error_message:
            update_values["error_message"] = error_message

        if new_status in (DocumentStatus.INDEXED, DocumentStatus.FAILED):
            update_values["last_processed_at"] = now

        # Build WHERE conditions
        where_conditions = [DocumentModel.document_id == document_id]
        if expected_status is not None:
            where_conditions.append(DocumentModel.status == expected_status)

        # Execute atomic UPDATE
        stmt = (
            update(DocumentModel)
            .where(and_(*where_conditions))
            .values(**update_values)
        )
        result = await self.session.execute(stmt)

        # Check if update succeeded (row was modified)
        if result.rowcount == 0:
            # Optimistic lock failed - refresh document to get current state
            await self.session.refresh(document)
            return document, False

        # Update succeeded - handle artifact pointers separately
        # (JSONB merge needs to be done on the model instance)
        if artifact_pointers:
            # Refresh to get updated state
            await self.session.refresh(document)
            document.artifact_pointers = {**document.artifact_pointers, **artifact_pointers}

        # Record audit entry (only if update succeeded)
        audit = StateAuditModel(
            document_id=document_id,
            previous_state=previous_state,
            new_state=new_status,
            worker_id=worker_id,
            error_message=error_message,
        )
        self.session.add(audit)

        await self.session.flush()

        # Refresh document to return updated state
        await self.session.refresh(document)
        return document, True

    async def merge_metadata(
        self,
        document: DocumentModel,
        new_metadata: dict[str, Any],
    ) -> DocumentModel:
        """Merge new metadata into existing document.

        Args:
            document: Existing document model
            new_metadata: New metadata to merge

        Returns:
            Updated document model
        """
        merged = {**document.source_metadata, **new_metadata}
        document.source_metadata = merged
        await self.session.flush()
        return document

    async def update_artifact_pointers(
        self,
        document_id: UUID,
        artifact_pointers: dict[str, str],
    ) -> bool:
        """Update document artifact pointers.

        Args:
            document_id: Document UUID
            artifact_pointers: New artifact pointers

        Returns:
            True if updated, False if document not found
        """
        document = await self.get_by_id(document_id)
        if document is None:
            return False

        document.artifact_pointers = artifact_pointers
        await self.session.flush()
        return True

    async def list_documents(
        self,
        status: DocumentStatus | None = None,
        limit: int = 100,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[DocumentModel]:
        """List documents with optional filtering (offset-based).

        Args:
            status: Optional status filter
            limit: Maximum documents to return
            offset: Number of documents to skip
            include_deleted: Whether to include soft-deleted documents

        Returns:
            List of document models
        """
        query = select(DocumentModel).order_by(DocumentModel.created_at.desc())

        if not include_deleted:
            query = query.where(DocumentModel.deleted_at.is_(None))

        if status is not None:
            query = query.where(DocumentModel.status == status)

        query = query.limit(limit).offset(offset)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_documents_cursor(
        self,
        status: DocumentStatus | None = None,
        limit: int = 100,
        cursor: UUID | None = None,
        include_deleted: bool = False,
    ) -> list[DocumentModel]:
        """List documents with cursor-based pagination.

        Uses document_id as cursor for stable pagination.
        Documents are ordered by created_at DESC, document_id DESC.

        Args:
            status: Optional status filter
            limit: Maximum documents to return
            cursor: Last document_id from previous page
            include_deleted: Whether to include soft-deleted documents

        Returns:
            List of document models
        """
        query = select(DocumentModel).order_by(
            DocumentModel.created_at.desc(),
            DocumentModel.document_id.desc(),
        )

        if not include_deleted:
            query = query.where(DocumentModel.deleted_at.is_(None))

        if status is not None:
            query = query.where(DocumentModel.status == status)

        if cursor is not None:
            # Get the cursor document to find its created_at
            cursor_doc = await self.get_by_id(cursor)
            if cursor_doc:
                # Get documents older than cursor OR same time but smaller ID
                query = query.where(
                    or_(
                        DocumentModel.created_at < cursor_doc.created_at,
                        and_(
                            DocumentModel.created_at == cursor_doc.created_at,
                            DocumentModel.document_id < cursor,
                        ),
                    )
                )

        query = query.limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count_documents(
        self,
        status: DocumentStatus | None = None,
        include_deleted: bool = False,
    ) -> int:
        """Count documents with optional filtering.

        Args:
            status: Optional status filter
            include_deleted: Whether to include soft-deleted documents

        Returns:
            Total count of matching documents
        """
        from sqlalchemy import func

        query = select(func.count()).select_from(DocumentModel)

        if not include_deleted:
            query = query.where(DocumentModel.deleted_at.is_(None))

        if status is not None:
            query = query.where(DocumentModel.status == status)

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def soft_delete(
        self,
        document_id: UUID,
    ) -> tuple[DocumentModel | None, bool]:
        """Soft delete a document by setting deleted_at timestamp.

        Args:
            document_id: Document UUID to soft delete

        Returns:
            Tuple of (document model, success flag)
            If document not found, returns (None, False)
            If already deleted, returns (document, False)
        """
        document = await self.get_by_id(document_id)
        if document is None:
            return None, False

        if document.deleted_at is not None:
            # Already deleted
            return document, False

        document.deleted_at = utc_now()
        await self.session.flush()
        return document, True

    async def restore(
        self,
        document_id: UUID,
    ) -> tuple[DocumentModel | None, bool]:
        """Restore a soft-deleted document.

        Args:
            document_id: Document UUID to restore

        Returns:
            Tuple of (document model, success flag)
            If document not found, returns (None, False)
            If not deleted, returns (document, False)
        """
        # Need to bypass the default deleted filter
        query = select(DocumentModel).where(DocumentModel.document_id == document_id)
        result = await self.session.execute(query)
        document = result.scalar_one_or_none()

        if document is None:
            return None, False

        if document.deleted_at is None:
            # Not deleted
            return document, False

        document.deleted_at = None
        await self.session.flush()
        return document, True
