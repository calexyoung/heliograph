"""Tests for storage client utilities (S3 and local filesystem)."""

import asyncio
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.utils.s3 import (
    LocalStorageClient,
    S3Client,
    StorageClient,
    get_storage_client,
)


class TestLocalStorageClient:
    """Tests for LocalStorageClient."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def storage_client(self, temp_dir):
        """Create a LocalStorageClient for testing."""
        # Clear any existing tokens from previous tests
        LocalStorageClient._upload_tokens.clear()
        return LocalStorageClient(
            base_path=temp_dir,
            bucket="test-bucket",
            serve_url="http://localhost:8080/files",
        )

    def test_init_creates_storage_directory(self, temp_dir):
        """Test that initialization creates the storage directory."""
        client = LocalStorageClient(
            base_path=temp_dir,
            bucket="my-bucket",
        )
        storage_dir = Path(temp_dir) / "my-bucket"
        assert storage_dir.exists()
        assert storage_dir.is_dir()

    def test_init_default_values(self, temp_dir):
        """Test default initialization values."""
        client = LocalStorageClient(base_path=temp_dir)
        assert client.bucket == "heliograph-documents"
        assert client.serve_url == "http://localhost:8080/files"

    def test_get_full_path(self, storage_client, temp_dir):
        """Test _get_full_path returns correct path."""
        path = storage_client._get_full_path("uploads/test.pdf")
        expected = Path(temp_dir) / "test-bucket" / "uploads/test.pdf"
        assert path == expected

    @pytest.mark.asyncio
    async def test_generate_presigned_upload_url(self, storage_client):
        """Test generating presigned upload URL."""
        result = await storage_client.generate_presigned_upload_url(
            key="uploads/doc.pdf",
            content_type="application/pdf",
            expires_in=3600,
        )

        assert "presigned_url" in result
        assert "expires_at" in result
        assert "local_path" in result
        assert "token" in result
        assert result["presigned_url"].startswith("http://localhost:8080/files/upload/")
        assert isinstance(result["expires_at"], datetime)
        assert result["expires_at"] > datetime.utcnow()

    @pytest.mark.asyncio
    async def test_generate_presigned_upload_url_creates_parent_dirs(
        self, storage_client, temp_dir
    ):
        """Test that presigned upload URL creates parent directories."""
        result = await storage_client.generate_presigned_upload_url(
            key="deep/nested/path/doc.pdf",
        )
        parent_dir = Path(temp_dir) / "test-bucket" / "deep/nested/path"
        assert parent_dir.exists()

    @pytest.mark.asyncio
    async def test_generate_presigned_upload_url_stores_token(self, storage_client):
        """Test that upload token is stored correctly."""
        result = await storage_client.generate_presigned_upload_url(
            key="test.pdf",
            content_type="application/pdf",
        )
        token = result["token"]
        token_data = LocalStorageClient._upload_tokens.get(token)

        assert token_data is not None
        assert token_data["key"] == "test.pdf"
        assert token_data["content_type"] == "application/pdf"
        assert "expires_at" in token_data
        assert "storage_dir" in token_data

    @pytest.mark.asyncio
    async def test_generate_presigned_download_url(self, storage_client):
        """Test generating presigned download URL."""
        result = await storage_client.generate_presigned_download_url(
            key="downloads/doc.pdf",
            expires_in=1800,
        )

        assert "presigned_url" in result
        assert "expires_at" in result
        assert "local_path" in result
        assert result["presigned_url"].startswith("http://localhost:8080/files/download/")
        assert isinstance(result["expires_at"], datetime)

    @pytest.mark.asyncio
    async def test_generate_presigned_download_url_stores_token(self, storage_client):
        """Test that download token is stored with correct type."""
        result = await storage_client.generate_presigned_download_url(key="test.pdf")
        token = result["presigned_url"].split("/")[-1]
        token_data = LocalStorageClient._upload_tokens.get(token)

        assert token_data is not None
        assert token_data["type"] == "download"
        assert token_data["key"] == "test.pdf"

    @pytest.mark.asyncio
    async def test_check_object_exists_true(self, storage_client, temp_dir):
        """Test check_object_exists returns True for existing file."""
        # Create a test file
        test_path = Path(temp_dir) / "test-bucket" / "exists.txt"
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_text("test content")

        result = await storage_client.check_object_exists("exists.txt")
        assert result is True

    @pytest.mark.asyncio
    async def test_check_object_exists_false(self, storage_client):
        """Test check_object_exists returns False for non-existing file."""
        result = await storage_client.check_object_exists("nonexistent.txt")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_object_metadata(self, storage_client, temp_dir):
        """Test getting object metadata."""
        # Create a test file
        test_path = Path(temp_dir) / "test-bucket" / "metadata_test.pdf"
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_content = b"PDF test content here"
        test_path.write_bytes(test_content)

        result = await storage_client.get_object_metadata("metadata_test.pdf")

        assert result is not None
        assert result["content_length"] == len(test_content)
        assert result["content_type"] == "application/pdf"
        assert "last_modified" in result
        assert "etag" in result
        assert result["metadata"] == {}

    @pytest.mark.asyncio
    async def test_get_object_metadata_different_types(self, storage_client, temp_dir):
        """Test content type detection for different file extensions."""
        base_path = Path(temp_dir) / "test-bucket"

        test_cases = [
            ("test.json", "application/json"),
            ("test.txt", "text/plain"),
            ("test.bin", "application/octet-stream"),
        ]

        for filename, expected_type in test_cases:
            file_path = base_path / filename
            file_path.write_bytes(b"test")
            result = await storage_client.get_object_metadata(filename)
            assert result["content_type"] == expected_type, f"Failed for {filename}"

    @pytest.mark.asyncio
    async def test_get_object_metadata_nonexistent(self, storage_client):
        """Test getting metadata for non-existing file returns None."""
        result = await storage_client.get_object_metadata("nonexistent.pdf")
        assert result is None

    @pytest.mark.asyncio
    async def test_download_object(self, storage_client, temp_dir):
        """Test downloading an object."""
        # Create a test file
        test_path = Path(temp_dir) / "test-bucket" / "download_test.txt"
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_content = b"Download this content"
        test_path.write_bytes(test_content)

        result = await storage_client.download_object("download_test.txt")
        assert result == test_content

    @pytest.mark.asyncio
    async def test_download_object_not_found(self, storage_client):
        """Test downloading non-existing object raises exception."""
        with pytest.raises(Exception) as exc_info:
            await storage_client.download_object("nonexistent.txt")
        assert "NoSuchKey" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_upload_bytes(self, storage_client, temp_dir):
        """Test uploading bytes to storage."""
        test_content = b"Uploaded content"
        await storage_client.upload_bytes(
            bucket="test-bucket",
            key="uploaded.txt",
            data=test_content,
            content_type="text/plain",
        )

        # Verify file was created
        file_path = Path(temp_dir) / "test-bucket" / "uploaded.txt"
        assert file_path.exists()
        assert file_path.read_bytes() == test_content

    @pytest.mark.asyncio
    async def test_upload_bytes_creates_directories(self, storage_client, temp_dir):
        """Test upload_bytes creates parent directories."""
        await storage_client.upload_bytes(
            bucket="test-bucket",
            key="deep/nested/uploaded.txt",
            data=b"test",
        )

        file_path = Path(temp_dir) / "test-bucket" / "deep/nested/uploaded.txt"
        assert file_path.exists()

    @pytest.mark.asyncio
    async def test_upload_bytes_different_bucket(self, storage_client, temp_dir):
        """Test upload_bytes to a different bucket."""
        await storage_client.upload_bytes(
            bucket="other-bucket",
            key="file.txt",
            data=b"other bucket content",
        )

        file_path = Path(temp_dir) / "other-bucket" / "file.txt"
        assert file_path.exists()

    @pytest.mark.asyncio
    async def test_write_file_directly(self, storage_client, temp_dir):
        """Test writing file directly using instance bucket."""
        test_content = b"Direct write content"
        await storage_client.write_file_directly("direct.txt", test_content)

        file_path = Path(temp_dir) / "test-bucket" / "direct.txt"
        assert file_path.exists()
        assert file_path.read_bytes() == test_content

    def test_validate_upload_token_valid(self, storage_client):
        """Test validating a valid upload token."""
        # Manually add a token
        token = "test-token-123"
        LocalStorageClient._upload_tokens[token] = {
            "key": "test.pdf",
            "expires_at": datetime.utcnow() + timedelta(hours=1),
        }

        result = LocalStorageClient.validate_upload_token(token)
        assert result is not None
        assert result["key"] == "test.pdf"

    def test_validate_upload_token_invalid(self, storage_client):
        """Test validating an invalid token returns None."""
        result = LocalStorageClient.validate_upload_token("invalid-token")
        assert result is None

    def test_validate_upload_token_expired(self, storage_client):
        """Test validating an expired token returns None and removes it."""
        token = "expired-token"
        LocalStorageClient._upload_tokens[token] = {
            "key": "test.pdf",
            "expires_at": datetime.utcnow() - timedelta(hours=1),
        }

        result = LocalStorageClient.validate_upload_token(token)
        assert result is None
        assert token not in LocalStorageClient._upload_tokens

    def test_consume_upload_token(self, storage_client):
        """Test consuming a token removes it."""
        token = "consume-token"
        LocalStorageClient._upload_tokens[token] = {
            "key": "test.pdf",
            "expires_at": datetime.utcnow() + timedelta(hours=1),
        }

        result = LocalStorageClient.consume_upload_token(token)
        assert result is not None
        assert token not in LocalStorageClient._upload_tokens

    def test_consume_upload_token_invalid(self, storage_client):
        """Test consuming invalid token returns None."""
        result = LocalStorageClient.consume_upload_token("nonexistent")
        assert result is None


class TestS3Client:
    """Tests for S3Client with mocked AWS calls."""

    @pytest.fixture
    def s3_client(self):
        """Create an S3Client for testing."""
        return S3Client(
            bucket="test-bucket",
            region="us-east-1",
            endpoint_url="http://localhost:4566",
        )

    def test_init_default_values(self):
        """Test S3Client initialization with defaults."""
        client = S3Client(bucket="my-bucket")
        assert client.bucket == "my-bucket"
        assert client.region == "us-east-1"
        assert client.endpoint_url is None
        assert client.access_key is None
        assert client.secret_key is None

    def test_init_with_endpoint_uses_test_credentials(self):
        """Test S3Client uses test credentials when endpoint_url is set."""
        client = S3Client(bucket="my-bucket", endpoint_url="http://localhost:4566")
        assert client.access_key == "test"
        assert client.secret_key == "test"

    def test_init_with_explicit_credentials(self):
        """Test S3Client uses provided credentials."""
        client = S3Client(
            bucket="my-bucket",
            endpoint_url="http://localhost:4566",
            access_key="my-key",
            secret_key="my-secret",
        )
        assert client.access_key == "my-key"
        assert client.secret_key == "my-secret"

    @pytest.mark.asyncio
    async def test_generate_presigned_upload_url(self, s3_client):
        """Test generating presigned upload URL with mocked S3."""
        mock_url = "https://bucket.s3.amazonaws.com/key?signature=xxx"

        with patch.object(s3_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.generate_presigned_url = AsyncMock(return_value=mock_url)
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            result = await s3_client.generate_presigned_upload_url(
                key="test/doc.pdf",
                content_type="application/pdf",
                expires_in=3600,
            )

            assert result["presigned_url"] == mock_url
            assert "expires_at" in result
            assert isinstance(result["expires_at"], datetime)
            mock_client.generate_presigned_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_presigned_download_url(self, s3_client):
        """Test generating presigned download URL with mocked S3."""
        mock_url = "https://bucket.s3.amazonaws.com/key?signature=xxx"

        with patch.object(s3_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.generate_presigned_url = AsyncMock(return_value=mock_url)
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            result = await s3_client.generate_presigned_download_url(
                key="test/doc.pdf",
                expires_in=1800,
            )

            assert result["presigned_url"] == mock_url
            assert "expires_at" in result

    @pytest.mark.asyncio
    async def test_check_object_exists_true(self, s3_client):
        """Test check_object_exists returns True when object exists."""
        with patch.object(s3_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.head_object = AsyncMock(return_value={"ContentLength": 100})
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            result = await s3_client.check_object_exists("exists.pdf")
            assert result is True

    @pytest.mark.asyncio
    async def test_check_object_exists_false(self, s3_client):
        """Test check_object_exists returns False when object doesn't exist."""
        with patch.object(s3_client, "_session") as mock_session:
            mock_client = AsyncMock()
            error = Exception("Not Found")
            error.response = {"Error": {"Code": "404"}}
            mock_client.head_object = AsyncMock(side_effect=error)
            mock_client.exceptions = MagicMock()
            mock_client.exceptions.ClientError = Exception
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            result = await s3_client.check_object_exists("nonexistent.pdf")
            assert result is False

    @pytest.mark.asyncio
    async def test_get_object_metadata(self, s3_client):
        """Test getting object metadata from S3."""
        mock_response = {
            "ContentLength": 12345,
            "ContentType": "application/pdf",
            "LastModified": datetime.utcnow(),
            "ETag": '"abc123"',
            "Metadata": {"author": "test"},
        }

        with patch.object(s3_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.head_object = AsyncMock(return_value=mock_response)
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            result = await s3_client.get_object_metadata("test.pdf")

            assert result["content_length"] == 12345
            assert result["content_type"] == "application/pdf"
            assert result["etag"] == '"abc123"'
            assert result["metadata"] == {"author": "test"}

    @pytest.mark.asyncio
    async def test_get_object_metadata_not_found(self, s3_client):
        """Test getting metadata for non-existing object returns None."""
        with patch.object(s3_client, "_session") as mock_session:
            mock_client = AsyncMock()
            error = Exception("Not Found")
            error.response = {"Error": {"Code": "404"}}
            mock_client.head_object = AsyncMock(side_effect=error)
            mock_client.exceptions = MagicMock()
            mock_client.exceptions.ClientError = Exception
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            result = await s3_client.get_object_metadata("nonexistent.pdf")
            assert result is None

    @pytest.mark.asyncio
    async def test_download_object(self, s3_client):
        """Test downloading object from S3."""
        test_content = b"PDF file content"

        with patch.object(s3_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_stream = AsyncMock()
            mock_stream.read = AsyncMock(return_value=test_content)
            mock_response = {"Body": MagicMock()}
            mock_response["Body"].__aenter__ = AsyncMock(return_value=mock_stream)
            mock_response["Body"].__aexit__ = AsyncMock()
            mock_client.get_object = AsyncMock(return_value=mock_response)
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            result = await s3_client.download_object("test.pdf")
            assert result == test_content

    @pytest.mark.asyncio
    async def test_upload_bytes(self, s3_client):
        """Test uploading bytes to S3."""
        test_content = b"Upload this content"

        with patch.object(s3_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.put_object = AsyncMock()
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            await s3_client.upload_bytes(
                bucket="test-bucket",
                key="uploaded.txt",
                data=test_content,
                content_type="text/plain",
                metadata={"custom": "value"},
            )

            mock_client.put_object.assert_called_once()
            call_kwargs = mock_client.put_object.call_args[1]
            assert call_kwargs["Bucket"] == "test-bucket"
            assert call_kwargs["Key"] == "uploaded.txt"
            assert call_kwargs["Body"] == test_content
            assert call_kwargs["ContentType"] == "text/plain"
            assert call_kwargs["Metadata"] == {"custom": "value"}

    @pytest.mark.asyncio
    async def test_upload_bytes_without_metadata(self, s3_client):
        """Test uploading bytes without metadata."""
        with patch.object(s3_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.put_object = AsyncMock()
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            await s3_client.upload_bytes(
                bucket="test-bucket",
                key="uploaded.txt",
                data=b"test",
            )

            call_kwargs = mock_client.put_object.call_args[1]
            assert "Metadata" not in call_kwargs


class TestGetStorageClient:
    """Tests for the get_storage_client factory function."""

    def test_get_local_storage_client(self):
        """Test creating a LocalStorageClient."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = get_storage_client(
                storage_type="local",
                local_path=tmpdir,
                bucket="test-bucket",
            )
            assert isinstance(client, LocalStorageClient)
            assert client.bucket == "test-bucket"

    def test_get_local_storage_client_case_insensitive(self):
        """Test storage_type is case insensitive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = get_storage_client(
                storage_type="LOCAL",
                local_path=tmpdir,
            )
            assert isinstance(client, LocalStorageClient)

    def test_get_local_storage_missing_path_raises(self):
        """Test local storage without path raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_storage_client(storage_type="local")
        assert "local_path is required" in str(exc_info.value)

    def test_get_s3_storage_client(self):
        """Test creating an S3Client."""
        client = get_storage_client(
            storage_type="s3",
            bucket="my-bucket",
            region="eu-west-1",
            endpoint_url="http://localhost:4566",
        )
        assert isinstance(client, S3Client)
        assert client.bucket == "my-bucket"
        assert client.region == "eu-west-1"
        assert client.endpoint_url == "http://localhost:4566"

    def test_get_s3_storage_client_with_credentials(self):
        """Test creating S3Client with credentials."""
        client = get_storage_client(
            storage_type="s3",
            bucket="my-bucket",
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        assert isinstance(client, S3Client)
        assert client.access_key == "AKIAIOSFODNN7EXAMPLE"
        assert client.secret_key == "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

    def test_get_storage_invalid_type_raises(self):
        """Test invalid storage type raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_storage_client(storage_type="invalid")
        assert "Invalid storage_type" in str(exc_info.value)
        assert "invalid" in str(exc_info.value)

    def test_get_storage_default_values(self):
        """Test default values for S3 client."""
        client = get_storage_client()
        assert isinstance(client, S3Client)
        assert client.bucket == "heliograph-documents"
        assert client.region == "us-east-1"


class TestStorageClientInterface:
    """Tests to verify both clients implement the same interface."""

    @pytest.fixture
    def local_client(self):
        """Create LocalStorageClient."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield LocalStorageClient(base_path=tmpdir)

    @pytest.fixture
    def s3_client(self):
        """Create S3Client."""
        return S3Client(bucket="test-bucket")

    def test_local_client_is_storage_client(self, local_client):
        """Test LocalStorageClient is a StorageClient."""
        assert isinstance(local_client, StorageClient)

    def test_s3_client_is_storage_client(self, s3_client):
        """Test S3Client is a StorageClient."""
        assert isinstance(s3_client, StorageClient)

    def test_clients_have_same_methods(self, local_client, s3_client):
        """Test both clients have the same public methods."""
        local_methods = {
            m for m in dir(local_client)
            if not m.startswith("_") and callable(getattr(local_client, m))
        }
        s3_methods = {
            m for m in dir(s3_client)
            if not m.startswith("_") and callable(getattr(s3_client, m))
        }

        # S3Client should have all methods LocalStorageClient has
        # (LocalStorageClient may have extra methods like validate_upload_token)
        abstract_methods = {
            "generate_presigned_upload_url",
            "generate_presigned_download_url",
            "check_object_exists",
            "get_object_metadata",
            "download_object",
            "upload_bytes",
        }
        assert abstract_methods.issubset(local_methods)
        assert abstract_methods.issubset(s3_methods)
