"""Tests for password hashing."""

import pytest

from services.api_gateway.app.auth.password import hash_password, verify_password


class TestPassword:
    """Tests for password hashing and verification."""

    def test_hash_password(self):
        """Test password hashing produces different hash each time."""
        password = "testpassword123"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        # Hashes should be different (bcrypt uses random salt)
        assert hash1 != hash2

        # Both should be valid hashes
        assert hash1.startswith("$2b$")
        assert hash2.startswith("$2b$")

    def test_verify_password_correct(self):
        """Test verifying correct password."""
        password = "testpassword123"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test verifying incorrect password."""
        password = "testpassword123"
        wrong_password = "wrongpassword"
        hashed = hash_password(password)

        assert verify_password(wrong_password, hashed) is False

    def test_verify_empty_password(self):
        """Test verifying empty password."""
        password = "testpassword123"
        hashed = hash_password(password)

        assert verify_password("", hashed) is False

    def test_hash_empty_password(self):
        """Test hashing empty password (should work)."""
        password = ""
        hashed = hash_password(password)

        assert verify_password("", hashed) is True
        assert verify_password("something", hashed) is False
