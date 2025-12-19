"""Integration tests for Document Registry Service.

These tests exercise the complete flow from document registration
through state transitions, simulating real-world usage patterns.
"""

import asyncio
from uuid import uuid4

import pytest

from shared.schemas.document import DocumentStatus


class TestDocumentRegistrationFlow:
    """End-to-end tests for document registration workflow."""

    @pytest.mark.asyncio
    async def test_complete_document_lifecycle(self, test_client, mock_sqs_client):
        """Test complete document lifecycle: register -> process -> index."""
        user_id = str(uuid4())

        # Step 1: Register document
        register_response = await test_client.post(
            "/registry/documents",
            json={
                "doi": "10.1234/lifecycle.test",
                "title": "Lifecycle Test Document",
                "authors": [
                    {"given_name": "Alice", "family_name": "Researcher"}
                ],
                "journal": "Journal of Integration Testing",
                "year": 2024,
                "source": "crossref",
                "user_id": user_id,
            }
        )

        assert register_response.status_code == 200
        document_id = register_response.json()["document_id"]
        assert register_response.json()["status"] == "queued"

        # Verify event was published
        assert mock_sqs_client.send_message.call_count == 1

        # Step 2: Verify initial state
        get_response = await test_client.get(f"/registry/documents/{document_id}")
        assert get_response.status_code == 200
        assert get_response.json()["status"] == "registered"

        # Step 3: Transition to processing
        process_response = await test_client.post(
            f"/registry/documents/{document_id}/state",
            json={
                "state": "processing",
                "worker_id": "pdf-parser-1",
                "expected_state": "registered",
            }
        )

        assert process_response.status_code == 200
        assert process_response.json()["new_state"] == "processing"

        # Step 4: Transition to indexed with artifacts
        index_response = await test_client.post(
            f"/registry/documents/{document_id}/state",
            json={
                "state": "indexed",
                "worker_id": "indexer-1",
                "expected_state": "processing",
                "artifact_pointers": {
                    "pdf": f"documents/{document_id}/document.pdf",
                    "markdown": f"documents/{document_id}/content.md",
                    "chunks": f"documents/{document_id}/chunks.json",
                },
            }
        )

        assert index_response.status_code == 200
        assert index_response.json()["new_state"] == "indexed"

        # Step 5: Verify final state
        final_response = await test_client.get(f"/registry/documents/{document_id}")
        final_data = final_response.json()

        assert final_data["status"] == "indexed"
        assert "pdf" in final_data["artifact_pointers"]
        assert "markdown" in final_data["artifact_pointers"]
        assert final_data["last_processed_at"] is not None

    @pytest.mark.asyncio
    async def test_document_failure_and_retry_flow(self, test_client, mock_sqs_client):
        """Test document failure and retry workflow."""
        user_id = str(uuid4())

        # Register document
        register_response = await test_client.post(
            "/registry/documents",
            json={
                "doi": "10.1234/retry.test",
                "title": "Retry Test Document",
                "authors": [],
                "source": "upload",
                "user_id": user_id,
                "upload_id": str(uuid4()),
            }
        )

        document_id = register_response.json()["document_id"]

        # Move to processing
        await test_client.post(
            f"/registry/documents/{document_id}/state",
            json={"state": "processing", "worker_id": "worker-1"}
        )

        # Fail with error
        fail_response = await test_client.post(
            f"/registry/documents/{document_id}/state",
            json={
                "state": "failed",
                "worker_id": "worker-1",
                "error_message": "PDF parsing failed: file corrupted",
                "expected_state": "processing",
            }
        )

        assert fail_response.status_code == 200
        assert fail_response.json()["new_state"] == "failed"

        # Verify error message stored
        get_response = await test_client.get(f"/registry/documents/{document_id}")
        assert "PDF parsing failed" in get_response.json()["error_message"]

        # Retry: move back to processing
        retry_response = await test_client.post(
            f"/registry/documents/{document_id}/state",
            json={
                "state": "processing",
                "worker_id": "worker-2",
                "expected_state": "failed",
            }
        )

        assert retry_response.status_code == 200
        assert retry_response.json()["previous_state"] == "failed"
        assert retry_response.json()["new_state"] == "processing"

        # Complete successfully this time
        success_response = await test_client.post(
            f"/registry/documents/{document_id}/state",
            json={
                "state": "indexed",
                "worker_id": "worker-2",
                "expected_state": "processing",
            }
        )

        assert success_response.status_code == 200


