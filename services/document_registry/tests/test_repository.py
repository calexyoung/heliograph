"""Tests for Document Repository operations."""

from uuid import uuid4

import pytest

from services.document_registry.app.db.models import DocumentModel, ProvenanceModel, StateAuditModel
from services.document_registry.app.db.repository import DocumentRepository
from shared.schemas.document import DocumentStatus


class TestDocumentCreate:
    """Tests for document creation."""

    @pytest.mark.asyncio
    async def test_create_document_with_all_fields(self, db_session):
        """Test creating a document with all fields populated."""
        repository = DocumentRepository(db_session)

        document, created = await repository.create(
            doi="10.1234/test.create.001",
            content_hash="a" * 64,
            title="Test Document Title",
            title_normalized="test document title",
            authors=[{"given_name": "John", "family_name": "Doe"}],
            subtitle="A Subtitle",
            journal="Journal of Testing",
            year=2024,
            source_metadata={"key": "value"},
        )

        assert created is True
        assert document.document_id is not None
        assert document.doi == "10.1234/test.create.001"
        assert document.content_hash == "a" * 64
        assert document.title == "Test Document Title"
        assert document.status == DocumentStatus.REGISTERED
        assert len(document.authors) == 1

    @pytest.mark.asyncio
    async def test_create_document_with_minimal_fields(self, db_session):
        """Test creating a document with minimal required fields."""
        repository = DocumentRepository(db_session)

        document, created = await repository.create(
            doi="10.1234/minimal.001",
            content_hash=None,
            title="Minimal Document",
            title_normalized="minimal document",
            authors=[],
        )

        assert created is True
        assert document.doi == "10.1234/minimal.001"
        assert document.content_hash is None
        assert document.authors == []
        assert document.source_metadata == {}

    @pytest.mark.asyncio
    async def test_create_duplicate_content_hash_returns_existing(self, db_session):
        """Test that duplicate content hash returns existing document."""
        repository = DocumentRepository(db_session)
        content_hash = "b" * 64

        # Create first document
        doc1, created1 = await repository.create(
            doi=None,
            content_hash=content_hash,
            title="First Document",
            title_normalized="first document",
            authors=[],
        )
        await db_session.commit()

        assert created1 is True

        # Try to create with same content hash
        doc2, created2 = await repository.create(
            doi=None,
            content_hash=content_hash,
            title="Second Document",
            title_normalized="second document",
            authors=[],
        )

        assert created2 is False
        assert doc2.document_id == doc1.document_id

    @pytest.mark.asyncio
    async def test_create_duplicate_doi_returns_existing(self, db_session):
        """Test that duplicate DOI returns existing document."""
        repository = DocumentRepository(db_session)
        doi = "10.1234/duplicate.doi"

        # Create first document
        doc1, created1 = await repository.create(
            doi=doi,
            content_hash=None,
            title="First Document",
            title_normalized="first document",
            authors=[],
        )
        await db_session.commit()

        assert created1 is True

        # Try to create with same DOI
        doc2, created2 = await repository.create(
            doi=doi,
            content_hash=None,
            title="Second Document",
            title_normalized="second document",
            authors=[],
        )

        assert created2 is False
        assert doc2.document_id == doc1.document_id


class TestDocumentRetrieval:
    """Tests for document retrieval methods."""

    @pytest.mark.asyncio
    async def test_get_by_id(self, db_session, existing_document):
        """Test retrieving document by ID."""
        repository = DocumentRepository(db_session)

        document = await repository.get_by_id(existing_document.document_id)

        assert document is not None
        assert document.document_id == existing_document.document_id

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, db_session):
        """Test retrieving non-existent document returns None."""
        repository = DocumentRepository(db_session)

        document = await repository.get_by_id(uuid4())

        assert document is None

    @pytest.mark.asyncio
    async def test_get_by_id_with_provenance(self, db_session, existing_document):
        """Test retrieving document with provenance eagerly loaded."""
        repository = DocumentRepository(db_session)

        # Add provenance
        await repository.add_provenance(
            document_id=existing_document.document_id,
            source="upload",
            user_id=uuid4(),
            metadata_snapshot={},
        )
        await db_session.commit()

        document = await repository.get_by_id(
            existing_document.document_id,
            include_provenance=True
        )

        assert document is not None
        assert len(document.provenance_records) == 1

    @pytest.mark.asyncio
    async def test_get_by_doi(self, db_session, existing_document):
        """Test retrieving document by DOI."""
        repository = DocumentRepository(db_session)

        document = await repository.get_by_doi(existing_document.doi)

        assert document is not None
        assert document.document_id == existing_document.document_id

    @pytest.mark.asyncio
    async def test_get_by_doi_not_found(self, db_session):
        """Test retrieving by non-existent DOI returns None."""
        repository = DocumentRepository(db_session)

        document = await repository.get_by_doi("10.1234/nonexistent")

        assert document is None

    @pytest.mark.asyncio
    async def test_get_by_content_hash(self, db_session, existing_document):
        """Test retrieving document by content hash."""
        repository = DocumentRepository(db_session)

        document = await repository.get_by_content_hash(existing_document.content_hash)

        assert document is not None
        assert document.document_id == existing_document.document_id

    @pytest.mark.asyncio
    async def test_get_by_composite_key(self, db_session, existing_document):
        """Test retrieving document by composite key."""
        repository = DocumentRepository(db_session)

        document = await repository.get_by_composite_key(
            content_hash=existing_document.content_hash,
            title_normalized=existing_document.title_normalized,
            year=existing_document.year,
        )

        assert document is not None
        assert document.document_id == existing_document.document_id


