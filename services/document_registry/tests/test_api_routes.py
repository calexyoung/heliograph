"""Tests for Document Registry API routes."""

from uuid import uuid4

import pytest

from shared.schemas.document import DocumentStatus


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    @pytest.mark.asyncio
    async def test_health_check(self, test_client):
        """Test health check returns healthy status."""
        response = await test_client.get("/registry/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "document-registry"

    @pytest.mark.asyncio
    async def test_readiness_check(self, test_client):
        """Test readiness check returns ready status."""
        response = await test_client.get("/registry/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True
        assert "database" in data["checks"]


class TestDocumentRegistration:
    """Tests for document registration endpoint."""

    @pytest.mark.asyncio
    async def test_register_new_document_with_doi(self, test_client, mock_sqs_client):
        """Test registering a new document with DOI."""
        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/test.2024.001",
            "title": "Test Document Title",
            "authors": [
                {"given_name": "John", "family_name": "Doe"}
            ],
            "journal": "Journal of Testing",
            "year": 2024,
            "source": "crossref",
            "user_id": user_id,
        }

        response = await test_client.post("/registry/documents", json=request_data)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert "document_id" in data
        # Verify SQS was called
        mock_sqs_client.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_new_document_with_content_hash(self, test_client, mock_sqs_client):
        """Test registering a new document with content hash."""
        user_id = str(uuid4())
        request_data = {
            "content_hash": "a" * 64,
            "title": "Test Document with Hash",
            "authors": [],
            "source": "upload",
            "user_id": user_id,
            "upload_id": str(uuid4()),
        }

        response = await test_client.post("/registry/documents", json=request_data)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert "document_id" in data

    @pytest.mark.asyncio
    async def test_register_document_requires_doi_or_hash(self, test_client):
        """Test that registration fails without DOI or content hash."""
        user_id = str(uuid4())
        request_data = {
            "title": "Test Document",
            "authors": [],
            "source": "upload",
            "user_id": user_id,
        }

        response = await test_client.post("/registry/documents", json=request_data)

        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_register_duplicate_doi_returns_existing(self, test_client, mock_sqs_client):
        """Test that duplicate DOI returns existing document."""
        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/duplicate.test",
            "title": "Original Document",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }

        # First registration
        response1 = await test_client.post("/registry/documents", json=request_data)
        assert response1.status_code == 200
        original_id = response1.json()["document_id"]

        # Reset mock for second call
        mock_sqs_client.send_message.reset_mock()

        # Second registration with same DOI
        request_data["title"] = "Different Title"
        response2 = await test_client.post("/registry/documents", json=request_data)

        assert response2.status_code == 200
        data = response2.json()
        assert data["status"] == "duplicate"
        assert data["existing_document_id"] == original_id

    @pytest.mark.asyncio
    async def test_register_invalid_content_hash_format(self, test_client):
        """Test that invalid content hash format is rejected."""
        user_id = str(uuid4())
        request_data = {
            "content_hash": "not-a-valid-hex-string",
            "title": "Test Document",
            "authors": [],
            "source": "upload",
            "user_id": user_id,
        }

        response = await test_client.post("/registry/documents", json=request_data)

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_invalid_source(self, test_client):
        """Test that invalid source is rejected."""
        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/test",
            "title": "Test Document",
            "authors": [],
            "source": "invalid_source",
            "user_id": user_id,
        }

        response = await test_client.post("/registry/documents", json=request_data)

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_event_publish_failure_returns_503(self, test_client, mock_sqs_client):
        """Test that event publish failure returns 503."""
        mock_sqs_client.send_message.return_value = None  # Simulate failure

        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/event.fail.test",
            "title": "Test Document",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }

        response = await test_client.post("/registry/documents", json=request_data)

        assert response.status_code == 503
        data = response.json()
        assert data["detail"]["error_code"] == "EVENT_PUBLISH_FAILED"


