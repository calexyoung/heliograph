"""Authentication API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_gateway.app.auth.jwt import TokenPair
from services.api_gateway.app.auth.models import UserModel
from services.api_gateway.app.auth.service import AuthService
from services.api_gateway.app.middleware.auth import CurrentUser, get_db
from shared.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# Request/Response schemas
class RegisterRequest(BaseModel):
    """User registration request."""

    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str | None = None


class LoginRequest(BaseModel):
    """User login request."""

    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """Token refresh request."""

    refresh_token: str


class TokenResponse(BaseModel):
    """Token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    """User info response."""

    user_id: UUID
    email: str
    full_name: str | None
    is_active: bool
    email_verified: bool


class APIKeyCreateRequest(BaseModel):
    """API key creation request."""

    name: str = Field(..., min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=list)
    expires_in_days: int | None = Field(None, ge=1, le=365)


class APIKeyResponse(BaseModel):
    """API key creation response (only time raw key is shown)."""

    key_id: UUID
    name: str
    api_key: str  # Raw key - only shown once
    key_prefix: str
    scopes: list[str]
    expires_at: str | None


DBSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    db: DBSession,
    http_request: Request,
) -> TokenResponse:
    """Register a new user account."""
    auth_service = AuthService(db)

    # Check if user exists
    existing = await auth_service.get_user_by_email(request.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create user
    user = await auth_service.create_user(
        email=request.email,
        password=request.password,
        full_name=request.full_name,
    )

    # Create tokens
    ip = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    token_pair = await auth_service.create_token_pair(
        user=user,
        ip_address=ip,
        user_agent=user_agent,
    )

    await db.commit()

    logger.info("user_registered", user_id=str(user.user_id), email=request.email)

    return TokenResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        expires_in=token_pair.expires_in,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    db: DBSession,
    http_request: Request,
) -> TokenResponse:
    """Login with email and password."""
    auth_service = AuthService(db)

    user = await auth_service.authenticate_user(
        email=request.email,
        password=request.password,
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Create tokens
    ip = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    token_pair = await auth_service.create_token_pair(
        user=user,
        ip_address=ip,
        user_agent=user_agent,
    )

    await db.commit()

    logger.info("user_logged_in", user_id=str(user.user_id))

    return TokenResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        expires_in=token_pair.expires_in,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(
    request: RefreshRequest,
    db: DBSession,
    http_request: Request,
) -> TokenResponse:
    """Refresh access token using refresh token."""
    auth_service = AuthService(db)

    ip = http_request.client.host if http_request.client else None

    token_pair = await auth_service.refresh_tokens(
        refresh_token=request.refresh_token,
        ip_address=ip,
    )

    if not token_pair:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    await db.commit()

    return TokenResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        expires_in=token_pair.expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: CurrentUser,
    db: DBSession,
    http_request: Request,
) -> None:
    """Logout (revoke all refresh tokens)."""
    auth_service = AuthService(db)
    await auth_service.revoke_all_user_tokens(current_user.user_id, reason="logout")
    await db.commit()

    logger.info("user_logged_out", user_id=str(current_user.user_id))


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: CurrentUser,
) -> UserResponse:
    """Get current user information."""
    return UserResponse(
        user_id=current_user.user_id,
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        email_verified=current_user.email_verified,
    )


@router.post("/api-keys", response_model=APIKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    request: APIKeyCreateRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> APIKeyResponse:
    """Create a new API key."""
    auth_service = AuthService(db)

    raw_key, api_key = await auth_service.create_api_key(
        user_id=current_user.user_id,
        name=request.name,
        scopes=request.scopes,
        expires_in_days=request.expires_in_days,
    )

    await db.commit()

    return APIKeyResponse(
        key_id=api_key.key_id,
        name=api_key.name,
        api_key=raw_key,  # Only shown once!
        key_prefix=api_key.key_prefix,
        scopes=api_key.scopes,
        expires_at=api_key.expires_at.isoformat() if api_key.expires_at else None,
    )
