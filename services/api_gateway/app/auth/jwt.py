"""JWT token handling."""

import hashlib
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from jose import JWTError, jwt
from pydantic import BaseModel

from services.api_gateway.app.config import get_settings


class TokenData(BaseModel):
    """Token payload data."""

    sub: str  # Subject (user_id)
    email: str | None = None
    scopes: list[str] = []
    token_type: str = "access"
    exp: datetime | None = None
    iat: datetime | None = None
    jti: str | None = None  # JWT ID for refresh token tracking


class TokenPair(BaseModel):
    """Access and refresh token pair."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # Seconds until access token expires


def create_access_token(
    user_id: UUID,
    email: str | None = None,
    scopes: list[str] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token.

    Args:
        user_id: User UUID
        email: User email
        scopes: List of permission scopes
        expires_delta: Custom expiration time

    Returns:
        Encoded JWT token
    """
    settings = get_settings()

    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)

    now = datetime.utcnow()
    expire = now + expires_delta

    payload = {
        "sub": str(user_id),
        "email": email,
        "scopes": scopes or [],
        "token_type": "access",
        "exp": expire,
        "iat": now,
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(
    user_id: UUID,
    token_id: UUID,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT refresh token.

    Args:
        user_id: User UUID
        token_id: Unique token ID for tracking/revocation
        expires_delta: Custom expiration time

    Returns:
        Encoded JWT token
    """
    settings = get_settings()

    if expires_delta is None:
        expires_delta = timedelta(days=settings.jwt_refresh_token_expire_days)

    now = datetime.utcnow()
    expire = now + expires_delta

    payload = {
        "sub": str(user_id),
        "token_type": "refresh",
        "jti": str(token_id),
        "exp": expire,
        "iat": now,
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def verify_token(token: str, expected_type: str = "access") -> TokenData | None:
    """Verify and decode a JWT token.

    Args:
        token: JWT token string
        expected_type: Expected token type ('access' or 'refresh')

    Returns:
        TokenData if valid, None if invalid
    """
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        # Validate token type
        if payload.get("token_type") != expected_type:
            return None

        return TokenData(
            sub=payload["sub"],
            email=payload.get("email"),
            scopes=payload.get("scopes", []),
            token_type=payload.get("token_type", "access"),
            exp=datetime.fromtimestamp(payload["exp"]) if "exp" in payload else None,
            iat=datetime.fromtimestamp(payload["iat"]) if "iat" in payload else None,
            jti=payload.get("jti"),
        )

    except JWTError:
        return None


def hash_token(token: str) -> str:
    """Create a hash of a token for storage.

    Args:
        token: Token string to hash

    Returns:
        SHA-256 hash of the token
    """
    return hashlib.sha256(token.encode()).hexdigest()
