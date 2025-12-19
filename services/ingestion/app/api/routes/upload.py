"""Upload API endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from services.ingestion.app.api.deps import get_upload_handler
from services.ingestion.app.upload.handler import UploadHandler
from shared.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("")
async def upload_pdf(
    file: Annotated[UploadFile, File(description="PDF file to upload")],
    document_id: Annotated[str | None, Form(description="Document ID (generated if not provided)")] = None,
    upload_handler: UploadHandler = Depends(get_upload_handler),
):
    """Upload a PDF file directly.

    The PDF will be:
    1. Validated
    2. Stored in S3
    3. Associated with the document ID

    Returns S3 key and content hash for registration.
    """
    # Validate content type
    if file.content_type and file.content_type != "application/pdf":
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail="File must be a PDF",
            )

    # Generate document ID if not provided
    if not document_id:
        document_id = str(uuid.uuid4())

    # Upload file
    result = await upload_handler.upload_from_file(
        file=file.file,
        filename=file.filename or "upload.pdf",
        document_id=document_id,
    )

    if not result["success"]:
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Upload failed"),
        )

    return {
        "document_id": document_id,
        "s3_key": result["s3_key"],
        "content_hash": result["content_hash"],
        "size_bytes": result["size_bytes"],
        "page_count": result.get("page_count"),
    }


@router.post("/from-url")
async def upload_from_url(
    url: str = Form(..., description="URL to PDF"),
    document_id: str | None = Form(None, description="Document ID (generated if not provided)"),
    upload_handler: UploadHandler = Depends(get_upload_handler),
):
    """Upload a PDF from URL.

    Downloads the PDF from the provided URL and stores it in S3.
    """
    # Generate document ID if not provided
    if not document_id:
        document_id = str(uuid.uuid4())

    result = await upload_handler.upload_from_url(
        url=url,
        document_id=document_id,
    )

    if not result["success"]:
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Download failed"),
        )

    return {
        "document_id": document_id,
        "s3_key": result["s3_key"],
        "content_hash": result["content_hash"],
        "size_bytes": result["size_bytes"],
        "page_count": result.get("page_count"),
        "source_url": result.get("source_url"),
    }


@router.get("/check-existing")
async def check_existing(
    content_hash: str = Query(..., description="SHA-256 hash of PDF content"),
    upload_handler: UploadHandler = Depends(get_upload_handler),
):
    """Check if PDF with given hash already exists.

    Use this before uploading to detect duplicates.
    """
    existing = await upload_handler.check_existing(content_hash)

    return {
        "exists": existing is not None,
        "s3_key": existing,
    }


@router.get("/download-url")
async def get_download_url(
    s3_key: str = Query(..., description="S3 object key"),
    expires_in: int = Query(3600, ge=60, le=86400, description="URL expiration in seconds"),
    upload_handler: UploadHandler = Depends(get_upload_handler),
):
    """Generate pre-signed download URL for a PDF.

    The URL will be valid for the specified duration.
    """
    url = await upload_handler.get_download_url(s3_key, expires_in=expires_in)

    if not url:
        raise HTTPException(
            status_code=404,
            detail="PDF not found",
        )

    return {
        "download_url": url,
        "expires_in": expires_in,
    }


@router.delete("/{document_id}")
async def delete_pdf(
    document_id: str,
    s3_key: str = Query(..., description="S3 object key"),
    upload_handler: UploadHandler = Depends(get_upload_handler),
):
    """Delete a PDF from storage.

    Requires both document ID and S3 key for verification.
    """
    # Verify the s3_key belongs to this document
    if document_id not in s3_key:
        raise HTTPException(
            status_code=403,
            detail="S3 key does not match document ID",
        )

    success = await upload_handler.delete_pdf(s3_key)

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Delete failed",
        )

    return {"deleted": True}