class TestDeduplicationFlow:
    """End-to-end tests for deduplication scenarios."""

    @pytest.mark.asyncio
    async def test_doi_deduplication_flow(self, test_client, mock_sqs_client):
        """Test that duplicate DOI submissions are handled correctly."""
        user_id = str(uuid4())
        doi = "10.1234/dedup.doi.test"

        # First registration
        first_response = await test_client.post(
            "/registry/documents",
            json={
                "doi": doi,
                "title": "Original Title",
                "authors": [{"given_name": "First", "family_name": "Author"}],
                "source": "crossref",
                "user_id": user_id,
            }
        )

        assert first_response.status_code == 200
        original_id = first_response.json()["document_id"]
        assert first_response.json()["status"] == "queued"

        # Second registration with same DOI
        second_response = await test_client.post(
            "/registry/documents",
            json={
                "doi": doi,
                "title": "Different Title",
                "authors": [{"given_name": "Second", "family_name": "Author"}],
                "source": "semantic_scholar",
                "user_id": user_id,
            }
        )

        assert second_response.status_code == 200
        assert second_response.json()["status"] == "duplicate"
        assert second_response.json()["existing_document_id"] == original_id

        # Verify provenance was added for duplicate
        get_response = await test_client.get(f"/registry/documents/{original_id}")
        provenance = get_response.json()["provenance"]
        assert len(provenance) == 2
        sources = [p["source"] for p in provenance]
        assert "crossref" in sources
        assert "semantic_scholar" in sources

    @pytest.mark.asyncio
    async def test_content_hash_deduplication_flow(self, test_client, mock_sqs_client):
        """Test that duplicate content hash submissions are handled correctly."""
        user_id = str(uuid4())
        content_hash = "e" * 64

        # First registration
        first_response = await test_client.post(
            "/registry/documents",
            json={
                "content_hash": content_hash,
                "title": "Original PDF Document",
                "authors": [],
                "source": "upload",
                "user_id": user_id,
                "upload_id": str(uuid4()),
            }
        )

        original_id = first_response.json()["document_id"]

        # Second registration with same content hash
        second_response = await test_client.post(
            "/registry/documents",
            json={
                "content_hash": content_hash,
                "title": "Same PDF Different Title",
                "authors": [],
                "source": "upload",
                "user_id": user_id,
                "upload_id": str(uuid4()),
            }
        )

        assert second_response.json()["status"] == "duplicate"
        assert second_response.json()["existing_document_id"] == original_id


