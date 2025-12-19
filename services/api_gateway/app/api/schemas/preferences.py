"""User preferences schemas."""

import os
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Allowed base paths for local storage (whitelist for security)
ALLOWED_LOCAL_PATH_PREFIXES = ["/data/", "/storage/", "/home/"]


class StoragePreferences(BaseModel):
    """User storage preferences."""

    type: Literal["s3", "local"] = Field(
        default="s3",
        description="Storage type: 's3' for cloud storage, 'local' for filesystem",
    )
    local_path: Optional[str] = Field(
        default=None,
        description="Custom local filesystem path (only used when type='local')",
    )
    bucket: Optional[str] = Field(
        default=None,
        description="Custom S3 bucket name (optional, uses default if not specified)",
    )

    @field_validator("local_path")
    @classmethod
    def validate_local_path(cls, v: str | None) -> str | None:
        """Validate and normalize local storage path.

        Security measures:
        - Must be absolute path (starts with /)
        - No path traversal (..)
        - Must be within allowed prefixes
        """
        if v is None:
            return v

        # Must be absolute path
        if not v.startswith("/"):
            raise ValueError("local_path must be an absolute path starting with '/'")

        # No path traversal
        if ".." in v:
            raise ValueError("local_path cannot contain path traversal sequences (..)")

        # Normalize the path
        normalized = os.path.normpath(v)

        # After normalization, verify still within allowed prefixes
        if not any(
            normalized.startswith(prefix.rstrip("/"))
            for prefix in ALLOWED_LOCAL_PATH_PREFIXES
        ):
            allowed = ", ".join(ALLOWED_LOCAL_PATH_PREFIXES)
            raise ValueError(f"local_path must start with one of: {allowed}")

        return normalized

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, v: str | None) -> str | None:
        """Validate S3 bucket name."""
        if v is None:
            return v

        # Basic S3 bucket naming rules
        if len(v) < 3 or len(v) > 63:
            raise ValueError("bucket name must be 3-63 characters")

        if not v.replace("-", "").replace(".", "").isalnum():
            raise ValueError(
                "bucket name can only contain lowercase letters, numbers, hyphens, and periods"
            )

        return v.lower()

    @model_validator(mode="after")
    def validate_local_path_required(self) -> "StoragePreferences":
        """Ensure local_path is provided when type is 'local'."""
        if self.type == "local" and not self.local_path:
            raise ValueError("local_path is required when storage type is 'local'")
        return self


class UpdatePreferencesRequest(BaseModel):
    """Request schema for updating user preferences."""

    storage: Optional[StoragePreferences] = Field(
        default=None,
        description="Storage preferences to update",
    )


class PreferencesResponse(BaseModel):
    """Response schema for user preferences."""

    storage: StoragePreferences = Field(
        default_factory=StoragePreferences,
        description="User's storage preferences",
    )
