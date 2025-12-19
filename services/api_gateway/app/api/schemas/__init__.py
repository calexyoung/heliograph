"""API schemas package."""

from services.api_gateway.app.api.schemas.preferences import (
    StoragePreferences,
    UpdatePreferencesRequest,
    PreferencesResponse,
)

__all__ = [
    "StoragePreferences",
    "UpdatePreferencesRequest",
    "PreferencesResponse",
]
