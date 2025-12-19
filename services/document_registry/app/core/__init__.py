"""Core business logic for Document Registry."""

from services.document_registry.app.core.dedup import DeduplicationService, DuplicateResult
from services.document_registry.app.core.state_machine import (
    StateMachine,
    InvalidTransitionError,
)
from services.document_registry.app.core.normalizers import (
    normalize_title,
    normalize_doi,
)

__all__ = [
    "DeduplicationService",
    "DuplicateResult",
    "StateMachine",
    "InvalidTransitionError",
    "normalize_title",
    "normalize_doi",
]
