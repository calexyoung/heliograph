"""Deduplication service for document registration."""

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from rapidfuzz import fuzz
from sqlalchemy.ext.asyncio import AsyncSession

from services.document_registry.app.core.normalizers import normalize_doi, normalize_title
from services.document_registry.app.db.models import DocumentModel
from services.document_registry.app.db.repository import DocumentRepository
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class MatchType(str, Enum):
    """Type of duplicate match found."""

    DOI = "doi"
    CONTENT_HASH = "content_hash"
    COMPOSITE = "composite"  # content_hash + title_normalized + year
    FUZZY_TITLE = "fuzzy_title"


@dataclass
class DuplicateResult:
    """Result of duplicate check."""

    is_duplicate: bool
    match_type: MatchType | None = None
    existing_document: DocumentModel | None = None
    similarity_score: float | None = None


class DeduplicationService:
    """Service for checking and handling document duplicates."""

    def __init__(
        self,
        session: AsyncSession,
        fuzzy_threshold: float = 0.9,
    ):
        """Initialize deduplication service.

        Args:
            session: Database session
            fuzzy_threshold: Levenshtein ratio threshold for fuzzy matching (0.0-1.0)
        """
        self.repository = DocumentRepository(session)
        self.fuzzy_threshold = fuzzy_threshold

    async def check_duplicate(
        self,
        doi: str | None,
        content_hash: str | None,
        title: str,
        year: int | None,
    ) -> DuplicateResult:
        """Check if a document is a duplicate.

        Checks in order:
        1. DOI exact match
        2. Content hash exact match (if content_hash provided)
        3. Composite key match (content_hash, title_normalized, year) - if content_hash provided
        4. Fuzzy title match on same year

        Args:
            doi: Document DOI (optional)
            content_hash: SHA-256 hash of document content (optional)
            title: Document title
            year: Publication year

        Returns:
            DuplicateResult indicating if duplicate and match details
        """
        normalized_doi = normalize_doi(doi)
        normalized_title = normalize_title(title)

        # 1. Check DOI exact match
        if normalized_doi:
            existing = await self.repository.get_by_doi(normalized_doi)
            if existing:
                logger.info(
                    "duplicate_found",
                    match_type="doi",
                    existing_document_id=str(existing.document_id),
                    doi=normalized_doi,
                )
                return DuplicateResult(
                    is_duplicate=True,
                    match_type=MatchType.DOI,
                    existing_document=existing,
                )

        # 2. Check content hash exact match (only if content_hash provided)
        if content_hash:
            existing = await self.repository.get_by_content_hash(content_hash)
            if existing:
                logger.info(
                    "duplicate_found",
                    match_type="content_hash",
                    existing_document_id=str(existing.document_id),
                    content_hash=content_hash[:16] + "...",
                )
                return DuplicateResult(
                    is_duplicate=True,
                    match_type=MatchType.CONTENT_HASH,
                    existing_document=existing,
                )

            # 3. Check composite key match (only if content_hash provided)
            existing = await self.repository.get_by_composite_key(
                content_hash=content_hash,
                title_normalized=normalized_title,
                year=year,
            )
            if existing:
                logger.info(
                    "duplicate_found",
                    match_type="composite",
                    existing_document_id=str(existing.document_id),
                )
                return DuplicateResult(
                    is_duplicate=True,
                    match_type=MatchType.COMPOSITE,
                    existing_document=existing,
                )

        # 4. Fuzzy title match on same year
        if year is not None:
            candidates = await self.repository.find_candidates_for_fuzzy_match(year)
            for candidate in candidates:
                similarity = fuzz.ratio(normalized_title, candidate.title_normalized) / 100.0
                if similarity >= self.fuzzy_threshold:
                    logger.info(
                        "duplicate_found",
                        match_type="fuzzy_title",
                        existing_document_id=str(candidate.document_id),
                        similarity=similarity,
                    )
                    return DuplicateResult(
                        is_duplicate=True,
                        match_type=MatchType.FUZZY_TITLE,
                        existing_document=candidate,
                        similarity_score=similarity,
                    )

        # No duplicate found
        return DuplicateResult(is_duplicate=False)

    async def handle_duplicate(
        self,
        existing_document: DocumentModel,
        new_source_metadata: dict,
        source: str,
        user_id: UUID,
        upload_id: UUID | None = None,
        connector_job_id: UUID | None = None,
    ) -> DocumentModel:
        """Handle a duplicate by merging metadata and recording provenance.

        Args:
            existing_document: The existing document that matches
            new_source_metadata: Metadata from the new registration request
            source: Source of the new registration
            user_id: User who initiated the registration
            upload_id: Upload ID if from direct upload
            connector_job_id: Connector job ID if from API import

        Returns:
            Updated document model
        """
        # Merge metadata
        await self.repository.merge_metadata(existing_document, new_source_metadata)

        # Add provenance record
        await self.repository.add_provenance(
            document_id=existing_document.document_id,
            source=source,
            user_id=user_id,
            metadata_snapshot=new_source_metadata,
            upload_id=upload_id,
            connector_job_id=connector_job_id,
        )

        logger.info(
            "duplicate_handled",
            document_id=str(existing_document.document_id),
            source=source,
        )

        return existing_document
