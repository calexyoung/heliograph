"""Tests for API request/response schemas."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.document_registry.app.api.schemas import (
    DocumentRegistrationRequest,
    StateTransitionRequest,
)
from shared.schemas.document import DocumentStatus


class TestDocumentRegistrationRequest:
    """Tests for document registration request schema."""

    def test_valid_request(self):
        """Test valid registration request."""
        request = DocumentRegistrationRequest(
            content_hash="a" * 64,
            title="Test Document",
            source="upload",
            user_id=uuid4(),
        )
        assert request.content_hash == "a" * 64

    def test_content_hash_lowercased(self):
        """Test content hash is lowercased."""
        request = DocumentRegistrationRequest(
            content_hash="A" * 64,
            title="Test Document",
            source="upload",
            user_id=uuid4(),
        )
        assert request.content_hash == "a" * 64

    def test_invalid_content_hash_length(self):
        """Test invalid content hash length is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            DocumentRegistrationRequest(
                content_hash="abc",  # Too short
                title="Test Document",
                source="upload",
                user_id=uuid4(),
            )
        assert "content_hash" in str(exc_info.value)

    def test_invalid_content_hash_not_hex(self):
        """Test non-hex content hash is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            DocumentRegistrationRequest(
                content_hash="g" * 64,  # 'g' is not valid hex
                title="Test Document",
                source="upload",
                user_id=uuid4(),
            )
        assert "hexadecimal" in str(exc_info.value)

    def test_empty_title_rejected(self):
        """Test empty title is rejected."""
        with pytest.raises(ValidationError):
            DocumentRegistrationRequest(
                content_hash="a" * 64,
                title="",
                source="upload",
                user_id=uuid4(),
            )

    def test_invalid_source_rejected(self):
        """Test invalid source value is rejected."""
        with pytest.raises(ValidationError):
            DocumentRegistrationRequest(
                content_hash="a" * 64,
                title="Test",
                source="invalid_source",
                user_id=uuid4(),
            )

    def test_valid_sources(self):
        """Test all valid source values are accepted."""
        valid_sources = ["upload", "crossref", "semantic_scholar", "arxiv", "scixplorer"]
        for source in valid_sources:
            request = DocumentRegistrationRequest(
                content_hash="a" * 64,
                title="Test",
                source=source,
                user_id=uuid4(),
            )
            assert request.source == source

    def test_year_validation(self):
        """Test year is within valid range."""
        # Valid year
        request = DocumentRegistrationRequest(
            content_hash="a" * 64,
            title="Test",
            source="upload",
            user_id=uuid4(),
            year=2024,
        )
        assert request.year == 2024

        # Year too old
        with pytest.raises(ValidationError):
            DocumentRegistrationRequest(
                content_hash="a" * 64,
                title="Test",
                source="upload",
                user_id=uuid4(),
                year=1700,
            )

        # Year too far in future
        with pytest.raises(ValidationError):
            DocumentRegistrationRequest(
                content_hash="a" * 64,
                title="Test",
                source="upload",
                user_id=uuid4(),
                year=2200,
            )

    def test_optional_fields(self):
        """Test optional fields default correctly."""
        request = DocumentRegistrationRequest(
            content_hash="a" * 64,
            title="Test",
            source="upload",
            user_id=uuid4(),
        )
        assert request.doi is None
        assert request.authors == []
        assert request.journal is None
        assert request.year is None


class TestStateTransitionRequest:
    """Tests for state transition request schema."""

    def test_valid_transition_to_processing(self):
        """Test valid transition request."""
        request = StateTransitionRequest(
            state=DocumentStatus.PROCESSING,
            worker_id="worker-1",
        )
        assert request.state == DocumentStatus.PROCESSING

    def test_transition_to_failed_requires_error_message(self):
        """Test transition to failed requires error message."""
        with pytest.raises(ValidationError) as exc_info:
            StateTransitionRequest(
                state=DocumentStatus.FAILED,
                worker_id="worker-1",
                # Missing error_message
            )
        assert "error_message" in str(exc_info.value)

    def test_transition_to_failed_with_error_message(self):
        """Test transition to failed with error message."""
        request = StateTransitionRequest(
            state=DocumentStatus.FAILED,
            worker_id="worker-1",
            error_message="PDF parsing failed",
        )
        assert request.error_message == "PDF parsing failed"

    def test_optimistic_locking_with_expected_state(self):
        """Test request with expected state for optimistic locking."""
        request = StateTransitionRequest(
            state=DocumentStatus.INDEXED,
            expected_state=DocumentStatus.PROCESSING,
            worker_id="worker-1",
        )
        assert request.expected_state == DocumentStatus.PROCESSING

    def test_artifact_pointers(self):
        """Test request with artifact pointers."""
        request = StateTransitionRequest(
            state=DocumentStatus.INDEXED,
            worker_id="worker-1",
            artifact_pointers={
                "chunks": "s3://bucket/doc/chunks.json",
                "embeddings": "s3://bucket/doc/embeddings.npy",
            },
        )
        assert "chunks" in request.artifact_pointers
