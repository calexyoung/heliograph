"""File upload API routes."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_gateway.app.auth.models import UploadModel, UserModel
from services.api_gateway.app.config import get_settings
from services.api_gateway.app.middleware.auth import CurrentUser, get_db
from services.api_gateway.app.upload.schemas import (
    PresignedUrlRequest,
    PresignedUrlResponse,
    UploadCompleteRequest,
    UploadCompleteResponse,
    UploadStatusResponse,
)
from services.api_gateway.app.upload.service import UploadError, UploadService
from shared.utils.logging import get_logger
from shared.utils.s3 import StorageClient, get_storage_client

logger = get_logger(__name__)

router = APIRouter(prefix="/upload", tags=["Upload"])


def get_storage() -> StorageClient:
    """Get storage client dependency (S3 or local based on system config)."""
    settings = get_settings()
    return get_storage_client(
        storage_type=settings.storage_type,
        bucket=settings.storage_bucket or settings.s3_bucket,
        region=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url,
        local_path=settings.local_storage_path,
        serve_url=settings.s3_public_endpoint_url or "http://localhost:8080/files",
    )


def get_user_storage(
    current_user: UserModel,
) -> tuple[StorageClient, dict[str, Any]]:
    """Get user-specific storage client based on preferences.

    Returns:
        Tuple of (StorageClient, storage_config dict)
    """
    settings = get_settings()

    # Get user's storage preferences
    prefs = (current_user.preferences or {}).get("storage", {})
    storage_type = prefs.get("type", settings.storage_type)
    storage_config = {
        "type": storage_type,
        "local_path": prefs.get("local_path"),
        "bucket": prefs.get("bucket"),
    }

    if storage_type == "local":
        local_path = prefs.get("local_path") or settings.local_storage_path
        # For local storage, serve files through the API gateway's /files endpoint
        # Default to port 8080 (standard API gateway port)
        local_serve_url = "http://localhost:8080/files"
        client = get_storage_client(
            storage_type="local",
            bucket=settings.storage_bucket or settings.s3_bucket,
            region=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            local_path=local_path,
            serve_url=local_serve_url,
        )
        storage_config["local_path"] = local_path
    else:
        bucket = prefs.get("bucket") or settings.storage_bucket or settings.s3_bucket
        client = get_storage_client(
            storage_type="s3",
            bucket=bucket,
            region=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            local_path=settings.local_storage_path,
            serve_url=settings.s3_public_endpoint_url or "http://localhost:8080/files",
        )
        storage_config["bucket"] = bucket

    logger.debug(
        "user_storage_resolved",
        user_id=str(current_user.user_id),
        storage_type=storage_type,
    )

    return client, storage_config


DBSession = Annotated[AsyncSession, Depends(get_db)]
Storage = Annotated[StorageClient, Depends(get_storage)]


@router.post("/presigned-url", response_model=PresignedUrlResponse)
async def create_presigned_url(
    request: PresignedUrlRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> PresignedUrlResponse:
    """Get a pre-signed URL for file upload.

    Use this URL to upload the file directly to S3 or local storage
    (based on user preferences), then call POST /upload/{upload_id}/complete
    to trigger processing.
    """
    # Get user-specific storage client and config
    storage, storage_config = get_user_storage(current_user)
    upload_service = UploadService(db, storage, storage_config)

    try:
        response = await upload_service.create_presigned_url(
            user_id=current_user.user_id,
            request=request,
        )
        await db.commit()
        return response

    except UploadError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/{upload_id}/complete", response_model=UploadCompleteResponse)
async def complete_upload(
    upload_id: UUID,
    request: UploadCompleteRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> UploadCompleteResponse:
    """Mark upload as complete and trigger document processing.

    Call this after successfully uploading the file to the pre-signed URL.
    Uses the storage configuration that was set when the upload was initiated.
    """
    # Get user-specific storage client (uses config stored in upload record)
    storage, storage_config = get_user_storage(current_user)
    upload_service = UploadService(db, storage, storage_config)

    try:
        response = await upload_service.complete_upload(
            upload_id=upload_id,
            user_id=current_user.user_id,
            title=request.title,
            doi=request.doi,
        )
        await db.commit()
        return response

    except UploadError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/{upload_id}", response_model=UploadStatusResponse)
async def get_upload_status(
    upload_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    storage: Storage,
) -> UploadStatusResponse:
    """Get the status of an upload."""
    upload_service = UploadService(db, storage)
    upload = await upload_service.get_upload(upload_id)

    if not upload or upload.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )

    return UploadStatusResponse(
        upload_id=upload.upload_id,
        status=upload.status.value if hasattr(upload.status, 'value') else upload.status,
        filename=upload.filename,
        size_bytes=upload.size_bytes,
        content_type=upload.content_type,
        document_id=upload.document_id,
        content_hash=upload.content_hash,
        error_message=upload.error_message,
        created_at=upload.created_at,
        uploaded_at=upload.uploaded_at,
        completed_at=upload.completed_at,
    )


@router.get("/", response_model=list[UploadStatusResponse])
async def list_uploads(
    current_user: CurrentUser,
    db: DBSession,
    storage: Storage,
    limit: int = 20,
    offset: int = 0,
) -> list[UploadStatusResponse]:
    """List user's uploads."""
    upload_service = UploadService(db, storage)
    uploads = await upload_service.get_user_uploads(
        user_id=current_user.user_id,
        limit=min(limit, 100),
        offset=offset,
    )

    return [
        UploadStatusResponse(
            upload_id=upload.upload_id,
            status=upload.status.value if hasattr(upload.status, 'value') else upload.status,
            filename=upload.filename,
            size_bytes=upload.size_bytes,
            content_type=upload.content_type,
            document_id=upload.document_id,
            content_hash=upload.content_hash,
            error_message=upload.error_message,
            created_at=upload.created_at,
            uploaded_at=upload.uploaded_at,
            completed_at=upload.completed_at,
        )
        for upload in uploads
    ]
