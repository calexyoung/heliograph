"""Upload service for handling file uploads."""

import hashlib
from datetime import datetime, timedelta
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_gateway.app.auth.models import UploadModel, UploadStatus
from services.api_gateway.app.config import get_settings
from services.api_gateway.app.upload.schemas import (
    PresignedUrlRequest,
    PresignedUrlResponse,
    UploadCompleteResponse,
)
from shared.utils.logging import get_logger
from shared.utils.s3 import StorageClient

logger = get_logger(__name__)

# Get URLs from settings (supports both local dev and Docker)
_settings = get_settings()
DOCUMENT_REGISTRY_URL = _settings.document_registry_url
DOCUMENT_PROCESSING_URL = "http://localhost:8003"  # Document processing service


class UploadError(Exception):
    """Upload operation error."""

    pass


class UploadService:
    """Service for handling file uploads."""

    def __init__(
        self,
        session: AsyncSession,
        storage_client: StorageClient,
        storage_config: dict | None = None,
    ):
        """Initialize upload service.

        Args:
            session: Database session
            storage_client: Storage client (S3 or local)
            storage_config: User's storage configuration (type, local_path, bucket)
        """
        self.session = session
        self.storage_client = storage_client
        self.storage_config = storage_config or {"type": "s3"}
        self.settings = get_settings()

    async def create_presigned_url(
        self,
        user_id: UUID,
        request: PresignedUrlRequest,
    ) -> PresignedUrlResponse:
        """Create a pre-signed URL for file upload.

        Args:
            user_id: User making the upload
            request: Pre-signed URL request

        Returns:
            Pre-signed URL response

        Raises:
            UploadError: If validation fails
        """
        # Validate file size
        max_size = self.settings.max_upload_size_mb * 1024 * 1024
        if request.size_bytes > max_size:
            raise UploadError(
                f"File size exceeds maximum of {self.settings.max_upload_size_mb}MB"
            )

        # Determine bucket based on storage config
        bucket = self.storage_config.get("bucket") or self.settings.s3_bucket

        # Create upload record with storage configuration
        upload = UploadModel(
            user_id=user_id,
            filename=request.filename,
            content_type=request.content_type,
            size_bytes=request.size_bytes,
            s3_bucket=bucket,
            s3_key=f"uploads/{user_id}/{datetime.utcnow().strftime('%Y/%m/%d')}/pending",
            status=UploadStatus.PENDING.value,
            storage_config=self.storage_config,
        )

        self.session.add(upload)
        await self.session.flush()

        # Update S3 key with upload_id
        upload.s3_key = f"uploads/{upload.upload_id}/document.pdf"
        await self.session.flush()

        # Generate pre-signed URL
        result = await self.storage_client.generate_presigned_upload_url(
            key=upload.s3_key,
            content_type=request.content_type,
            expires_in=self.settings.presigned_url_expiry_seconds,
        )

        # Rewrite presigned URL to use public endpoint for browser access
        presigned_url = result["presigned_url"]
        if self.settings.s3_endpoint_url and self.settings.s3_public_endpoint_url:
            presigned_url = presigned_url.replace(
                self.settings.s3_endpoint_url,
                self.settings.s3_public_endpoint_url,
            )

        logger.info(
            "presigned_url_created",
            upload_id=str(upload.upload_id),
            user_id=str(user_id),
            filename=request.filename,
        )

        return PresignedUrlResponse(
            upload_id=upload.upload_id,
            presigned_url=presigned_url,
            expires_at=result["expires_at"],
            s3_key=upload.s3_key,
            max_size_bytes=max_size,
        )

    async def get_upload(self, upload_id: UUID) -> UploadModel | None:
        """Get upload record by ID.

        Args:
            upload_id: Upload UUID

        Returns:
            Upload model or None
        """
        query = select(UploadModel).where(UploadModel.upload_id == upload_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_user_uploads(
        self,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[UploadModel]:
        """Get uploads for a user.

        Args:
            user_id: User UUID
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of upload models
        """
        query = (
            select(UploadModel)
            .where(UploadModel.user_id == user_id)
            .order_by(UploadModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def complete_upload(
        self,
        upload_id: UUID,
        user_id: UUID,
        title: str | None = None,
        doi: str | None = None,
    ) -> UploadCompleteResponse:
        """Mark an upload as complete and trigger registration.

        Args:
            upload_id: Upload UUID
            user_id: User UUID (for verification)
            title: Optional document title
            doi: Optional document DOI

        Returns:
            Upload completion response

        Raises:
            UploadError: If upload not found or not owned by user
        """
        upload = await self.get_upload(upload_id)

        if not upload:
            raise UploadError("Upload not found")

        if upload.user_id != user_id:
            raise UploadError("Upload not found")  # Don't reveal existence

        if upload.status != UploadStatus.PENDING.value:
            raise UploadError(f"Upload is already in status: {upload.status}")

        # Verify file exists in S3
        exists = await self.storage_client.check_object_exists(upload.s3_key)
        if not exists:
            raise UploadError("File not found in storage. Please upload again.")

        # Get file metadata
        metadata = await self.storage_client.get_object_metadata(upload.s3_key)
        if metadata:
            # Verify size matches
            if metadata["content_length"] != upload.size_bytes:
                logger.warning(
                    "upload_size_mismatch",
                    upload_id=str(upload_id),
                    expected=upload.size_bytes,
                    actual=metadata["content_length"],
                )
                upload.size_bytes = metadata["content_length"]

        # Update status
        upload.status = UploadStatus.UPLOADED.value
        upload.uploaded_at = datetime.utcnow()

        # Download file and calculate content hash
        try:
            file_content = await self.storage_client.download_object(upload.s3_key)
            content_hash = hashlib.sha256(file_content).hexdigest()
            upload.content_hash = content_hash
        except Exception as e:
            logger.error("content_hash_calculation_failed", error=str(e))
            raise UploadError(f"Failed to process uploaded file: {e}")

        # Register document with Document Registry
        try:
            # Extract title from filename (remove extension)
            doc_title = title or upload.filename.rsplit(".", 1)[0]

            registration_request = {
                "content_hash": content_hash,
                "title": doc_title,
                "source": "upload",
                "upload_id": str(upload_id),
                "user_id": str(user_id),
                "s3_key": upload.s3_key,
            }
            if doi:
                registration_request["doi"] = doi

            # Include storage configuration for document processing
            if upload.storage_config:
                registration_request["storage_config"] = upload.storage_config

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{DOCUMENT_REGISTRY_URL}/registry/documents",
                    json=registration_request,
                )
                response.raise_for_status()
                reg_result = response.json()

                upload.document_id = UUID(reg_result["document_id"])
                upload.status = UploadStatus.PROCESSING.value

                logger.info(
                    "document_registered",
                    upload_id=str(upload_id),
                    document_id=reg_result["document_id"],
                    registration_status=reg_result["status"],
                )

                # Update registry with S3 key for processing
                try:
                    await client.patch(
                        f"{DOCUMENT_REGISTRY_URL}/registry/documents/{reg_result['document_id']}",
                        json={"artifact_pointers": {"pdf": upload.s3_key}},
                    )
                except Exception as e:
                    logger.warning("artifact_pointer_update_failed", error=str(e))

                # Trigger document processing
                try:
                    process_response = await client.post(
                        f"{DOCUMENT_PROCESSING_URL}/api/v1/processing/reprocess",
                        json={"document_id": reg_result["document_id"]},
                        timeout=10.0,  # Short timeout, processing runs async
                    )
                    if process_response.status_code == 200:
                        logger.info(
                            "document_processing_triggered",
                            document_id=reg_result["document_id"],
                        )
                    else:
                        logger.warning(
                            "document_processing_trigger_failed",
                            document_id=reg_result["document_id"],
                            status=process_response.status_code,
                        )
                except Exception as e:
                    logger.warning("document_processing_trigger_error", error=str(e))

        except httpx.HTTPStatusError as e:
            logger.error(
                "document_registration_failed",
                upload_id=str(upload_id),
                status_code=e.response.status_code,
                response=e.response.text,
            )
            upload.status = UploadStatus.FAILED.value
            upload.error_message = f"Registration failed: {e.response.text}"
        except Exception as e:
            logger.error("document_registration_error", error=str(e))
            upload.status = UploadStatus.FAILED.value
            upload.error_message = f"Registration error: {str(e)}"

        await self.session.flush()

        logger.info(
            "upload_complete",
            upload_id=str(upload_id),
            user_id=str(user_id),
        )

        return UploadCompleteResponse(
            upload_id=upload.upload_id,
            document_id=upload.document_id,
            status=upload.status.value if hasattr(upload.status, 'value') else upload.status,
            content_hash=upload.content_hash,
            message="Upload received. Document is being processed." if upload.document_id else upload.error_message or "Upload failed",
        )

    async def mark_completed(
        self,
        upload_id: UUID,
        document_id: UUID,
        content_hash: str,
    ) -> None:
        """Mark upload as completed with document registration info.

        Args:
            upload_id: Upload UUID
            document_id: Registered document ID
            content_hash: Document content hash
        """
        upload = await self.get_upload(upload_id)
        if not upload:
            return

        upload.status = UploadStatus.COMPLETED.value
        upload.document_id = document_id
        upload.content_hash = content_hash
        upload.completed_at = datetime.utcnow()

        await self.session.flush()

        logger.info(
            "upload_registration_complete",
            upload_id=str(upload_id),
            document_id=str(document_id),
        )

    async def mark_failed(
        self,
        upload_id: UUID,
        error_message: str,
    ) -> None:
        """Mark upload as failed.

        Args:
            upload_id: Upload UUID
            error_message: Error description
        """
        upload = await self.get_upload(upload_id)
        if not upload:
            return

        upload.status = UploadStatus.FAILED.value
        upload.error_message = error_message

        await self.session.flush()

        logger.error(
            "upload_failed",
            upload_id=str(upload_id),
            error=error_message,
        )