class TestDocumentStatusUpdate:
    """Tests for document status updates with optimistic locking."""

    @pytest.mark.asyncio
    async def test_update_status_success(self, db_session, existing_document):
        """Test successful status update."""
        repository = DocumentRepository(db_session)

        document, success = await repository.update_status(
            document_id=existing_document.document_id,
            new_status=DocumentStatus.PROCESSING,
            worker_id="test-worker",
        )

        assert success is True
        assert document.status == DocumentStatus.PROCESSING

    @pytest.mark.asyncio
    async def test_update_status_with_expected_state(self, db_session, existing_document):
        """Test status update with correct expected state."""
        repository = DocumentRepository(db_session)

        document, success = await repository.update_status(
            document_id=existing_document.document_id,
            new_status=DocumentStatus.PROCESSING,
            worker_id="test-worker",
            expected_status=DocumentStatus.REGISTERED,
        )

        assert success is True
        assert document.status == DocumentStatus.PROCESSING

    @pytest.mark.asyncio
    async def test_update_status_optimistic_lock_failure(self, db_session, existing_document):
        """Test status update fails with wrong expected state."""
        repository = DocumentRepository(db_session)

        document, success = await repository.update_status(
            document_id=existing_document.document_id,
            new_status=DocumentStatus.PROCESSING,
            worker_id="test-worker",
            expected_status=DocumentStatus.PROCESSING,  # Wrong - it's REGISTERED
        )

        assert success is False
        assert document.status == DocumentStatus.REGISTERED

    @pytest.mark.asyncio
    async def test_update_status_creates_audit_record(self, db_session, existing_document):
        """Test that status update creates audit record."""
        repository = DocumentRepository(db_session)

        await repository.update_status(
            document_id=existing_document.document_id,
            new_status=DocumentStatus.PROCESSING,
            worker_id="test-worker",
        )
        await db_session.commit()

        # Check audit record was created
        await db_session.refresh(existing_document, ["state_audit_records"])
        assert len(existing_document.state_audit_records) == 1
        audit = existing_document.state_audit_records[0]
        assert audit.previous_state == DocumentStatus.REGISTERED
        assert audit.new_state == DocumentStatus.PROCESSING
        assert audit.worker_id == "test-worker"

    @pytest.mark.asyncio
    async def test_update_status_with_error_message(self, db_session, existing_document):
        """Test status update with error message."""
        repository = DocumentRepository(db_session)

        # First move to processing
        await repository.update_status(
            document_id=existing_document.document_id,
            new_status=DocumentStatus.PROCESSING,
            worker_id="test-worker",
        )
        await db_session.commit()

        # Then fail with error
        document, success = await repository.update_status(
            document_id=existing_document.document_id,
            new_status=DocumentStatus.FAILED,
            worker_id="test-worker",
            error_message="PDF parsing failed",
        )

        assert success is True
        assert document.status == DocumentStatus.FAILED
        assert document.error_message == "PDF parsing failed"

    @pytest.mark.asyncio
    async def test_update_status_with_artifact_pointers(self, db_session, existing_document):
        """Test status update with artifact pointers."""
        repository = DocumentRepository(db_session)

        document, success = await repository.update_status(
            document_id=existing_document.document_id,
            new_status=DocumentStatus.PROCESSING,
            worker_id="test-worker",
            artifact_pointers={"pdf": "documents/test.pdf"},
        )

        assert success is True
        assert document.artifact_pointers["pdf"] == "documents/test.pdf"

    @pytest.mark.asyncio
    async def test_update_status_not_found(self, db_session):
        """Test status update for non-existent document."""
        repository = DocumentRepository(db_session)

        document, success = await repository.update_status(
            document_id=uuid4(),
            new_status=DocumentStatus.PROCESSING,
            worker_id="test-worker",
        )

        assert success is False
        assert document is None

    @pytest.mark.asyncio
    async def test_update_status_sets_last_processed_at_for_terminal_states(
        self, db_session, existing_document
    ):
        """Test that terminal states set last_processed_at."""
        repository = DocumentRepository(db_session)

        # Move to processing first
        await repository.update_status(
            document_id=existing_document.document_id,
            new_status=DocumentStatus.PROCESSING,
            worker_id="test-worker",
        )
        await db_session.commit()

        # Move to indexed (terminal state)
        document, success = await repository.update_status(
            document_id=existing_document.document_id,
            new_status=DocumentStatus.INDEXED,
            worker_id="test-worker",
        )

        assert success is True
        assert document.last_processed_at is not None


