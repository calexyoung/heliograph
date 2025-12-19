"""PDF upload handling."""

import hashlib
import tempfile
from pathlib import Path
from typing import BinaryIO

import httpx

from services.ingestion.app.config import settings
from services.ingestion.app.upload.processor import PDFProcessor
from shared.utils.logging import get_logger
from shared.utils.s3 import S3Client

logger = get_logger(__name__)


class UploadHandler:
    """Handle PDF uploads from various sources."""

    def __init__(
        self,
        s3_client: S3Client | None = None,
        pdf_processor: PDFProcessor | None = None,
    ):
        """Initialize upload handler.

        Args:
            s3_client: S3 client for storage
            pdf_processor: PDF processor for validation
        """
        self.s3_client = s3_client or S3Client(
            bucket=settings.s3_bucket,
            region=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
        )
        self.pdf_processor = pdf_processor or PDFProcessor()

    async def upload_from_file(
        self,
        file: BinaryIO,
        filename: str,
        document_id: str,
    ) -> dict:
        """Upload PDF from file object.

        Args:
            file: File object
            filename: Original filename
            document_id: Associated document ID

        Returns:
            Upload result with s3_key and content_hash
        """
        # Read file content
        content = file.read()

        # Calculate content hash
        content_hash = hashlib.sha256(content).hexdigest()

        # Validate PDF
        validation = await self.pdf_processor.validate_pdf(content)
        if not validation["valid"]:
            logger.warning(
                "pdf_validation_failed",
                document_id=document_id,
                error=validation.get("error"),
            )
            return {
                "success": False,
                "error": validation.get("error", "Invalid PDF"),
            }

        # Generate S3 key
        s3_key = f"documents/{document_id}/{content_hash}.pdf"

        # Upload to S3
        try:
            await self.s3_client.upload_bytes(
                bucket=settings.s3_bucket,
                key=s3_key,
                data=content,
                content_type="application/pdf",
                metadata={
                    "document_id": document_id,
                    "original_filename": filename,
                    "content_hash": content_hash,
                },
            )

            logger.info(
                "pdf_uploaded",
                document_id=document_id,
                s3_key=s3_key,
                size_bytes=len(content),
            )

            return {
                "success": True,
                "s3_key": s3_key,
                "content_hash": content_hash,
                "size_bytes": len(content),
                "page_count": validation.get("page_count"),
            }

        except Exception as e:
            logger.error(
                "pdf_upload_error",
                document_id=document_id,
                error=str(e),
            )
            return {
                "success": False,
                "error": f"Upload failed: {str(e)}",
            }

    async def upload_from_url(
        self,
        url: str,
        document_id: str,
    ) -> dict:
        """Download and upload PDF from URL.

        Args:
            url: PDF URL
            document_id: Associated document ID

        Returns:
            Upload result with s3_key and content_hash
        """
        try:
            # Download PDF
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(60.0),
                follow_redirects=True,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

                content = response.content

                # Verify content type
                content_type = response.headers.get("content-type", "")
                if "pdf" not in content_type.lower() and not content.startswith(b"%PDF"):
                    return {
                        "success": False,
                        "error": f"Not a PDF: {content_type}",
                    }

            # Calculate content hash
            content_hash = hashlib.sha256(content).hexdigest()

            # Validate PDF
            validation = await self.pdf_processor.validate_pdf(content)
            if not validation["valid"]:
                return {
                    "success": False,
                    "error": validation.get("error", "Invalid PDF"),
                }

            # Generate S3 key
            s3_key = f"documents/{document_id}/{content_hash}.pdf"

            # Upload to S3
            await self.s3_client.upload_bytes(
                bucket=settings.s3_bucket,
                key=s3_key,
                data=content,
                content_type="application/pdf",
                metadata={
                    "document_id": document_id,
                    "source_url": url,
                    "content_hash": content_hash,
                },
            )

            logger.info(
                "pdf_downloaded_and_uploaded",
                document_id=document_id,
                source_url=url,
                s3_key=s3_key,
                size_bytes=len(content),
            )

            return {
                "success": True,
                "s3_key": s3_key,
                "content_hash": content_hash,
                "size_bytes": len(content),
                "page_count": validation.get("page_count"),
                "source_url": url,
            }

        except httpx.HTTPStatusError as e:
            logger.warning(
                "pdf_download_http_error",
                document_id=document_id,
                url=url,
                status=e.response.status_code,
            )
            return {
                "success": False,
                "error": f"Download failed: HTTP {e.response.status_code}",
            }

        except Exception as e:
            logger.error(
                "pdf_download_error",
                document_id=document_id,
                url=url,
                error=str(e),
            )
            return {
                "success": False,
                "error": f"Download failed: {str(e)}",
            }

    async def check_existing(self, content_hash: str) -> str | None:
        """Check if PDF with hash already exists.

        Args:
            content_hash: SHA-256 hash of PDF content

        Returns:
            S3 key if exists, None otherwise
        """
        # List objects with hash prefix
        prefix = f"documents/"

        try:
            objects = await self.s3_client.list_objects(
                bucket=settings.s3_bucket,
                prefix=prefix,
            )

            # Search for matching hash in keys
            for obj in objects:
                if content_hash in obj.get("Key", ""):
                    return obj["Key"]

            return None

        except Exception as e:
            logger.error("check_existing_error", error=str(e))
            return None

    async def get_download_url(
        self,
        s3_key: str,
        expires_in: int = 3600,
    ) -> str | None:
        """Generate pre-signed download URL.

        Args:
            s3_key: S3 object key
            expires_in: URL expiration in seconds

        Returns:
            Pre-signed URL or None
        """
        try:
            return await self.s3_client.generate_presigned_url(
                bucket=settings.s3_bucket,
                key=s3_key,
                operation="get_object",
                expires_in=expires_in,
            )
        except Exception as e:
            logger.error("generate_url_error", s3_key=s3_key, error=str(e))
            return None

    async def delete_pdf(self, s3_key: str) -> bool:
        """Delete PDF from S3.

        Args:
            s3_key: S3 object key

        Returns:
            True if deleted successfully
        """
        try:
            await self.s3_client.delete_object(
                bucket=settings.s3_bucket,
                key=s3_key,
            )
            logger.info("pdf_deleted", s3_key=s3_key)
            return True
        except Exception as e:
            logger.error("pdf_delete_error", s3_key=s3_key, error=str(e))
            return False
