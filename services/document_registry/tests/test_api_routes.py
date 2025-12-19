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

    @pytest.mark.asyncio
    async def test_list_documents_paginated_endpoint(self, test_client, mock_sqs_client):
        """Test cursor-based paginated endpoint."""
        user_id = str(uuid4())

        # Create several documents
        for i in range(5):
            request_data = {
                "doi": f"10.1234/paginated.test.{i}",
                "title": f"Paginated Test Document {i}",
                "authors": [],
                "source": "crossref",
                "user_id": user_id,
            }
            await test_client.post("/registry/documents", json=request_data)

        # Fetch first page
        response = await test_client.get(
            "/registry/documents/paginated",
            params={"limit": 2}
        )

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "limit" in data
        assert "has_more" in data
        assert len(data["items"]) <= 2
        assert data["limit"] == 2

    @pytest.mark.asyncio
    async def test_list_documents_paginated_with_cursor(self, test_client, mock_sqs_client):
        """Test paginated endpoint with cursor navigation."""
        user_id = str(uuid4())

        # Create several documents
        for i in range(5):
            request_data = {
                "doi": f"10.1234/cursor.test.{i}",
                "title": f"Cursor Test Document {i}",
                "authors": [],
                "source": "crossref",
                "user_id": user_id,
            }
            await test_client.post("/registry/documents", json=request_data)

        # Fetch first page
        response1 = await test_client.get(
            "/registry/documents/paginated",
            params={"limit": 2}
        )

        assert response1.status_code == 200
        data1 = response1.json()

        if data1["has_more"] and data1["next_cursor"]:
            # Fetch next page using cursor
            response2 = await test_client.get(
                "/registry/documents/paginated",
                params={"limit": 2, "cursor": data1["next_cursor"]}
            )

            assert response2.status_code == 200
            data2 = response2.json()
            assert len(data2["items"]) <= 2

            # Ensure no overlap between pages
            page1_ids = {item["document_id"] for item in data1["items"]}
            page2_ids = {item["document_id"] for item in data2["items"]}
            assert page1_ids.isdisjoint(page2_ids)

    @pytest.mark.asyncio
    async def test_list_documents_paginated_with_status_filter(self, test_client, mock_sqs_client):
        """Test paginated endpoint with status filter."""
        response = await test_client.get(
            "/registry/documents/paginated",
            params={"status": "registered", "limit": 10}
        )

        assert response.status_code == 200
        data = response.json()
        assert all(item["status"] == "registered" for item in data["items"])

    @pytest.mark.asyncio
    async def test_list_documents_paginated_invalid_cursor(self, test_client):
        """Test paginated endpoint with invalid cursor returns 400."""
        response = await test_client.get(
            "/registry/documents/paginated",
            params={"cursor": "not-valid-base64!"}
        )

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["error_code"] == "INVALID_CURSOR"


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


