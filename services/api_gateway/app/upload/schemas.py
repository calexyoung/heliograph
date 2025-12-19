"""Upload request/response schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class PresignedUrlRequest(BaseModel):
    """Request for a pre-signed upload URL."""

    filename: str = Field(..., description="Original filename", min_length=1, max_length=255)
    content_type: str = Field(
        default="application/pdf",
        description="MIME type of the file",
    )
    size_bytes: int = Field(..., description="File size in bytes", gt=0)

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        """Validate content type is allowed."""
        allowed_types = ["application/pdf"]
        if v not in allowed_types:
            raise ValueError(f"Content type must be one of: {', '.join(allowed_types)}")
        return v

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        """Validate filename is safe."""
        # Remove path separators
        v = v.replace("/", "_").replace("\\", "_")
        # Remove null bytes
        v = v.replace("\x00", "")
        return v


class PresignedUrlResponse(BaseModel):
    """Response with pre-signed upload URL."""

    upload_id: UUID
    presigned_url: str
    expires_at: datetime
    s3_key: str
    max_size_bytes: int


class UploadCompleteRequest(BaseModel):
    """Request to mark upload as complete."""

    # Optional metadata to extract from the uploaded file
    title: Optional[str] = Field(None, description="Document title if known")
    doi: Optional[str] = Field(None, description="Document DOI if known")


class UploadCompleteResponse(BaseModel):
    """Response after upload completion."""

    upload_id: UUID
    document_id: Optional[UUID] = Field(
        None, description="Document ID if registration succeeded"
    )
    status: str = Field(..., description="Upload status")
    content_hash: Optional[str] = Field(None, description="SHA-256 hash of file content")
    message: str = Field(..., description="Status message")


class UploadStatusResponse(BaseModel):
    """Response for upload status check."""

    upload_id: UUID
    status: str
    filename: str
    size_bytes: int
    content_type: str
    document_id: Optional[UUID] = None
    content_hash: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    uploaded_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
