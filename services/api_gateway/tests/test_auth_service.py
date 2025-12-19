"""Tests for authentication service."""

import asyncio
from uuid import uuid4

import pytest

from services.api_gateway.app.auth.service import AuthService
from services.api_gateway.app.auth.models import UserModel


class TestAuthService:
    """Tests for authentication service."""

    @pytest.mark.asyncio
    async def test_create_user(self, db_session):
        """Test creating a new user."""
        auth_service = AuthService(db_session)

        user = await auth_service.create_user(
            email="newuser@example.com",
            password="password123",
            full_name="New User",
        )

        assert user is not None
        assert user.email == "newuser@example.com"
        assert user.full_name == "New User"
        assert user.hashed_password is not None
        assert user.is_active is True

    @pytest.mark.asyncio
    async def test_create_oauth_user(self, db_session):
        """Test creating an OAuth user."""
        auth_service = AuthService(db_session)

        user = await auth_service.create_user(
            email="oauth@example.com",
            oauth_provider="google",
            oauth_subject="12345",
        )

        assert user is not None
        assert user.hashed_password is None
        assert user.oauth_provider == "google"
        assert user.email_verified is True  # OAuth users are verified

    @pytest.mark.asyncio
    async def test_get_user_by_email(self, db_session, test_user):
        """Test getting user by email."""
        auth_service = AuthService(db_session)

        user = await auth_service.get_user_by_email("test@example.com")

        assert user is not None
        assert user.user_id == test_user.user_id

    @pytest.mark.asyncio
    async def test_get_user_by_email_not_found(self, db_session):
        """Test getting non-existent user by email."""
        auth_service = AuthService(db_session)

        user = await auth_service.get_user_by_email("nonexistent@example.com")

        assert user is None

    @pytest.mark.asyncio
    async def test_authenticate_user_success(self, db_session, test_user):
        """Test successful authentication."""
        auth_service = AuthService(db_session)

        user = await auth_service.authenticate_user(
            email="test@example.com",
            password="testpassword123",
        )

        assert user is not None
        assert user.user_id == test_user.user_id

    @pytest.mark.asyncio
    async def test_authenticate_user_wrong_password(self, db_session, test_user):
        """Test authentication with wrong password."""
        auth_service = AuthService(db_session)

        user = await auth_service.authenticate_user(
            email="test@example.com",
            password="wrongpassword",
        )

        assert user is None

    @pytest.mark.asyncio
    async def test_authenticate_user_not_found(self, db_session):
        """Test authentication for non-existent user."""
        auth_service = AuthService(db_session)

        user = await auth_service.authenticate_user(
            email="nonexistent@example.com",
            password="password123",
        )

        assert user is None

    @pytest.mark.asyncio
    async def test_create_token_pair(self, db_session, test_user):
        """Test creating token pair."""
        auth_service = AuthService(db_session)

        token_pair = await auth_service.create_token_pair(
            user=test_user,
            ip_address="127.0.0.1",
        )

        assert token_pair is not None
        assert token_pair.access_token is not None
        assert token_pair.refresh_token is not None
        assert token_pair.token_type == "bearer"
        assert token_pair.expires_in > 0

    @pytest.mark.asyncio
    async def test_refresh_tokens(self, db_session, test_user):
        """Test refreshing tokens."""
        auth_service = AuthService(db_session)

        # Create initial tokens
        token_pair = await auth_service.create_token_pair(user=test_user)

        # Wait for 1 second to ensure different iat timestamp
        await asyncio.sleep(1)

        # Refresh
        new_tokens = await auth_service.refresh_tokens(
            refresh_token=token_pair.refresh_token,
        )

        assert new_tokens is not None
        assert new_tokens.access_token != token_pair.access_token
        assert new_tokens.refresh_token != token_pair.refresh_token

    @pytest.mark.asyncio
    async def test_refresh_tokens_invalid(self, db_session):
        """Test refreshing with invalid token."""
        auth_service = AuthService(db_session)

        result = await auth_service.refresh_tokens(
            refresh_token="invalid_token",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_create_api_key(self, db_session, test_user):
        """Test creating API key."""
        auth_service = AuthService(db_session)

        raw_key, api_key = await auth_service.create_api_key(
            user_id=test_user.user_id,
            name="Test Key",
            scopes=["read", "write"],
        )

        assert raw_key is not None
        assert raw_key.startswith("hg_")
        assert api_key is not None
        assert api_key.name == "Test Key"
        assert api_key.scopes == ["read", "write"]

    @pytest.mark.asyncio
    async def test_validate_api_key(self, db_session, test_user):
        """Test validating API key."""
        auth_service = AuthService(db_session)

        raw_key, created_key = await auth_service.create_api_key(
            user_id=test_user.user_id,
            name="Test Key",
        )

        # Validate
        validated_key = await auth_service.validate_api_key(raw_key)

        assert validated_key is not None
        assert validated_key.key_id == created_key.key_id

    @pytest.mark.asyncio
    async def test_validate_api_key_invalid(self, db_session):
        """Test validating invalid API key."""
        auth_service = AuthService(db_session)

        result = await auth_service.validate_api_key("invalid_key")

        assert result is None

    @pytest.mark.asyncio
    async def test_revoke_all_user_tokens(self, db_session, test_user):
        """Test revoking all user tokens."""
        auth_service = AuthService(db_session)

        # Create some tokens
        await auth_service.create_token_pair(user=test_user)
        await auth_service.create_token_pair(user=test_user)

        # Revoke all
        count = await auth_service.revoke_all_user_tokens(test_user.user_id)

        assert count == 2
