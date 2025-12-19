"""Authentication service for user management."""

import secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_gateway.app.auth.models import (
    APIKeyModel,
    RefreshTokenModel,
    UserModel,
)
from services.api_gateway.app.auth.password import hash_password, verify_password
from services.api_gateway.app.auth.jwt import (
    create_access_token,
    create_refresh_token,
    hash_token,
    TokenPair,
    verify_token,
)
from services.api_gateway.app.config import get_settings
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails."""

    pass


class AuthService:
    """Service for authentication operations."""

    def __init__(self, session: AsyncSession):
        """Initialize auth service.

        Args:
            session: Database session
        """
        self.session = session
        self.settings = get_settings()

    async def get_user_by_id(self, user_id: UUID) -> UserModel | None:
        """Get user by ID.

        Args:
            user_id: User UUID

        Returns:
            User model or None
        """
        query = select(UserModel).where(UserModel.user_id == user_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> UserModel | None:
        """Get user by email.

        Args:
            email: User email

        Returns:
            User model or None
        """
        query = select(UserModel).where(UserModel.email == email.lower())
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_user(
        self,
        email: str,
        password: str | None = None,
        full_name: str | None = None,
        oauth_provider: str | None = None,
        oauth_subject: str | None = None,
    ) -> UserModel:
        """Create a new user.

        Args:
            email: User email
            password: Plain text password (None for OAuth users)
            full_name: User's full name
            oauth_provider: OAuth provider name
            oauth_subject: OAuth subject ID

        Returns:
            Created user model
        """
        hashed_pwd = hash_password(password) if password else None

        user = UserModel(
            email=email.lower(),
            hashed_password=hashed_pwd,
            full_name=full_name,
            oauth_provider=oauth_provider,
            oauth_subject=oauth_subject,
            email_verified=oauth_provider is not None,  # OAuth users are verified
        )

        self.session.add(user)
        await self.session.flush()

        logger.info("user_created", user_id=str(user.user_id), email=email)
        return user

    async def authenticate_user(
        self,
        email: str,
        password: str,
    ) -> UserModel | None:
        """Authenticate user with email and password.

        Args:
            email: User email
            password: Plain text password

        Returns:
            User model if authenticated, None otherwise
        """
        user = await self.get_user_by_email(email)

        if not user:
            return None

        if not user.hashed_password:
            # OAuth-only user
            return None

        if not verify_password(password, user.hashed_password):
            return None

        if not user.is_active:
            return None

        # Update last login
        user.last_login_at = datetime.utcnow()
        await self.session.flush()

        logger.info("user_authenticated", user_id=str(user.user_id))
        return user

    async def create_token_pair(
        self,
        user: UserModel,
        device_info: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPair:
        """Create access and refresh token pair.

        Args:
            user: User model
            device_info: Device information
            ip_address: Client IP address
            user_agent: Client user agent

        Returns:
            Token pair with access and refresh tokens
        """
        # Create access token
        access_token = create_access_token(
            user_id=user.user_id,
            email=user.email,
            scopes=["user:read", "user:write", "documents:read", "documents:write"],
        )

        # Create refresh token record
        token_id = uuid4()
        refresh_token = create_refresh_token(
            user_id=user.user_id,
            token_id=token_id,
        )

        # Store refresh token hash
        expires_at = datetime.utcnow() + timedelta(
            days=self.settings.jwt_refresh_token_expire_days
        )

        refresh_record = RefreshTokenModel(
            token_id=token_id,
            user_id=user.user_id,
            token_hash=hash_token(refresh_token),
            device_info=device_info or {},
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at,
        )

        self.session.add(refresh_record)
        await self.session.flush()

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.settings.jwt_access_token_expire_minutes * 60,
        )

    async def refresh_tokens(
        self,
        refresh_token: str,
        ip_address: str | None = None,
    ) -> TokenPair | None:
        """Refresh access token using refresh token.

        Args:
            refresh_token: Refresh token
            ip_address: Client IP address

        Returns:
            New token pair or None if invalid
        """
        # Verify refresh token
        token_data = verify_token(refresh_token, expected_type="refresh")
        if not token_data or not token_data.jti:
            return None

        # Find refresh token record
        token_id = UUID(token_data.jti)
        query = select(RefreshTokenModel).where(
            RefreshTokenModel.token_id == token_id,
            RefreshTokenModel.is_revoked == False,
            RefreshTokenModel.expires_at > datetime.utcnow(),
        )
        result = await self.session.execute(query)
        token_record = result.scalar_one_or_none()

        if not token_record:
            return None

        # Verify token hash
        if token_record.token_hash != hash_token(refresh_token):
            # Token mismatch - possible token theft, revoke all tokens
            await self.revoke_all_user_tokens(token_record.user_id)
            logger.warning(
                "refresh_token_mismatch",
                user_id=str(token_record.user_id),
            )
            return None

        # Get user
        user = await self.get_user_by_id(UUID(token_data.sub))
        if not user or not user.is_active:
            return None

        # Revoke old refresh token
        token_record.is_revoked = True
        token_record.revoked_at = datetime.utcnow()
        token_record.revoked_reason = "rotated"

        # Create new token pair
        return await self.create_token_pair(
            user=user,
            device_info=token_record.device_info,
            ip_address=ip_address,
            user_agent=token_record.user_agent,
        )

    async def revoke_refresh_token(self, token_id: UUID, reason: str = "logout") -> bool:
        """Revoke a specific refresh token.

        Args:
            token_id: Token ID to revoke
            reason: Reason for revocation

        Returns:
            True if token was revoked
        """
        query = select(RefreshTokenModel).where(RefreshTokenModel.token_id == token_id)
        result = await self.session.execute(query)
        token = result.scalar_one_or_none()

        if not token:
            return False

        token.is_revoked = True
        token.revoked_at = datetime.utcnow()
        token.revoked_reason = reason
        await self.session.flush()

        return True

    async def revoke_all_user_tokens(self, user_id: UUID, reason: str = "security") -> int:
        """Revoke all refresh tokens for a user.

        Args:
            user_id: User ID
            reason: Reason for revocation

        Returns:
            Number of tokens revoked
        """
        query = select(RefreshTokenModel).where(
            RefreshTokenModel.user_id == user_id,
            RefreshTokenModel.is_revoked == False,
        )
        result = await self.session.execute(query)
        tokens = result.scalars().all()

        now = datetime.utcnow()
        for token in tokens:
            token.is_revoked = True
            token.revoked_at = now
            token.revoked_reason = reason

        await self.session.flush()

        logger.info(
            "all_tokens_revoked",
            user_id=str(user_id),
            count=len(tokens),
        )
        return len(tokens)

    async def create_api_key(
        self,
        user_id: UUID,
        name: str,
        scopes: list[str] | None = None,
        expires_in_days: int | None = None,
    ) -> tuple[str, APIKeyModel]:
        """Create a new API key.

        Args:
            user_id: Owner user ID
            name: Key name/description
            scopes: Allowed scopes
            expires_in_days: Days until expiration (None for no expiration)

        Returns:
            Tuple of (raw API key, key model)
        """
        # Generate key: prefix + random bytes
        key_bytes = secrets.token_bytes(32)
        raw_key = f"hg_{secrets.token_urlsafe(32)}"
        key_prefix = raw_key[:8]

        expires_at = None
        if expires_in_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

        api_key = APIKeyModel(
            user_id=user_id,
            name=name,
            key_hash=hash_token(raw_key),
            key_prefix=key_prefix,
            scopes=scopes or [],
            expires_at=expires_at,
        )

        self.session.add(api_key)
        await self.session.flush()

        logger.info(
            "api_key_created",
            user_id=str(user_id),
            key_id=str(api_key.key_id),
        )

        return raw_key, api_key

    async def validate_api_key(self, raw_key: str) -> APIKeyModel | None:
        """Validate an API key.

        Args:
            raw_key: Raw API key string

        Returns:
            API key model if valid, None otherwise
        """
        # Find by prefix for efficiency
        prefix = raw_key[:8]
        query = select(APIKeyModel).where(
            APIKeyModel.key_prefix == prefix,
            APIKeyModel.is_active == True,
        )
        result = await self.session.execute(query)
        candidates = result.scalars().all()

        for key in candidates:
            if key.key_hash == hash_token(raw_key):
                # Check expiration
                if key.expires_at and key.expires_at < datetime.utcnow():
                    return None

                # Update last used
                key.last_used_at = datetime.utcnow()
                await self.session.flush()

                return key

        return None
