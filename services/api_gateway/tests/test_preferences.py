"""Tests for user preferences schemas and API endpoints."""

import pytest
from pydantic import ValidationError

from services.api_gateway.app.api.schemas.preferences import (
    ALLOWED_LOCAL_PATH_PREFIXES,
    PreferencesResponse,
    StoragePreferences,
    UpdatePreferencesRequest,
)
from services.api_gateway.app.auth.models import UserModel


class TestStoragePreferencesSchema:
    """Tests for StoragePreferences schema validation."""

    def test_default_storage_type_is_s3(self):
        """Test that default storage type is S3."""
        prefs = StoragePreferences()
        assert prefs.type == "s3"
        assert prefs.local_path is None
        assert prefs.bucket is None

    def test_valid_s3_storage(self):
        """Test valid S3 storage configuration."""
        prefs = StoragePreferences(type="s3", bucket="my-bucket")
        assert prefs.type == "s3"
        assert prefs.bucket == "my-bucket"

    def test_valid_local_storage(self):
        """Test valid local storage configuration."""
        prefs = StoragePreferences(type="local", local_path="/data/documents")
        assert prefs.type == "local"
        assert prefs.local_path == "/data/documents"

    def test_local_storage_with_home_path(self):
        """Test local storage with /home/ prefix."""
        prefs = StoragePreferences(type="local", local_path="/home/user/documents")
        assert prefs.local_path == "/home/user/documents"

    def test_local_storage_with_storage_path(self):
        """Test local storage with /storage/ prefix."""
        prefs = StoragePreferences(type="local", local_path="/storage/research/pdfs")
        assert prefs.local_path == "/storage/research/pdfs"

    def test_local_path_normalized(self):
        """Test that local path is normalized."""
        prefs = StoragePreferences(type="local", local_path="/data/foo/./bar/")
        assert prefs.local_path == "/data/foo/bar"

    def test_invalid_relative_path(self):
        """Test that relative paths are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            StoragePreferences(type="local", local_path="data/documents")
        assert "must be an absolute path" in str(exc_info.value)

    def test_path_traversal_rejected(self):
        """Test that path traversal is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            StoragePreferences(type="local", local_path="/data/../etc/passwd")
        assert "path traversal" in str(exc_info.value)

    def test_path_traversal_in_middle_rejected(self):
        """Test that path traversal in middle of path is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            StoragePreferences(type="local", local_path="/data/foo/../../../etc")
        assert "path traversal" in str(exc_info.value)

    def test_disallowed_path_prefix(self):
        """Test that paths outside allowed prefixes are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            StoragePreferences(type="local", local_path="/etc/heliograph")
        assert "must start with one of" in str(exc_info.value)

    def test_disallowed_root_path(self):
        """Test that root path is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            StoragePreferences(type="local", local_path="/")
        assert "must start with one of" in str(exc_info.value)

    def test_disallowed_var_path(self):
        """Test that /var path is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            StoragePreferences(type="local", local_path="/var/lib/heliograph")
        assert "must start with one of" in str(exc_info.value)

    def test_local_type_requires_path(self):
        """Test that local storage type requires local_path."""
        with pytest.raises(ValidationError) as exc_info:
            StoragePreferences(type="local")
        assert "local_path is required" in str(exc_info.value)

    def test_local_type_rejects_empty_path(self):
        """Test that local storage type rejects empty path."""
        with pytest.raises(ValidationError) as exc_info:
            StoragePreferences(type="local", local_path="")
        assert "must be an absolute path" in str(exc_info.value)

    def test_s3_type_allows_no_path(self):
        """Test that S3 storage type allows no local_path."""
        prefs = StoragePreferences(type="s3")
        assert prefs.local_path is None

    def test_invalid_storage_type(self):
        """Test that invalid storage type is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            StoragePreferences(type="gcs")  # Google Cloud Storage not supported
        assert "type" in str(exc_info.value)

    def test_bucket_name_too_short(self):
        """Test that bucket names under 3 characters are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            StoragePreferences(type="s3", bucket="ab")
        assert "3-63 characters" in str(exc_info.value)

    def test_bucket_name_too_long(self):
        """Test that bucket names over 63 characters are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            StoragePreferences(type="s3", bucket="a" * 64)
        assert "3-63 characters" in str(exc_info.value)

    def test_bucket_name_invalid_characters(self):
        """Test that bucket names with invalid characters are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            StoragePreferences(type="s3", bucket="my_bucket!")
        assert "lowercase letters, numbers, hyphens, and periods" in str(exc_info.value)

    def test_bucket_name_lowercased(self):
        """Test that bucket names are lowercased."""
        prefs = StoragePreferences(type="s3", bucket="My-Bucket")
        assert prefs.bucket == "my-bucket"

    def test_bucket_name_with_hyphens(self):
        """Test that bucket names with hyphens are valid."""
        prefs = StoragePreferences(type="s3", bucket="my-research-bucket")
        assert prefs.bucket == "my-research-bucket"

    def test_bucket_name_with_periods(self):
        """Test that bucket names with periods are valid."""
        prefs = StoragePreferences(type="s3", bucket="my.bucket.name")
        assert prefs.bucket == "my.bucket.name"


