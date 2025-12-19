"""Tests for JWT token handling."""

from datetime import timedelta
from uuid import uuid4

import pytest

from services.api_gateway.app.auth.jwt import (
    create_access_token,
    create_refresh_token,
    verify_token,
    hash_token,
)


class TestJWT:
    """Tests for JWT token operations."""

    def test_create_access_token(self):
        """Test creating access token."""
        user_id = uuid4()
        email = "test@example.com"

        token = create_access_token(
            user_id=user_id,
            email=email,
            scopes=["user:read"],
        )

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_verify_access_token(self):
        """Test verifying valid access token."""
        user_id = uuid4()
        email = "test@example.com"
        scopes = ["user:read", "user:write"]

        token = create_access_token(
            user_id=user_id,
            email=email,
            scopes=scopes,
        )

        token_data = verify_token(token, expected_type="access")

        assert token_data is not None
        assert token_data.sub == str(user_id)
        assert token_data.email == email
        assert token_data.scopes == scopes
        assert token_data.token_type == "access"

    def test_verify_invalid_token(self):
        """Test verifying invalid token."""
        result = verify_token("invalid.token.here")
        assert result is None

    def test_verify_wrong_token_type(self):
        """Test verifying token with wrong type."""
        user_id = uuid4()
        token = create_access_token(user_id=user_id)

        # Try to verify as refresh token
        result = verify_token(token, expected_type="refresh")
        assert result is None

    def test_create_refresh_token(self):
        """Test creating refresh token."""
        user_id = uuid4()
        token_id = uuid4()

        token = create_refresh_token(
            user_id=user_id,
            token_id=token_id,
        )

        assert token is not None
        assert isinstance(token, str)

    def test_verify_refresh_token(self):
        """Test verifying valid refresh token."""
        user_id = uuid4()
        token_id = uuid4()

        token = create_refresh_token(
            user_id=user_id,
            token_id=token_id,
        )

        token_data = verify_token(token, expected_type="refresh")

        assert token_data is not None
        assert token_data.sub == str(user_id)
        assert token_data.jti == str(token_id)
        assert token_data.token_type == "refresh"

    def test_expired_token(self):
        """Test verifying expired token."""
        user_id = uuid4()

        # Create token that expires immediately
        token = create_access_token(
            user_id=user_id,
            expires_delta=timedelta(seconds=-1),
        )

        result = verify_token(token)
        assert result is None

    def test_hash_token(self):
        """Test token hashing."""
        token = "test_token_12345"

        hash1 = hash_token(token)
        hash2 = hash_token(token)

        # Same token should produce same hash
        assert hash1 == hash2

        # Hash should be 64 chars (SHA-256 hex)
        assert len(hash1) == 64

        # Different token should produce different hash
        assert hash_token("different_token") != hash1