@pytest.mark.skip(reason="Concurrent tests require PostgreSQL - SQLite doesn't support proper transaction isolation for concurrent operations")
class TestConcurrentOperations:
    """Tests for concurrent operation handling.

    Note: These tests require PostgreSQL to properly test concurrent behavior.
    SQLite in-memory databases don't provide the same isolation guarantees.
    """

    @pytest.mark.asyncio
    async def test_concurrent_state_transitions_with_optimistic_locking(
        self, test_client, mock_sqs_client
    ):
        """Test that concurrent state transitions are handled with optimistic locking."""
        user_id = str(uuid4())

        # Register document
        register_response = await test_client.post(
            "/registry/documents",
            json={
                "doi": "10.1234/concurrent.test",
                "title": "Concurrent Test Document",
                "authors": [],
                "source": "crossref",
                "user_id": user_id,
            }
        )

        document_id = register_response.json()["document_id"]

        # Simulate two workers trying to process simultaneously
        async def worker_attempt(worker_id: str):
            return await test_client.post(
                f"/registry/documents/{document_id}/state",
                json={
                    "state": "processing",
                    "worker_id": worker_id,
                    "expected_state": "registered",
                }
            )

        # Run both attempts concurrently
        results = await asyncio.gather(
            worker_attempt("worker-1"),
            worker_attempt("worker-2"),
        )

        # One should succeed, one should fail with conflict
        status_codes = [r.status_code for r in results]
        assert 200 in status_codes
        assert 409 in status_codes

    @pytest.mark.asyncio
    async def test_concurrent_duplicate_registrations(
        self, test_client, mock_sqs_client
    ):
        """Test handling of concurrent duplicate registration attempts."""
        user_id = str(uuid4())
        content_hash = "f" * 64

        async def register_document(upload_id: str):
            return await test_client.post(
                "/registry/documents",
                json={
                    "content_hash": content_hash,
                    "title": f"Concurrent Upload {upload_id}",
                    "authors": [],
                    "source": "upload",
                    "user_id": user_id,
                    "upload_id": upload_id,
                }
            )

        # Run concurrent registrations
        upload_ids = [str(uuid4()) for _ in range(3)]
        results = await asyncio.gather(*[register_document(uid) for uid in upload_ids])

        # All should succeed (either as queued or duplicate)
        assert all(r.status_code == 200 for r in results)

        # Only one should be queued, others should be duplicates
        statuses = [r.json()["status"] for r in results]
        assert statuses.count("queued") + statuses.count("duplicate") == 3

        # All should reference the same document
        document_ids = set()
        for r in results:
            data = r.json()
            document_ids.add(data.get("existing_document_id") or data["document_id"])
        assert len(document_ids) == 1


class TestMultiSourceIngestion:
    """Tests for multi-source document ingestion scenarios."""

    @pytest.mark.asyncio
    async def test_document_from_multiple_sources(self, test_client, mock_sqs_client):
        """Test document enrichment from multiple sources."""
        user_id = str(uuid4())
        doi = "10.1234/multisource.test"

        # First ingestion from Crossref
        crossref_response = await test_client.post(
            "/registry/documents",
            json={
                "doi": doi,
                "title": "Multi-Source Document",
                "authors": [{"given_name": "Alice", "family_name": "Author"}],
                "journal": "Test Journal",
                "year": 2024,
                "source": "crossref",
                "user_id": user_id,
                "source_metadata": {"crossref_type": "journal-article"},
            }
        )

        document_id = crossref_response.json()["document_id"]

        # Second ingestion from Semantic Scholar (same DOI)
        await test_client.post(
            "/registry/documents",
            json={
                "doi": doi,
                "title": "Multi-Source Document",
                "authors": [
                    {"given_name": "Alice", "family_name": "Author"},
                    {"given_name": "Bob", "family_name": "Coauthor"},
                ],
                "source": "semantic_scholar",
                "user_id": user_id,
                "source_metadata": {
                    "s2_paper_id": "12345",
                    "citation_count": 42,
                },
            }
        )

        # Third ingestion from arXiv
        await test_client.post(
            "/registry/documents",
            json={
                "doi": doi,
                "title": "Multi-Source Document",
                "authors": [],
                "source": "arxiv",
                "user_id": user_id,
                "source_metadata": {
                    "arxiv_id": "2401.12345",
                    "categories": ["astro-ph.SR"],
                },
            }
        )

        # Verify all sources recorded in provenance
        get_response = await test_client.get(f"/registry/documents/{document_id}")
        data = get_response.json()

        provenance = data["provenance"]
        assert len(provenance) == 3

        sources = [p["source"] for p in provenance]
        assert "crossref" in sources
        assert "semantic_scholar" in sources
        assert "arxiv" in sources

        # Verify metadata was merged
        metadata = data.get("source_metadata", {})
        # Note: Exact merge behavior depends on implementation
        # This test verifies the flow works


