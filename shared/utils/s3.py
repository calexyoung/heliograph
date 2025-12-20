"""Storage client wrappers for S3 and local filesystem."""

import hashlib
import os
import secrets
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiofiles
import aiofiles.os
from aiobotocore.session import get_session

from shared.utils.logging import get_logger

logger = get_logger(__name__)


class StorageClient(ABC):
    """Abstract base class for storage clients."""

    @abstractmethod
    async def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str = "application/pdf",
        expires_in: int = 3600,
    ) -> dict[str, Any]:
        """Generate a URL/path for uploading."""
        pass

    @abstractmethod
    async def generate_presigned_download_url(
        self,
        key: str,
        expires_in: int = 3600,
    ) -> dict[str, Any]:
        """Generate a URL/path for downloading."""
        pass

    @abstractmethod
    async def check_object_exists(self, key: str) -> bool:
        """Check if an object exists."""
        pass

    @abstractmethod
    async def get_object_metadata(self, key: str) -> dict[str, Any] | None:
        """Get object metadata."""
        pass

    @abstractmethod
    async def download_object(self, key: str) -> bytes:
        """Download an object."""
        pass

    @abstractmethod
    async def upload_bytes(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Upload bytes to storage."""
        pass


class LocalStorageClient(StorageClient):
    """Local filesystem storage client with same interface as S3Client."""

    # In-memory store for upload tokens (in production, use Redis)
    _upload_tokens: dict[str, dict[str, Any]] = {}

    def __init__(
        self,
        base_path: str,
        bucket: str = "heliograph-documents",
        serve_url: str = "http://localhost:8080/files",
    ):
        """Initialize local storage client.

        Args:
            base_path: Base directory for file storage
            bucket: Virtual bucket name (used as subdirectory)
            serve_url: Base URL for serving files (for presigned URLs)
        """
        self.base_path = Path(base_path)
        self.bucket = bucket
        self.serve_url = serve_url.rstrip("/")
        self._storage_dir = self.base_path / bucket
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "local_storage_initialized",
            base_path=str(self.base_path),
            bucket=bucket,
            storage_dir=str(self._storage_dir),
        )

    def _get_full_path(self, key: str) -> Path:
        """Get full filesystem path for a key."""
        return self._storage_dir / key

    async def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str = "application/pdf",
        expires_in: int = 3600,
    ) -> dict[str, Any]:
        """Generate upload info for local storage.

        For local storage, we return a token that can be used to upload
        directly, along with the file path.
        """
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        token = secrets.token_urlsafe(32)

        # Store token for validation (include storage_dir for user-specific paths)
        LocalStorageClient._upload_tokens[token] = {
            "key": key,
            "content_type": content_type,
            "expires_at": expires_at,
            "storage_dir": str(self._storage_dir),
        }

        # Ensure directory exists
        full_path = self._get_full_path(key)
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Return a URL that the upload service can use
        # For local dev, clients can PUT directly to this path
        presigned_url = f"{self.serve_url}/upload/{token}"

        logger.info(
            "presigned_upload_url_generated",
            bucket=self.bucket,
            key=key,
            expires_at=expires_at.isoformat(),
            storage_type="local",
        )

        return {
            "presigned_url": presigned_url,
            "expires_at": expires_at,
            "local_path": str(full_path),
            "token": token,
        }

    async def generate_presigned_download_url(
        self,
        key: str,
        expires_in: int = 3600,
    ) -> dict[str, Any]:
        """Generate download URL for local storage."""
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        token = secrets.token_urlsafe(32)

        # Store token for validation (include storage_dir for user-specific paths)
        LocalStorageClient._upload_tokens[token] = {
            "key": key,
            "type": "download",
            "expires_at": expires_at,
            "storage_dir": str(self._storage_dir),
        }

        presigned_url = f"{self.serve_url}/download/{token}"

        return {
            "presigned_url": presigned_url,
            "expires_at": expires_at,
            "local_path": str(self._get_full_path(key)),
        }

    async def check_object_exists(self, key: str) -> bool:
        """Check if a file exists in local storage."""
        full_path = self._get_full_path(key)
        try:
            return await aiofiles.os.path.exists(full_path)
        except Exception:
            return False

    async def get_object_metadata(self, key: str) -> dict[str, Any] | None:
        """Get file metadata from local storage."""
        full_path = self._get_full_path(key)
        try:
            if not await aiofiles.os.path.exists(full_path):
                return None

            stat = await aiofiles.os.stat(full_path)
            # Determine content type from extension
            ext = full_path.suffix.lower()
            content_types = {
                ".pdf": "application/pdf",
                ".json": "application/json",
                ".txt": "text/plain",
            }
            content_type = content_types.get(ext, "application/octet-stream")

            # Calculate ETag (MD5 hash)
            async with aiofiles.open(full_path, "rb") as f:
                content = await f.read()
                etag = hashlib.md5(content).hexdigest()

            return {
                "content_length": stat.st_size,
                "content_type": content_type,
                "last_modified": datetime.fromtimestamp(stat.st_mtime),
                "etag": f'"{etag}"',
                "metadata": {},
            }
        except Exception as e:
            logger.error("get_object_metadata_failed", key=key, error=str(e))
            return None

    async def download_object(self, key: str) -> bytes:
        """Download a file from local storage."""
        full_path = self._get_full_path(key)
        try:
            async with aiofiles.open(full_path, "rb") as f:
                return await f.read()
        except FileNotFoundError:
            raise Exception(
                f"An error occurred (NoSuchKey) when calling the GetObject operation: "
                f"The specified key does not exist."
            )

    async def upload_bytes(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Upload bytes to local storage."""
        # Use the bucket from parameter or instance
        storage_dir = self.base_path / bucket
        storage_dir.mkdir(parents=True, exist_ok=True)
        full_path = storage_dir / key

        # Ensure parent directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(full_path, "wb") as f:
            await f.write(data)

        logger.info("local_storage_upload_complete", bucket=bucket, key=key)

    async def write_file_directly(self, key: str, data: bytes) -> None:
        """Write file directly using instance bucket."""
        full_path = self._get_full_path(key)
        full_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(full_path, "wb") as f:
            await f.write(data)

        logger.info("local_storage_write_complete", key=key)

    @classmethod
    def validate_upload_token(cls, token: str) -> dict[str, Any] | None:
        """Validate an upload token and return its metadata."""
        token_data = cls._upload_tokens.get(token)
        if not token_data:
            return None
        if datetime.utcnow() > token_data["expires_at"]:
            del cls._upload_tokens[token]
            return None
        return token_data

    @classmethod
    def consume_upload_token(cls, token: str) -> dict[str, Any] | None:
        """Validate and consume an upload token."""
        token_data = cls.validate_upload_token(token)
        if token_data:
            del cls._upload_tokens[token]
        return token_data


class S3Client(StorageClient):
    """Async S3 client wrapper."""

    def __init__(
        self,
        bucket: str,
        region: str = "us-east-1",
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
    ):
        """Initialize S3 client.

        Args:
            bucket: S3 bucket name
            region: AWS region
            endpoint_url: Custom endpoint (for LocalStack/MinIO)
            access_key: AWS access key (or fake for LocalStack)
            secret_key: AWS secret key (or fake for LocalStack)
        """
        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url
        # Use fake credentials for LocalStack if endpoint_url is set but no credentials
        self.access_key = access_key or ("test" if endpoint_url else None)
        self.secret_key = secret_key or ("test" if endpoint_url else None)
        self._session = get_session()

    async def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str = "application/pdf",
        expires_in: int = 3600,
    ) -> dict[str, Any]:
        """Generate a pre-signed URL for uploading.

        Args:
            key: S3 object key
            content_type: MIME type of the file
            expires_in: URL expiration time in seconds

        Returns:
            Dict with presigned_url and expires_at
        """
        async with self._session.create_client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        ) as client:
            url = await client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=expires_in,
            )

            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

            logger.info(
                "presigned_upload_url_generated",
                bucket=self.bucket,
                key=key,
                expires_at=expires_at.isoformat(),
            )

            return {
                "presigned_url": url,
                "expires_at": expires_at,
            }

    async def generate_presigned_download_url(
        self,
        key: str,
        expires_in: int = 3600,
    ) -> dict[str, Any]:
        """Generate a pre-signed URL for downloading.

        Args:
            key: S3 object key
            expires_in: URL expiration time in seconds

        Returns:
            Dict with presigned_url and expires_at
        """
        async with self._session.create_client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        ) as client:
            url = await client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                },
                ExpiresIn=expires_in,
            )

            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

            return {
                "presigned_url": url,
                "expires_at": expires_at,
            }

    async def check_object_exists(self, key: str) -> bool:
        """Check if an object exists in S3.

        Args:
            key: S3 object key

        Returns:
            True if object exists, False otherwise
        """
        async with self._session.create_client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        ) as client:
            try:
                await client.head_object(Bucket=self.bucket, Key=key)
                return True
            except client.exceptions.ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    return False
                raise

    async def get_object_metadata(self, key: str) -> dict[str, Any] | None:
        """Get object metadata from S3.

        Args:
            key: S3 object key

        Returns:
            Object metadata dict or None if not found
        """
        async with self._session.create_client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        ) as client:
            try:
                response = await client.head_object(Bucket=self.bucket, Key=key)
                return {
                    "content_length": response.get("ContentLength"),
                    "content_type": response.get("ContentType"),
                    "last_modified": response.get("LastModified"),
                    "etag": response.get("ETag"),
                    "metadata": response.get("Metadata", {}),
                }
            except client.exceptions.ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    return None
                raise

    async def download_object(self, key: str) -> bytes:
        """Download an object from S3.

        Args:
            key: S3 object key

        Returns:
            Object content as bytes

        Raises:
            Exception if object not found or download fails
        """
        async with self._session.create_client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        ) as client:
            response = await client.get_object(Bucket=self.bucket, Key=key)
            async with response["Body"] as stream:
                return await stream.read()

    async def upload_bytes(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Upload bytes to S3.

        Args:
            bucket: S3 bucket name
            key: S3 object key
            data: Bytes to upload
            content_type: MIME type of the content
            metadata: Optional metadata to store with the object
        """
        async with self._session.create_client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        ) as client:
            put_params = {
                "Bucket": bucket,
                "Key": key,
                "Body": data,
                "ContentType": content_type,
            }
            if metadata:
                put_params["Metadata"] = metadata
            await client.put_object(**put_params)
            logger.info("s3_upload_complete", bucket=bucket, key=key)


def get_storage_client(
    storage_type: str = "s3",
    bucket: str = "heliograph-documents",
    region: str = "us-east-1",
    endpoint_url: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    local_path: str | None = None,
    serve_url: str = "http://localhost:8080/files",
) -> StorageClient:
    """Factory function to create the appropriate storage client.

    Args:
        storage_type: Type of storage ('s3' or 'local')
        bucket: S3 bucket name or virtual bucket for local storage
        region: AWS region (S3 only)
        endpoint_url: Custom endpoint URL (S3 only, for LocalStack/MinIO)
        access_key: AWS access key (S3 only)
        secret_key: AWS secret key (S3 only)
        local_path: Base path for local storage (required if storage_type='local')
        serve_url: Base URL for serving files (local storage only)

    Returns:
        StorageClient instance (either S3Client or LocalStorageClient)

    Raises:
        ValueError: If storage_type is invalid or required params are missing
    """
    storage_type = storage_type.lower()

    if storage_type == "local":
        if not local_path:
            raise ValueError("local_path is required for local storage")
        logger.info(
            "creating_storage_client",
            storage_type="local",
            local_path=local_path,
            bucket=bucket,
        )
        return LocalStorageClient(
            base_path=local_path,
            bucket=bucket,
            serve_url=serve_url,
        )
    elif storage_type == "s3":
        logger.info(
            "creating_storage_client",
            storage_type="s3",
            bucket=bucket,
            endpoint_url=endpoint_url,
        )
        return S3Client(
            bucket=bucket,
            region=region,
            endpoint_url=endpoint_url,
            access_key=access_key,
            secret_key=secret_key,
        )
    else:
        raise ValueError(f"Invalid storage_type: {storage_type}. Use 's3' or 'local'")
