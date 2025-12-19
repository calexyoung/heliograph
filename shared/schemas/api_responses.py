"""Standard API response envelopes."""

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """Standard API response wrapper."""

    success: bool = True
    data: Optional[T] = None
    error: Optional[str] = None
    correlation_id: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standard error response."""

    success: bool = False
    error_code: str
    error_message: str
    details: Optional[dict[str, Any]] = None
    correlation_id: Optional[str] = None


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response wrapper."""

    success: bool = True
    data: list[T] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    has_next: bool = False
    has_previous: bool = False
    correlation_id: Optional[str] = None