class TestDocumentRetrieval:
    """Tests for document retrieval endpoints."""

    @pytest.mark.asyncio
    async def test_get_document_by_id(self, test_client, mock_sqs_client):
        """Test retrieving a document by ID."""
        # First create a document
        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/get.test",
            "title": "Test Document for Get",
            "authors": [{"given_name": "Test", "family_name": "Author"}],
            "source": "crossref",
            "user_id": user_id,
        }

        create_response = await test_client.post("/registry/documents", json=request_data)
        document_id = create_response.json()["document_id"]

        # Now retrieve it
        response = await test_client.get(f"/registry/documents/{document_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["document_id"] == document_id
        assert data["doi"] == "10.1234/get.test"
        assert data["title"] == "Test Document for Get"
        assert data["status"] == "registered"
        assert len(data["provenance"]) == 1

    @pytest.mark.asyncio
    async def test_get_document_not_found(self, test_client):
        """Test that non-existent document returns 404."""
        fake_id = str(uuid4())
        response = await test_client.get(f"/registry/documents/{fake_id}")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error_code"] == "DOCUMENT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_list_documents(self, test_client, mock_sqs_client):
        """Test listing documents."""
        user_id = str(uuid4())

        # Create a few documents
        for i in range(3):
            request_data = {
                "doi": f"10.1234/list.test.{i}",
                "title": f"List Test Document {i}",
                "authors": [],
                "source": "crossref",
                "user_id": user_id,
            }
            await test_client.post("/registry/documents", json=request_data)

        response = await test_client.get("/registry/documents")

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 3

    @pytest.mark.asyncio
    async def test_list_documents_with_status_filter(self, test_client, mock_sqs_client):
        """Test listing documents with status filter."""
        user_id = str(uuid4())

        # Create a document
        request_data = {
            "doi": "10.1234/filter.test",
            "title": "Filter Test Document",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }
        await test_client.post("/registry/documents", json=request_data)

        response = await test_client.get(
            "/registry/documents",
            params={"status": "registered"}
        )

        assert response.status_code == 200
        data = response.json()
        assert all(doc["status"] == "registered" for doc in data)

    @pytest.mark.asyncio
    async def test_list_documents_with_pagination(self, test_client, mock_sqs_client):
        """Test listing documents with pagination."""
        response = await test_client.get(
            "/registry/documents",
            params={"limit": 2, "offset": 0}
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 2


class TestStateTransition:
    """Tests for state transition endpoint."""

    @pytest.mark.asyncio
    async def test_valid_state_transition(self, test_client, mock_sqs_client):
        """Test valid state transition from registered to processing."""
        # Create a document
        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/state.test",
            "title": "State Test Document",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }
        create_response = await test_client.post("/registry/documents", json=request_data)
        document_id = create_response.json()["document_id"]

        # Transition to processing
        transition_data = {
            "state": "processing",
            "worker_id": "test-worker-1",
            "expected_state": "registered",
        }
        response = await test_client.post(
            f"/registry/documents/{document_id}/state",
            json=transition_data
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["previous_state"] == "registered"
        assert data["new_state"] == "processing"

    @pytest.mark.asyncio
    async def test_invalid_state_transition(self, test_client, mock_sqs_client):
        """Test invalid state transition (registered -> indexed)."""
        # Create a document
        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/invalid.state.test",
            "title": "Invalid State Test Document",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }
        create_response = await test_client.post("/registry/documents", json=request_data)
        document_id = create_response.json()["document_id"]

        # Try invalid transition
        transition_data = {
            "state": "indexed",  # Cannot go directly from registered to indexed
            "worker_id": "test-worker-1",
        }
        response = await test_client.post(
            f"/registry/documents/{document_id}/state",
            json=transition_data
        )

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["error_code"] == "INVALID_STATE_TRANSITION"

    @pytest.mark.asyncio
    async def test_state_transition_with_optimistic_lock_conflict(self, test_client, mock_sqs_client):
        """Test state transition fails with wrong expected state."""
        # Create a document
        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/lock.conflict.test",
            "title": "Lock Conflict Test Document",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }
        create_response = await test_client.post("/registry/documents", json=request_data)
        document_id = create_response.json()["document_id"]

        # Try transition with wrong expected state
        transition_data = {
            "state": "processing",
            "worker_id": "test-worker-1",
            "expected_state": "processing",  # Wrong - it's actually 'registered'
        }
        response = await test_client.post(
            f"/registry/documents/{document_id}/state",
            json=transition_data
        )

        assert response.status_code == 409
        data = response.json()
        assert data["detail"]["error_code"] == "STATE_CONFLICT"

    @pytest.mark.asyncio
    async def test_state_transition_to_failed_requires_error_message(self, test_client, mock_sqs_client):
        """Test transitioning to failed state requires error message."""
        # Create and move to processing
        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/failed.test",
            "title": "Failed State Test Document",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }
        create_response = await test_client.post("/registry/documents", json=request_data)
        document_id = create_response.json()["document_id"]

        # Move to processing first
        await test_client.post(
            f"/registry/documents/{document_id}/state",
            json={"state": "processing", "worker_id": "test-worker-1"}
        )

        # Try to fail without error message
        transition_data = {
            "state": "failed",
            "worker_id": "test-worker-1",
            # Missing error_message
        }
        response = await test_client.post(
            f"/registry/documents/{document_id}/state",
            json=transition_data
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_state_transition_to_failed_with_error_message(self, test_client, mock_sqs_client):
        """Test transitioning to failed state with error message."""
        # Create and move to processing
        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/failed.success.test",
            "title": "Failed Success Test Document",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }
        create_response = await test_client.post("/registry/documents", json=request_data)
        document_id = create_response.json()["document_id"]

        # Move to processing first
        await test_client.post(
            f"/registry/documents/{document_id}/state",
            json={"state": "processing", "worker_id": "test-worker-1"}
        )

        # Now fail with error message
        transition_data = {
            "state": "failed",
            "worker_id": "test-worker-1",
            "error_message": "PDF parsing failed: corrupt file",
        }
        response = await test_client.post(
            f"/registry/documents/{document_id}/state",
            json=transition_data
        )

        assert response.status_code == 200
        data = response.json()
        assert data["new_state"] == "failed"

    @pytest.mark.asyncio
    async def test_state_transition_with_artifact_pointers(self, test_client, mock_sqs_client):
        """Test state transition with artifact pointers update."""
        # Create and move to processing
        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/artifacts.test",
            "title": "Artifacts Test Document",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }
        create_response = await test_client.post("/registry/documents", json=request_data)
        document_id = create_response.json()["document_id"]

        # Move to processing first
        await test_client.post(
            f"/registry/documents/{document_id}/state",
            json={"state": "processing", "worker_id": "test-worker-1"}
        )

        # Move to indexed with artifacts
        transition_data = {
            "state": "indexed",
            "worker_id": "test-worker-1",
            "artifact_pointers": {
                "pdf": f"documents/{document_id}/document.pdf",
                "markdown": f"documents/{document_id}/content.md",
            },
        }
        response = await test_client.post(
            f"/registry/documents/{document_id}/state",
            json=transition_data
        )

        assert response.status_code == 200

        # Verify artifacts were saved
        doc_response = await test_client.get(f"/registry/documents/{document_id}")
        doc_data = doc_response.json()
        assert "pdf" in doc_data["artifact_pointers"]
        assert "markdown" in doc_data["artifact_pointers"]

    @pytest.mark.asyncio
    async def test_state_transition_document_not_found(self, test_client):
        """Test state transition for non-existent document."""
        fake_id = str(uuid4())
        transition_data = {
            "state": "processing",
            "worker_id": "test-worker-1",
        }
        response = await test_client.post(
            f"/registry/documents/{fake_id}/state",
            json=transition_data
        )

        assert response.status_code == 404


class TestDocumentUpdate:
    """Tests for document update endpoint."""

    @pytest.mark.asyncio
    async def test_update_artifact_pointers(self, test_client, mock_sqs_client):
        """Test updating document artifact pointers."""
        # Create a document
        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/update.test",
            "title": "Update Test Document",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }
        create_response = await test_client.post("/registry/documents", json=request_data)
        document_id = create_response.json()["document_id"]

        # Update artifact pointers
        update_data = {
            "artifact_pointers": {
                "pdf": f"documents/{document_id}/document.pdf",
            }
        }
        response = await test_client.patch(
            f"/registry/documents/{document_id}",
            params=update_data
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_update_document_not_found(self, test_client):
        """Test updating non-existent document."""
        fake_id = str(uuid4())
        response = await test_client.patch(
            f"/registry/documents/{fake_id}",
            params={"artifact_pointers": {"pdf": "test.pdf"}}
        )

        assert response.status_code == 404
