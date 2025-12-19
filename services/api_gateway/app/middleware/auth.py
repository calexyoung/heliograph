"""Authentication middleware and dependencies."""

from typing import Annotated, Callable
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_gateway.app.auth.jwt import verify_token, TokenData
from services.api_gateway.app.auth.models import UserModel
from services.api_gateway.app.auth.service import AuthService
from services.api_gateway.app.config import get_settings
from shared.utils.db import get_db_session
from shared.utils.logging import get_logger

logger = get_logger(__name__)

# Security schemes
bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class AuthMiddleware:
    """Authentication middleware for extracting user from request."""

    def __init__(self, require_auth: bool = True):
        """Initialize middleware.

        Args:
            require_auth: Whether authentication is required
        """
        self.require_auth = require_auth

    async def __call__(
        self,
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
        api_key: str | None = Depends(api_key_header),
    ) -> UserModel | None:
        """Extract and validate user from request.

        Args:
            request: FastAPI request
            credentials: Bearer token credentials
            api_key: API key header value

        Returns:
            User model or None

        Raises:
            HTTPException: If authentication required but fails
        """
        user = None

        async with get_db_session() as session:
            auth_service = AuthService(session)

            # Try Bearer token first
            if credentials:
                token_data = verify_token(credentials.credentials)
                if token_data:
                    user = await auth_service.get_user_by_id(UUID(token_data.sub))
                    if user:
                        request.state.token_data = token_data
                        request.state.auth_method = "bearer"

            # Try API key
            if not user and api_key:
                api_key_model = await auth_service.validate_api_key(api_key)
                if api_key_model and api_key_model.user_id:
                    user = await auth_service.get_user_by_id(api_key_model.user_id)
                    if user:
                        request.state.api_key = api_key_model
                        request.state.auth_method = "api_key"
                        request.state.scopes = api_key_model.scopes

        if self.require_auth and not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if user:
            request.state.user = user
            logger.debug("user_authenticated", user_id=str(user.user_id))

        return user


async def get_db() -> AsyncSession:
    """Get database session dependency."""
    async with get_db_session() as session:
        yield session


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    api_key: Annotated[str | None, Depends(api_key_header)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> UserModel:
    """Dependency to get current authenticated user.

    Raises:
        HTTPException: If not authenticated
    """
    user = None

    # Check if already authenticated via middleware
    if hasattr(request.state, "user"):
        return request.state.user

    auth_service = AuthService(db)

    # Try Bearer token
    if credentials:
        token_data = verify_token(credentials.credentials)
        if token_data:
            user = await auth_service.get_user_by_id(UUID(token_data.sub))
            if user:
                request.state.token_data = token_data
                request.state.auth_method = "bearer"

    # Try API key
    if not user and api_key:
        api_key_model = await auth_service.validate_api_key(api_key)
        if api_key_model and api_key_model.user_id:
            user = await auth_service.get_user_by_id(api_key_model.user_id)
            if user:
                request.state.api_key = api_key_model
                request.state.auth_method = "api_key"

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    request.state.user = user
    return user


async def get_current_user_optional(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    api_key: Annotated[str | None, Depends(api_key_header)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> UserModel | None:
    """Dependency to optionally get current user (no error if not authenticated)."""
    try:
        return await get_current_user(request, credentials, api_key, db)
    except HTTPException:
        return None


def require_scopes(*required_scopes: str) -> Callable:
    """Dependency factory to require specific scopes.

    Args:
        required_scopes: Scopes that must be present

    Returns:
        Dependency function
    """

    async def check_scopes(
        request: Request,
        user: Annotated[UserModel, Depends(get_current_user)],
    ) -> UserModel:
        # Get scopes from token or API key
        scopes = []

        if hasattr(request.state, "token_data"):
            scopes = request.state.token_data.scopes
        elif hasattr(request.state, "api_key"):
            scopes = request.state.api_key.scopes

        # Superusers have all scopes
        if user.is_superuser:
            return user

        # Check required scopes
        missing = set(required_scopes) - set(scopes)
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scopes: {', '.join(missing)}",
            )

        return user

    return check_scopes


# Type aliases for convenience
CurrentUser = Annotated[UserModel, Depends(get_current_user)]
OptionalUser = Annotated[UserModel | None, Depends(get_current_user_optional)]