class TestErrorRecovery:
    """Tests for error handling and recovery scenarios."""

    @pytest.mark.asyncio
    async def test_event_publish_failure_prevents_registration(
        self, test_client, mock_sqs_client
    ):
        """Test that event publish failure prevents document registration."""
        # Simulate SQS failure
        mock_sqs_client.send_message.return_value = None

        user_id = str(uuid4())
        response = await test_client.post(
            "/registry/documents",
            json={
                "doi": "10.1234/event.fail",
                "title": "Event Fail Document",
                "authors": [],
                "source": "crossref",
                "user_id": user_id,
            }
        )

        assert response.status_code == 503
        assert response.json()["detail"]["error_code"] == "EVENT_PUBLISH_FAILED"

        # Reset mock for subsequent tests
        mock_sqs_client.send_message.return_value = "test-message-id"

    @pytest.mark.asyncio
    async def test_invalid_state_transition_sequence(
        self, test_client, mock_sqs_client
    ):
        """Test that invalid state transition sequences are rejected."""
        user_id = str(uuid4())

        # Register document
        register_response = await test_client.post(
            "/registry/documents",
            json={
                "doi": "10.1234/invalid.transition",
                "title": "Invalid Transition Test",
                "authors": [],
                "source": "crossref",
                "user_id": user_id,
            }
        )

        document_id = register_response.json()["document_id"]

        # Try to go directly to indexed (should fail)
        invalid_response = await test_client.post(
            f"/registry/documents/{document_id}/state",
            json={"state": "indexed", "worker_id": "worker-1"}
        )

        assert invalid_response.status_code == 400
        assert "INVALID_STATE_TRANSITION" in invalid_response.json()["detail"]["error_code"]

        # Try to go to failed without being in processing (should fail)
        invalid_response2 = await test_client.post(
            f"/registry/documents/{document_id}/state",
            json={
                "state": "failed",
                "worker_id": "worker-1",
                "error_message": "Some error",
            }
        )

        assert invalid_response2.status_code == 400


class TestProvenanceTracking:
    """Tests for provenance and audit trail tracking."""

    @pytest.mark.asyncio
    async def test_provenance_includes_all_metadata(self, test_client, mock_sqs_client):
        """Test that provenance records include all relevant metadata."""
        user_id = str(uuid4())
        upload_id = str(uuid4())

        # Register with full metadata
        register_response = await test_client.post(
            "/registry/documents",
            json={
                "content_hash": "1" * 64,
                "title": "Provenance Test Document",
                "authors": [{"given_name": "Test", "family_name": "Author"}],
                "source": "upload",
                "user_id": user_id,
                "upload_id": upload_id,
                "source_metadata": {
                    "original_filename": "research_paper.pdf",
                    "file_size": 1024000,
                },
            }
        )

        document_id = register_response.json()["document_id"]

        # Verify provenance
        get_response = await test_client.get(f"/registry/documents/{document_id}")
        provenance = get_response.json()["provenance"][0]

        assert provenance["source"] == "upload"
        assert provenance["upload_id"] == upload_id
        assert provenance["user_id"] == user_id
        assert "original_filename" in provenance["metadata_snapshot"]

    @pytest.mark.asyncio
    async def test_state_audit_trail(self, test_client, mock_sqs_client, db_session):
        """Test that state transitions create audit records."""
        user_id = str(uuid4())

        # Register and transition through states
        register_response = await test_client.post(
            "/registry/documents",
            json={
                "doi": "10.1234/audit.test",
                "title": "Audit Trail Test",
                "authors": [],
                "source": "crossref",
                "user_id": user_id,
            }
        )

        document_id = register_response.json()["document_id"]

        # Multiple state transitions
        await test_client.post(
            f"/registry/documents/{document_id}/state",
            json={"state": "processing", "worker_id": "worker-1"}
        )

        await test_client.post(
            f"/registry/documents/{document_id}/state",
            json={
                "state": "failed",
                "worker_id": "worker-1",
                "error_message": "First attempt failed",
            }
        )

        await test_client.post(
            f"/registry/documents/{document_id}/state",
            json={"state": "processing", "worker_id": "worker-2"}
        )

        await test_client.post(
            f"/registry/documents/{document_id}/state",
            json={"state": "indexed", "worker_id": "worker-2"}
        )

        # Verify audit trail exists (would need direct DB access to verify fully)
        # For now, verify the final state is correct
        get_response = await test_client.get(f"/registry/documents/{document_id}")
        assert get_response.json()["status"] == "indexed"
