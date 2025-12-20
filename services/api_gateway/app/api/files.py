"""File storage routes for local filesystem storage."""

from pathlib import Path
from typing import Annotated

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse

from services.api_gateway.app.config import get_settings
from shared.utils.logging import get_logger
from shared.utils.s3 import LocalStorageClient

router = APIRouter(prefix="/files", tags=["files"])

logger = get_logger(__name__)


def get_local_storage() -> LocalStorageClient:
    """Get local storage client for handling file uploads/downloads.

    This is always enabled because users may have local storage preferences
    even when the system default is S3. The actual storage path comes from
    the upload token, not from this default client.
    """
    # Use /tmp as base path for the dependency injection default.
    # The actual user-specific path is stored in upload tokens and used
    # when processing uploads/downloads.
    base_path = "/tmp/heliograph_storage"
    return LocalStorageClient(
        base_path=base_path,
        bucket="heliograph-documents",
        serve_url="http://localhost:8080/files",
    )


LocalStorage = Annotated[LocalStorageClient, Depends(get_local_storage)]


@router.put("/upload/{token}")
async def upload_file_with_token(
    token: str,
    request: Request,
    storage: LocalStorage,
):
    """Handle file upload for local storage using token-based authentication.

    The LocalStorageClient generates presigned URLs in the format:
    /files/upload/{token}

    The token is validated against stored upload tokens.
    """
    # Validate the upload token
    token_data = LocalStorageClient._upload_tokens.get(token)
    if not token_data:
        logger.warning("invalid_upload_token", token=token[:8] + "...")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired upload token",
        )

    # Get the key from token data
    key = token_data.get("key")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token data",
        )

    # Remove used token (one-time use)
    del LocalStorageClient._upload_tokens[token]

    # Read the file content
    content = await request.body()

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file content provided",
        )

    # Store the file using storage_dir from token (supports user-specific paths)
    storage_dir = Path(token_data.get("storage_dir", str(storage._storage_dir)))
    file_path = storage_dir / key
    file_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    logger.info(
        "file_uploaded",
        key=key,
        size=len(content),
    )

    return Response(status_code=status.HTTP_200_OK)


@router.get("/download/{token}")
async def download_file_with_token(
    token: str,
    storage: LocalStorage,
):
    """Handle file download for local storage using token-based authentication.

    The LocalStorageClient generates presigned URLs in the format:
    /files/download/{token}

    The token is validated against stored download tokens.
    """
    # Validate the download token
    token_data = LocalStorageClient._upload_tokens.get(token)
    if not token_data or token_data.get("type") != "download":
        logger.warning("invalid_download_token", token=token[:8] + "...")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired download token",
        )

    # Get the key from token data
    key = token_data.get("key")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token data",
        )

    # Don't remove download tokens - they can be reused within expiry time
    # (You might want to remove them for one-time use or check expiry)

    # Get the file path using storage_dir from token (supports user-specific paths)
    storage_dir = Path(token_data.get("storage_dir", str(storage._storage_dir)))
    file_path = storage_dir / key

    # Check if file exists
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    logger.info(
        "file_downloaded",
        key=key,
    )

    # Determine content type based on file extension
    content_type = "application/octet-stream"
    if file_path.suffix.lower() == ".pdf":
        content_type = "application/pdf"
    elif file_path.suffix.lower() == ".json":
        content_type = "application/json"
    elif file_path.suffix.lower() == ".txt":
        content_type = "text/plain"

    return FileResponse(
        path=file_path,
        media_type=content_type,
        filename=file_path.name,
    )