class TestProvenance:
    """Tests for provenance operations."""

    @pytest.mark.asyncio
    async def test_add_provenance(self, db_session, existing_document):
        """Test adding provenance record."""
        repository = DocumentRepository(db_session)
        user_id = uuid4()

        provenance = await repository.add_provenance(
            document_id=existing_document.document_id,
            source="crossref",
            user_id=user_id,
            metadata_snapshot={"source_field": "value"},
            source_query="solar wind",
        )

        assert provenance.provenance_id is not None
        assert provenance.source == "crossref"
        assert provenance.user_id == user_id
        assert provenance.source_query == "solar wind"
        assert provenance.metadata_snapshot["source_field"] == "value"

    @pytest.mark.asyncio
    async def test_add_provenance_with_upload_id(self, db_session, existing_document):
        """Test adding provenance with upload ID."""
        repository = DocumentRepository(db_session)
        user_id = uuid4()
        upload_id = uuid4()

        provenance = await repository.add_provenance(
            document_id=existing_document.document_id,
            source="upload",
            user_id=user_id,
            metadata_snapshot={},
            upload_id=upload_id,
        )

        assert provenance.upload_id == upload_id
        assert provenance.source == "upload"

    @pytest.mark.asyncio
    async def test_add_provenance_with_connector_job_id(self, db_session, existing_document):
        """Test adding provenance with connector job ID."""
        repository = DocumentRepository(db_session)
        user_id = uuid4()
        connector_job_id = uuid4()

        provenance = await repository.add_provenance(
            document_id=existing_document.document_id,
            source="arxiv",
            user_id=user_id,
            metadata_snapshot={},
            connector_job_id=connector_job_id,
        )

        assert provenance.connector_job_id == connector_job_id


class TestMetadataMerge:
    """Tests for metadata merge operations."""

    @pytest.mark.asyncio
    async def test_merge_metadata(self, db_session, existing_document):
        """Test merging metadata into document."""
        repository = DocumentRepository(db_session)

        new_metadata = {"new_key": "new_value", "another_key": 123}
        document = await repository.merge_metadata(existing_document, new_metadata)

        assert "new_key" in document.source_metadata
        assert document.source_metadata["new_key"] == "new_value"
        assert document.source_metadata["another_key"] == 123

    @pytest.mark.asyncio
    async def test_merge_metadata_overwrites_existing(self, db_session, existing_document):
        """Test that merge overwrites existing keys."""
        repository = DocumentRepository(db_session)

        # Add initial metadata
        existing_document.source_metadata = {"key1": "old_value"}
        await db_session.flush()

        # Merge with new value
        new_metadata = {"key1": "new_value"}
        document = await repository.merge_metadata(existing_document, new_metadata)

        assert document.source_metadata["key1"] == "new_value"


