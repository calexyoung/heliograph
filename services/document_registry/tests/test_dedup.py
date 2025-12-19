"""Tests for deduplication service."""

from uuid import uuid4

import pytest

from services.document_registry.app.core.dedup import (
    DeduplicationService,
    MatchType,
)
from services.document_registry.app.db.models import DocumentModel
from shared.schemas.document import DocumentStatus


class TestDeduplicationService:
    """Tests for deduplication logic."""

    @pytest.mark.asyncio
    async def test_no_duplicate_for_new_document(self, db_session):
        """Test that new document is not flagged as duplicate."""
        service = DeduplicationService(db_session)

        result = await service.check_duplicate(
            doi="10.1234/new.2024.001",
            content_hash="b" * 64,
            title="A Completely New Document",
            year=2024,
        )

        assert not result.is_duplicate
        assert result.match_type is None
        assert result.existing_document is None

    @pytest.mark.asyncio
    async def test_doi_exact_match(self, db_session, existing_document):
        """Test DOI exact match detection."""
        service = DeduplicationService(db_session)

        result = await service.check_duplicate(
            doi=existing_document.doi,
            content_hash="b" * 64,  # Different hash
            title="Different Title",
            year=2025,
        )

        assert result.is_duplicate
        assert result.match_type == MatchType.DOI
        assert result.existing_document.document_id == existing_document.document_id

    @pytest.mark.asyncio
    async def test_doi_match_with_prefix(self, db_session, existing_document):
        """Test DOI match works with URL prefix."""
        service = DeduplicationService(db_session)

        result = await service.check_duplicate(
            doi=f"https://doi.org/{existing_document.doi}",
            content_hash="b" * 64,
            title="Different Title",
            year=2025,
        )

        assert result.is_duplicate
        assert result.match_type == MatchType.DOI

    @pytest.mark.asyncio
    async def test_content_hash_match(self, db_session, existing_document):
        """Test content hash exact match detection."""
        service = DeduplicationService(db_session)

        result = await service.check_duplicate(
            doi=None,  # No DOI
            content_hash=existing_document.content_hash,
            title="Different Title",
            year=2025,
        )

        assert result.is_duplicate
        assert result.match_type == MatchType.CONTENT_HASH
        assert result.existing_document.document_id == existing_document.document_id

    @pytest.mark.asyncio
    async def test_composite_key_match(self, db_session, existing_document):
        """Test composite key (hash + title + year) match."""
        service = DeduplicationService(db_session)

        result = await service.check_duplicate(
            doi=None,
            content_hash=existing_document.content_hash,
            title=existing_document.title,
            year=existing_document.year,
        )

        assert result.is_duplicate
        # Should match on content_hash first
        assert result.match_type in (MatchType.CONTENT_HASH, MatchType.COMPOSITE)

    @pytest.mark.asyncio
    async def test_fuzzy_title_match_above_threshold(self, db_session, existing_document):
        """Test fuzzy title match above threshold."""
        service = DeduplicationService(db_session, fuzzy_threshold=0.9)

        # Slightly modified title (should still match at 0.9 threshold)
        similar_title = "Test Document Title: A Study of Somethng"  # Typo in 'Something'

        result = await service.check_duplicate(
            doi=None,
            content_hash="c" * 64,  # Different hash
            title=similar_title,
            year=existing_document.year,  # Same year
        )

        assert result.is_duplicate
        assert result.match_type == MatchType.FUZZY_TITLE
        assert result.similarity_score is not None
        assert result.similarity_score >= 0.9

    @pytest.mark.asyncio
    async def test_fuzzy_title_no_match_below_threshold(self, db_session, existing_document):
        """Test fuzzy title doesn't match below threshold."""
        service = DeduplicationService(db_session, fuzzy_threshold=0.9)

        # Very different title
        different_title = "Completely Different Topic About Magnetism"

        result = await service.check_duplicate(
            doi=None,
            content_hash="c" * 64,
            title=different_title,
            year=existing_document.year,
        )

        assert not result.is_duplicate

    @pytest.mark.asyncio
    async def test_fuzzy_title_different_year_no_match(self, db_session, existing_document):
        """Test fuzzy title doesn't match with different year."""
        service = DeduplicationService(db_session, fuzzy_threshold=0.9)

        result = await service.check_duplicate(
            doi=None,
            content_hash="c" * 64,
            title=existing_document.title,  # Same title
            year=2000,  # Different year
        )

        # Should not find fuzzy match because year is different
        assert not result.is_duplicate

    @pytest.mark.asyncio
    async def test_fuzzy_match_threshold_boundary(self, db_session, existing_document):
        """Test fuzzy match at exact threshold boundary."""
        # Create document with title that's exactly at threshold
        service = DeduplicationService(db_session, fuzzy_threshold=0.9)

        # Title with ~10% difference
        boundary_title = "Test Document Title: A Study of Nothing"

        result = await service.check_duplicate(
            doi=None,
            content_hash="d" * 64,
            title=boundary_title,
            year=existing_document.year,
        )

        # Result depends on exact similarity score
        if result.is_duplicate:
            assert result.similarity_score >= 0.9

    @pytest.mark.asyncio
    async def test_handle_duplicate_merges_metadata(self, db_session, existing_document):
        """Test that handling duplicate merges metadata."""
        service = DeduplicationService(db_session)
        user_id = uuid4()

        new_metadata = {"new_field": "new_value"}
        await service.handle_duplicate(
            existing_document=existing_document,
            new_source_metadata=new_metadata,
            source="crossref",
            user_id=user_id,
        )

        # Check metadata was merged
        assert "new_field" in existing_document.source_metadata

    @pytest.mark.asyncio
    async def test_handle_duplicate_adds_provenance(self, db_session, existing_document):
        """Test that handling duplicate adds provenance record."""
        service = DeduplicationService(db_session)
        user_id = uuid4()
        upload_id = uuid4()

        await service.handle_duplicate(
            existing_document=existing_document,
            new_source_metadata={},
            source="upload",
            user_id=user_id,
            upload_id=upload_id,
        )

        # Provenance should be added (check via repository or query)
        await db_session.refresh(existing_document, ["provenance_records"])
        assert len(existing_document.provenance_records) == 1
        assert existing_document.provenance_records[0].source == "upload"
        assert existing_document.provenance_records[0].user_id == user_id
