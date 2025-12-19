"""User preferences API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_gateway.app.api.schemas.preferences import (
    PreferencesResponse,
    StoragePreferences,
    UpdatePreferencesRequest,
)
from services.api_gateway.app.middleware.auth import CurrentUser, get_db
from shared.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/preferences", tags=["Preferences"])

DBSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=PreferencesResponse)
async def get_preferences(
    current_user: CurrentUser,
) -> PreferencesResponse:
    """Get current user's preferences.

    Returns the user's storage preferences including:
    - Storage type (s3 or local)
    - Local path (if using local storage)
    - Custom S3 bucket (if specified)
    """
    prefs = current_user.preferences or {}
    storage_prefs = prefs.get("storage", {})

    return PreferencesResponse(
        storage=StoragePreferences(
            type=storage_prefs.get("type", "s3"),
            local_path=storage_prefs.get("local_path"),
            bucket=storage_prefs.get("bucket"),
        )
    )


@router.put("", response_model=PreferencesResponse)
async def update_preferences(
    request: UpdatePreferencesRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> PreferencesResponse:
    """Update user preferences.

    Updates the user's storage preferences. The storage configuration
    will be used for new document uploads.

    Existing documents will continue to use their original storage location.
    """
    # Get current preferences
    prefs = dict(current_user.preferences or {})

    # Update storage preferences if provided
    if request.storage:
        prefs["storage"] = request.storage.model_dump(exclude_none=True)

        logger.info(
            "user_preferences_updated",
            user_id=str(current_user.user_id),
            storage_type=request.storage.type,
        )

    # Save to database
    current_user.preferences = prefs
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    # Return updated preferences
    storage_prefs = prefs.get("storage", {})
    return PreferencesResponse(
        storage=StoragePreferences(
            type=storage_prefs.get("type", "s3"),
            local_path=storage_prefs.get("local_path"),
            bucket=storage_prefs.get("bucket"),
        )
    )


@router.get("/storage", response_model=StoragePreferences)
async def get_storage_preferences(
    current_user: CurrentUser,
) -> StoragePreferences:
    """Get current user's storage preferences only.

    Convenience endpoint that returns just the storage configuration.
    """
    prefs = current_user.preferences or {}
    storage_prefs = prefs.get("storage", {})

    return StoragePreferences(
        type=storage_prefs.get("type", "s3"),
        local_path=storage_prefs.get("local_path"),
        bucket=storage_prefs.get("bucket"),
    )
