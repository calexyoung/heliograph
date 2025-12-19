"""Tests for document state machine."""

import pytest

from services.document_registry.app.core.state_machine import (
    InvalidTransitionError,
    StateMachine,
)
from shared.schemas.document import DocumentStatus


class TestStateMachine:
    """Tests for document lifecycle state machine."""

    def test_valid_registered_to_processing(self):
        """Test valid transition from registered to processing."""
        assert StateMachine.is_valid_transition(
            DocumentStatus.REGISTERED,
            DocumentStatus.PROCESSING,
        )

    def test_valid_processing_to_indexed(self):
        """Test valid transition from processing to indexed."""
        assert StateMachine.is_valid_transition(
            DocumentStatus.PROCESSING,
            DocumentStatus.INDEXED,
        )

    def test_valid_processing_to_failed(self):
        """Test valid transition from processing to failed."""
        assert StateMachine.is_valid_transition(
            DocumentStatus.PROCESSING,
            DocumentStatus.FAILED,
        )

    def test_valid_failed_to_processing_retry(self):
        """Test valid retry transition from failed to processing."""
        assert StateMachine.is_valid_transition(
            DocumentStatus.FAILED,
            DocumentStatus.PROCESSING,
        )

    def test_invalid_registered_to_indexed(self):
        """Test invalid direct transition from registered to indexed."""
        assert not StateMachine.is_valid_transition(
            DocumentStatus.REGISTERED,
            DocumentStatus.INDEXED,
        )

    def test_invalid_indexed_to_processing(self):
        """Test invalid transition from terminal indexed state."""
        assert not StateMachine.is_valid_transition(
            DocumentStatus.INDEXED,
            DocumentStatus.PROCESSING,
        )

    def test_invalid_registered_to_failed(self):
        """Test invalid transition from registered to failed."""
        assert not StateMachine.is_valid_transition(
            DocumentStatus.REGISTERED,
            DocumentStatus.FAILED,
        )

    def test_validate_transition_raises_on_invalid(self):
        """Test validate_transition raises exception for invalid transition."""
        with pytest.raises(InvalidTransitionError) as exc_info:
            StateMachine.validate_transition(
                DocumentStatus.REGISTERED,
                DocumentStatus.INDEXED,
            )
        assert exc_info.value.current_state == DocumentStatus.REGISTERED
        assert exc_info.value.target_state == DocumentStatus.INDEXED

    def test_validate_transition_passes_on_valid(self):
        """Test validate_transition doesn't raise for valid transition."""
        # Should not raise
        StateMachine.validate_transition(
            DocumentStatus.REGISTERED,
            DocumentStatus.PROCESSING,
        )

    def test_get_valid_next_states_from_registered(self):
        """Test getting valid next states from registered."""
        next_states = StateMachine.get_valid_next_states(DocumentStatus.REGISTERED)
        assert next_states == [DocumentStatus.PROCESSING]

    def test_get_valid_next_states_from_processing(self):
        """Test getting valid next states from processing."""
        next_states = StateMachine.get_valid_next_states(DocumentStatus.PROCESSING)
        assert set(next_states) == {DocumentStatus.INDEXED, DocumentStatus.FAILED}

    def test_get_valid_next_states_from_indexed(self):
        """Test getting valid next states from terminal indexed state."""
        next_states = StateMachine.get_valid_next_states(DocumentStatus.INDEXED)
        assert next_states == []

    def test_is_terminal_state_indexed(self):
        """Test indexed is a terminal state."""
        assert StateMachine.is_terminal_state(DocumentStatus.INDEXED)

    def test_is_not_terminal_state_registered(self):
        """Test registered is not a terminal state."""
        assert not StateMachine.is_terminal_state(DocumentStatus.REGISTERED)

    def test_is_not_terminal_state_failed(self):
        """Test failed is not a terminal state (can retry)."""
        assert not StateMachine.is_terminal_state(DocumentStatus.FAILED)

    def test_can_retry_from_failed(self):
        """Test can retry from failed state."""
        assert StateMachine.can_retry(DocumentStatus.FAILED)

    def test_cannot_retry_from_registered(self):
        """Test cannot retry from registered state."""
        assert not StateMachine.can_retry(DocumentStatus.REGISTERED)

    def test_cannot_retry_from_processing(self):
        """Test cannot retry from processing state."""
        assert not StateMachine.can_retry(DocumentStatus.PROCESSING)