class TestUpdatePreferencesRequest:
    """Tests for UpdatePreferencesRequest schema."""

    def test_empty_request_valid(self):
        """Test that empty request is valid."""
        request = UpdatePreferencesRequest()
        assert request.storage is None

    def test_request_with_storage(self):
        """Test request with storage preferences."""
        request = UpdatePreferencesRequest(
            storage=StoragePreferences(type="local", local_path="/data/docs")
        )
        assert request.storage is not None
        assert request.storage.type == "local"

    def test_request_storage_validation_applies(self):
        """Test that storage validation applies in request."""
        with pytest.raises(ValidationError):
            UpdatePreferencesRequest(
                storage={"type": "local", "local_path": "/invalid/path"}
            )


class TestPreferencesResponse:
    """Tests for PreferencesResponse schema."""

    def test_default_response(self):
        """Test default preferences response."""
        response = PreferencesResponse()
        assert response.storage.type == "s3"
        assert response.storage.local_path is None

    def test_response_with_custom_storage(self):
        """Test response with custom storage."""
        response = PreferencesResponse(
            storage=StoragePreferences(type="local", local_path="/data/test")
        )
        assert response.storage.type == "local"
        assert response.storage.local_path == "/data/test"


class TestPreferencesAPI:
    """Tests for preferences API endpoints."""

    @pytest.mark.asyncio
    async def test_get_preferences_default(self, db_session, test_user):
        """Test getting preferences returns defaults for new user."""
        # User with no preferences set
        assert test_user.preferences is None or test_user.preferences == {}

        # Simulate what the endpoint does
        prefs = test_user.preferences or {}
        storage_prefs = prefs.get("storage", {})

        response = PreferencesResponse(
            storage=StoragePreferences(
                type=storage_prefs.get("type", "s3"),
                local_path=storage_prefs.get("local_path"),
                bucket=storage_prefs.get("bucket"),
            )
        )

        assert response.storage.type == "s3"
        assert response.storage.local_path is None
        assert response.storage.bucket is None

    @pytest.mark.asyncio
    async def test_get_preferences_with_stored_values(self, db_session, test_user):
        """Test getting preferences returns stored values."""
        # Set preferences on user
        test_user.preferences = {
            "storage": {
                "type": "local",
                "local_path": "/data/research",
            }
        }
        db_session.add(test_user)
        await db_session.commit()

        # Simulate what the endpoint does
        prefs = test_user.preferences or {}
        storage_prefs = prefs.get("storage", {})

        response = PreferencesResponse(
            storage=StoragePreferences(
                type=storage_prefs.get("type", "s3"),
                local_path=storage_prefs.get("local_path"),
                bucket=storage_prefs.get("bucket"),
            )
        )

        assert response.storage.type == "local"
        assert response.storage.local_path == "/data/research"

    @pytest.mark.asyncio
    async def test_update_preferences_to_local(self, db_session, test_user):
        """Test updating preferences to local storage."""
        # Create update request
        request = UpdatePreferencesRequest(
            storage=StoragePreferences(type="local", local_path="/data/documents")
        )

        # Simulate what the endpoint does
        prefs = dict(test_user.preferences or {})
        if request.storage:
            prefs["storage"] = request.storage.model_dump(exclude_none=True)

        test_user.preferences = prefs
        db_session.add(test_user)
        await db_session.commit()
        await db_session.refresh(test_user)

        assert test_user.preferences["storage"]["type"] == "local"
        assert test_user.preferences["storage"]["local_path"] == "/data/documents"

    @pytest.mark.asyncio
    async def test_update_preferences_to_s3(self, db_session, test_user):
        """Test updating preferences to S3 storage."""
        # First set to local
        test_user.preferences = {
            "storage": {"type": "local", "local_path": "/data/test"}
        }
        await db_session.commit()

        # Now update to S3
        request = UpdatePreferencesRequest(
            storage=StoragePreferences(type="s3", bucket="my-bucket")
        )

        prefs = dict(test_user.preferences or {})
        if request.storage:
            prefs["storage"] = request.storage.model_dump(exclude_none=True)

        test_user.preferences = prefs
        db_session.add(test_user)
        await db_session.commit()
        await db_session.refresh(test_user)

        assert test_user.preferences["storage"]["type"] == "s3"
        assert test_user.preferences["storage"]["bucket"] == "my-bucket"
        # local_path should not be present when using S3
        assert "local_path" not in test_user.preferences["storage"]

    @pytest.mark.asyncio
    async def test_update_preserves_other_preferences(self, db_session, test_user):
        """Test that updating storage preserves other preference keys."""
        # Set multiple preference keys
        test_user.preferences = {
            "storage": {"type": "s3"},
            "notifications": {"email": True},
            "theme": "dark",
        }
        await db_session.commit()

        # Update only storage
        request = UpdatePreferencesRequest(
            storage=StoragePreferences(type="local", local_path="/data/new")
        )

        prefs = dict(test_user.preferences or {})
        if request.storage:
            prefs["storage"] = request.storage.model_dump(exclude_none=True)

        test_user.preferences = prefs
        db_session.add(test_user)
        await db_session.commit()

        # Other preferences should be preserved
        assert test_user.preferences["notifications"]["email"] is True
        assert test_user.preferences["theme"] == "dark"
        assert test_user.preferences["storage"]["type"] == "local"

    @pytest.mark.asyncio
    async def test_get_storage_preferences_only(self, db_session, test_user):
        """Test getting just storage preferences."""
        test_user.preferences = {
            "storage": {
                "type": "local",
                "local_path": "/home/user/docs",
            },
            "other_settings": {"foo": "bar"},
        }
        await db_session.commit()

        # Simulate GET /preferences/storage endpoint
        prefs = test_user.preferences or {}
        storage_prefs = prefs.get("storage", {})

        response = StoragePreferences(
            type=storage_prefs.get("type", "s3"),
            local_path=storage_prefs.get("local_path"),
            bucket=storage_prefs.get("bucket"),
        )

        assert response.type == "local"
        assert response.local_path == "/home/user/docs"


class TestAllowedPathPrefixes:
    """Tests to verify allowed path prefixes are correct."""

    def test_allowed_prefixes_include_data(self):
        """Test that /data/ is in allowed prefixes."""
        assert "/data/" in ALLOWED_LOCAL_PATH_PREFIXES

    def test_allowed_prefixes_include_storage(self):
        """Test that /storage/ is in allowed prefixes."""
        assert "/storage/" in ALLOWED_LOCAL_PATH_PREFIXES

    def test_allowed_prefixes_include_home(self):
        """Test that /home/ is in allowed prefixes."""
        assert "/home/" in ALLOWED_LOCAL_PATH_PREFIXES

    def test_allowed_prefixes_do_not_include_etc(self):
        """Test that /etc/ is not in allowed prefixes."""
        assert "/etc/" not in ALLOWED_LOCAL_PATH_PREFIXES

    def test_allowed_prefixes_do_not_include_var(self):
        """Test that /var/ is not in allowed prefixes."""
        assert "/var/" not in ALLOWED_LOCAL_PATH_PREFIXES

    def test_allowed_prefixes_do_not_include_root(self):
        """Test that root is not in allowed prefixes."""
        assert "/" not in ALLOWED_LOCAL_PATH_PREFIXES