class TestDocumentListing:
    """Tests for document listing."""

    @pytest.mark.asyncio
    async def test_list_documents(self, db_session):
        """Test listing documents."""
        repository = DocumentRepository(db_session)

        # Create a few documents
        for i in range(3):
            doc, _ = await repository.create(
                doi=f"10.1234/list.{i}",
                content_hash=None,
                title=f"List Document {i}",
                title_normalized=f"list document {i}",
                authors=[],
            )
        await db_session.commit()

        documents = await repository.list_documents()

        assert len(documents) >= 3

    @pytest.mark.asyncio
    async def test_list_documents_with_status_filter(self, db_session):
        """Test listing documents with status filter."""
        repository = DocumentRepository(db_session)

        # Create documents with different statuses
        doc1, _ = await repository.create(
            doi="10.1234/status.1",
            content_hash=None,
            title="Status Document 1",
            title_normalized="status document 1",
            authors=[],
        )
        await db_session.commit()

        # Move one to processing
        await repository.update_status(
            document_id=doc1.document_id,
            new_status=DocumentStatus.PROCESSING,
            worker_id="test",
        )
        await db_session.commit()

        doc2, _ = await repository.create(
            doi="10.1234/status.2",
            content_hash=None,
            title="Status Document 2",
            title_normalized="status document 2",
            authors=[],
        )
        await db_session.commit()

        # List only registered
        documents = await repository.list_documents(status=DocumentStatus.REGISTERED)

        # Should not include the processing one
        doc_ids = [d.document_id for d in documents]
        assert doc1.document_id not in doc_ids

    @pytest.mark.asyncio
    async def test_list_documents_with_limit(self, db_session):
        """Test listing documents with limit."""
        repository = DocumentRepository(db_session)

        # Create more documents than limit
        for i in range(5):
            await repository.create(
                doi=f"10.1234/limit.{i}",
                content_hash=None,
                title=f"Limit Document {i}",
                title_normalized=f"limit document {i}",
                authors=[],
            )
        await db_session.commit()

        documents = await repository.list_documents(limit=2)

        assert len(documents) == 2

    @pytest.mark.asyncio
    async def test_list_documents_with_offset(self, db_session):
        """Test listing documents with offset."""
        repository = DocumentRepository(db_session)

        # Create documents
        for i in range(5):
            await repository.create(
                doi=f"10.1234/offset.{i}",
                content_hash=None,
                title=f"Offset Document {i}",
                title_normalized=f"offset document {i}",
                authors=[],
            )
        await db_session.commit()

        documents_page1 = await repository.list_documents(limit=2, offset=0)
        documents_page2 = await repository.list_documents(limit=2, offset=2)

        # Should be different documents
        ids_page1 = {d.document_id for d in documents_page1}
        ids_page2 = {d.document_id for d in documents_page2}
        assert ids_page1.isdisjoint(ids_page2)


class TestFuzzyMatchCandidates:
    """Tests for fuzzy match candidate retrieval."""

    @pytest.mark.asyncio
    async def test_find_candidates_for_fuzzy_match(self, db_session):
        """Test finding candidates for fuzzy matching by year."""
        repository = DocumentRepository(db_session)

        # Create documents with different years
        for i, year in enumerate([2020, 2020, 2021, 2021, 2021]):
            await repository.create(
                doi=f"10.1234/fuzzy.{i}",
                content_hash=None,
                title=f"Fuzzy Document {i}",
                title_normalized=f"fuzzy document {i}",
                authors=[],
                year=year,
            )
        await db_session.commit()

        candidates_2020 = await repository.find_candidates_for_fuzzy_match(year=2020)
        candidates_2021 = await repository.find_candidates_for_fuzzy_match(year=2021)

        assert len(candidates_2020) == 2
        assert len(candidates_2021) == 3

    @pytest.mark.asyncio
    async def test_find_candidates_with_limit(self, db_session):
        """Test finding candidates with limit."""
        repository = DocumentRepository(db_session)

        # Create many documents
        for i in range(10):
            await repository.create(
                doi=f"10.1234/limit.fuzzy.{i}",
                content_hash=None,
                title=f"Limit Fuzzy Document {i}",
                title_normalized=f"limit fuzzy document {i}",
                authors=[],
                year=2023,
            )
        await db_session.commit()

        candidates = await repository.find_candidates_for_fuzzy_match(year=2023, limit=5)

        assert len(candidates) == 5

    @pytest.mark.asyncio
    async def test_find_candidates_no_match_year(self, db_session):
        """Test finding candidates with no matching year."""
        repository = DocumentRepository(db_session)

        candidates = await repository.find_candidates_for_fuzzy_match(year=1900)

        assert len(candidates) == 0


class TestArtifactPointers:
    """Tests for artifact pointer updates."""

    @pytest.mark.asyncio
    async def test_update_artifact_pointers(self, db_session, existing_document):
        """Test updating artifact pointers."""
        repository = DocumentRepository(db_session)

        success = await repository.update_artifact_pointers(
            document_id=existing_document.document_id,
            artifact_pointers={
                "pdf": "documents/test.pdf",
                "markdown": "documents/test.md",
            }
        )

        assert success is True

        # Refresh and check
        await db_session.refresh(existing_document)
        assert existing_document.artifact_pointers["pdf"] == "documents/test.pdf"
        assert existing_document.artifact_pointers["markdown"] == "documents/test.md"

    @pytest.mark.asyncio
    async def test_update_artifact_pointers_not_found(self, db_session):
        """Test updating artifact pointers for non-existent document."""
        repository = DocumentRepository(db_session)

        success = await repository.update_artifact_pointers(
            document_id=uuid4(),
            artifact_pointers={"pdf": "test.pdf"}
        )

        assert success is False
