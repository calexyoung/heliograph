"""Document state machine for lifecycle management."""

from shared.schemas.document import DocumentStatus


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        current_state: DocumentStatus,
        target_state: DocumentStatus,
        message: str | None = None,
    ):
        self.current_state = current_state
        self.target_state = target_state
        self.message = message or f"Invalid transition from {current_state} to {target_state}"
        super().__init__(self.message)


class StateMachine:
    """Document lifecycle state machine.

    Valid transitions:
    - registered -> processing (start processing)
    - processing -> indexed (processing complete)
    - processing -> failed (processing error)
    - failed -> processing (retry)
    """

    # Define valid transitions as (from_state, to_state) pairs
    VALID_TRANSITIONS: set[tuple[DocumentStatus, DocumentStatus]] = {
        (DocumentStatus.REGISTERED, DocumentStatus.PROCESSING),
        (DocumentStatus.PROCESSING, DocumentStatus.INDEXED),
        (DocumentStatus.PROCESSING, DocumentStatus.FAILED),
        (DocumentStatus.FAILED, DocumentStatus.PROCESSING),  # Retry
    }

    @classmethod
    def is_valid_transition(
        cls,
        current_state: DocumentStatus,
        target_state: DocumentStatus,
    ) -> bool:
        """Check if a state transition is valid.

        Args:
            current_state: Current document state
            target_state: Desired new state

        Returns:
            True if transition is valid, False otherwise
        """
        return (current_state, target_state) in cls.VALID_TRANSITIONS

    @classmethod
    def validate_transition(
        cls,
        current_state: DocumentStatus,
        target_state: DocumentStatus,
    ) -> None:
        """Validate a state transition, raising an error if invalid.

        Args:
            current_state: Current document state
            target_state: Desired new state

        Raises:
            InvalidTransitionError: If transition is not valid
        """
        if not cls.is_valid_transition(current_state, target_state):
            raise InvalidTransitionError(current_state, target_state)

    @classmethod
    def get_valid_next_states(
        cls,
        current_state: DocumentStatus,
    ) -> list[DocumentStatus]:
        """Get list of valid next states from current state.

        Args:
            current_state: Current document state

        Returns:
            List of valid target states
        """
        return [
            target
            for (source, target) in cls.VALID_TRANSITIONS
            if source == current_state
        ]

    @classmethod
    def is_terminal_state(cls, state: DocumentStatus) -> bool:
        """Check if a state is terminal (no valid transitions out).

        Args:
            state: State to check

        Returns:
            True if state is terminal
        """
        # indexed is terminal, failed can retry to processing
        return state == DocumentStatus.INDEXED

    @classmethod
    def can_retry(cls, state: DocumentStatus) -> bool:
        """Check if a document in this state can be retried.

        Args:
            state: Current state

        Returns:
            True if document can be retried
        """
        return state == DocumentStatus.FAILED