class TestSoftDelete:
    """Tests for soft delete functionality."""

    @pytest.mark.asyncio
    async def test_soft_delete_document(self, test_client, mock_sqs_client):
        """Test soft deleting a document."""
        # Create a document
        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/softdelete.test",
            "title": "Soft Delete Test Document",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }
        create_response = await test_client.post("/registry/documents", json=request_data)
        document_id = create_response.json()["document_id"]

        # Soft delete the document
        response = await test_client.delete(f"/registry/documents/{document_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"
        assert data["permanent"] is False

        # Verify document is not in list
        list_response = await test_client.get("/registry/documents")
        list_data = list_response.json()
        document_ids = [doc["document_id"] for doc in list_data]
        assert document_id not in document_ids

    @pytest.mark.asyncio
    async def test_soft_delete_document_not_found(self, test_client):
        """Test soft deleting non-existent document."""
        fake_id = str(uuid4())
        response = await test_client.delete(f"/registry/documents/{fake_id}")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error_code"] == "DOCUMENT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_soft_delete_already_deleted(self, test_client, mock_sqs_client):
        """Test soft deleting already deleted document."""
        # Create a document
        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/doubledelete.test",
            "title": "Double Delete Test Document",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }
        create_response = await test_client.post("/registry/documents", json=request_data)
        document_id = create_response.json()["document_id"]

        # Delete first time
        await test_client.delete(f"/registry/documents/{document_id}")

        # Try to delete again
        response = await test_client.delete(f"/registry/documents/{document_id}")

        assert response.status_code == 409
        data = response.json()
        assert data["detail"]["error_code"] == "ALREADY_DELETED"

    @pytest.mark.asyncio
    async def test_restore_document(self, test_client, mock_sqs_client):
        """Test restoring a soft-deleted document."""
        # Create a document
        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/restore.test",
            "title": "Restore Test Document",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }
        create_response = await test_client.post("/registry/documents", json=request_data)
        document_id = create_response.json()["document_id"]

        # Soft delete
        await test_client.delete(f"/registry/documents/{document_id}")

        # Restore
        response = await test_client.post(f"/registry/documents/{document_id}/restore")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "restored"

        # Verify document is back in list
        list_response = await test_client.get("/registry/documents")
        list_data = list_response.json()
        document_ids = [doc["document_id"] for doc in list_data]
        assert document_id in document_ids

    @pytest.mark.asyncio
    async def test_restore_not_deleted_document(self, test_client, mock_sqs_client):
        """Test restoring a document that's not deleted."""
        # Create a document
        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/restorenot.test",
            "title": "Not Deleted Test Document",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }
        create_response = await test_client.post("/registry/documents", json=request_data)
        document_id = create_response.json()["document_id"]

        # Try to restore without deleting
        response = await test_client.post(f"/registry/documents/{document_id}/restore")

        assert response.status_code == 409
        data = response.json()
        assert data["detail"]["error_code"] == "NOT_DELETED"

    @pytest.mark.asyncio
    async def test_restore_document_not_found(self, test_client):
        """Test restoring non-existent document."""
        fake_id = str(uuid4())
        response = await test_client.post(f"/registry/documents/{fake_id}/restore")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_permanent_delete(self, test_client, mock_sqs_client):
        """Test permanently deleting a document."""
        # Create a document
        user_id = str(uuid4())
        request_data = {
            "doi": "10.1234/harddelete.test",
            "title": "Hard Delete Test Document",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }
        create_response = await test_client.post("/registry/documents", json=request_data)
        document_id = create_response.json()["document_id"]

        # Permanently delete
        response = await test_client.delete(
            f"/registry/documents/{document_id}",
            params={"permanent": True}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"
        assert data["permanent"] is True

        # Verify document cannot be retrieved
        get_response = await test_client.get(f"/registry/documents/{document_id}")
        assert get_response.status_code == 404


class TestIdempotency:
    """Tests for idempotency key support."""

    @pytest.mark.asyncio
    async def test_idempotency_key_returns_same_response(self, test_client, mock_sqs_client):
        """Test that same idempotency key returns cached response."""
        user_id = str(uuid4())
        idempotency_key = str(uuid4())

        request_data = {
            "doi": "10.1234/idempotent.test",
            "title": "Idempotency Test Document",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }

        # First request
        response1 = await test_client.post(
            "/registry/documents",
            json=request_data,
            headers={"Idempotency-Key": idempotency_key},
        )
        assert response1.status_code == 200
        data1 = response1.json()

        # Second request with same key should return cached response
        response2 = await test_client.post(
            "/registry/documents",
            json=request_data,
            headers={"Idempotency-Key": idempotency_key},
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert response2.headers.get("X-Idempotency-Replayed") == "true"

        # Should return same document_id
        assert data1["document_id"] == data2["document_id"]

    @pytest.mark.asyncio
    async def test_different_idempotency_keys_different_responses(self, test_client, mock_sqs_client):
        """Test that different idempotency keys process independently."""
        user_id = str(uuid4())

        # First request with key1
        response1 = await test_client.post(
            "/registry/documents",
            json={
                "doi": "10.1234/idempotent.key1",
                "title": "Idempotency Test Key1",
                "authors": [],
                "source": "crossref",
                "user_id": user_id,
            },
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response1.status_code == 200

        # Second request with different key
        response2 = await test_client.post(
            "/registry/documents",
            json={
                "doi": "10.1234/idempotent.key2",
                "title": "Idempotency Test Key2",
                "authors": [],
                "source": "crossref",
                "user_id": user_id,
            },
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response2.status_code == 200
        assert response2.headers.get("X-Idempotency-Replayed") is None

    @pytest.mark.asyncio
    async def test_no_idempotency_key_processes_normally(self, test_client, mock_sqs_client):
        """Test that requests without idempotency key process normally."""
        user_id = str(uuid4())

        request_data = {
            "doi": "10.1234/no.idempotency.key",
            "title": "No Idempotency Key Test",
            "authors": [],
            "source": "crossref",
            "user_id": user_id,
        }

        response = await test_client.post(
            "/registry/documents",
            json=request_data,
        )
        assert response.status_code == 200
        assert response.headers.get("X-Idempotency-Replayed") is None

    @pytest.mark.asyncio
    async def test_idempotency_only_for_post_and_patch(self, test_client, mock_sqs_client):
        """Test that idempotency only applies to POST and PATCH methods."""
        # Create a document first
        user_id = str(uuid4())
        create_response = await test_client.post(
            "/registry/documents",
            json={
                "doi": "10.1234/get.idempotency.test",
                "title": "GET Idempotency Test",
                "authors": [],
                "source": "crossref",
                "user_id": user_id,
            },
        )
        document_id = create_response.json()["document_id"]

        # GET requests should not use idempotency
        response = await test_client.get(
            f"/registry/documents/{document_id}",
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 200
        assert response.headers.get("X-Idempotency-Replayed") is None
