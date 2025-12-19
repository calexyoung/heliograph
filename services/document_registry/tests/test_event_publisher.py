"""Tests for Document Event Publisher."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.document_registry.app.db.models import DocumentModel
from services.document_registry.app.events.publisher import DocumentEventPublisher
from shared.schemas.document import DocumentStatus


class TestDocumentEventPublisher:
    """Tests for the DocumentEventPublisher class."""

    @pytest.fixture
    def mock_sqs_client(self):
        """Create mock SQS client."""
        mock = MagicMock()
        mock.send_message = AsyncMock(return_value="test-message-id-123")
        return mock

    @pytest.fixture
    def publisher(self, mock_sqs_client):
        """Create publisher with mock SQS client."""
        return DocumentEventPublisher(mock_sqs_client)

    @pytest.fixture
    def sample_document(self):
        """Create sample document for testing."""
        doc = MagicMock(spec=DocumentModel)
        doc.document_id = uuid4()
        doc.doi = "10.1234/test.doc"
        doc.content_hash = "a" * 64
        doc.title = "Test Document"
        return doc


class TestPublishDocumentRegistered:
    """Tests for publish_document_registered method."""

    @pytest.fixture
    def mock_sqs_client(self):
        """Create mock SQS client."""
        mock = MagicMock()
        mock.send_message = AsyncMock(return_value="test-message-id-123")
        return mock

    @pytest.fixture
    def publisher(self, mock_sqs_client):
        """Create publisher with mock SQS client."""
        return DocumentEventPublisher(mock_sqs_client)

    @pytest.fixture
    def sample_document(self):
        """Create sample document for testing."""
        doc = MagicMock(spec=DocumentModel)
        doc.document_id = uuid4()
        doc.doi = "10.1234/test.doc"
        doc.content_hash = "a" * 64
        doc.title = "Test Document"
        return doc

    @pytest.mark.asyncio
    async def test_publish_document_registered_success(
        self, publisher, mock_sqs_client, sample_document
    ):
        """Test successful document registered event publication."""
        user_id = uuid4()
        s3_key = "documents/test.pdf"

        message_id = await publisher.publish_document_registered(
            document=sample_document,
            s3_key=s3_key,
            user_id=user_id,
        )

        assert message_id == "test-message-id-123"
        mock_sqs_client.send_message.assert_called_once()

        # Verify the event structure
        call_args = mock_sqs_client.send_message.call_args[0][0]
        assert call_args.document_id == sample_document.document_id
        assert call_args.s3_key == s3_key
        assert call_args.user_id == user_id
        assert call_args.doi == sample_document.doi
        assert call_args.content_hash == sample_document.content_hash
        assert call_args.title == sample_document.title

    @pytest.mark.asyncio
    async def test_publish_document_registered_failure(
        self, publisher, mock_sqs_client, sample_document
    ):
        """Test document registered event publication failure."""
        mock_sqs_client.send_message = AsyncMock(side_effect=Exception("SQS error"))

        message_id = await publisher.publish_document_registered(
            document=sample_document,
            s3_key="documents/test.pdf",
            user_id=uuid4(),
        )

        assert message_id is None

    @pytest.mark.asyncio
    async def test_publish_document_registered_includes_correlation_id(
        self, publisher, mock_sqs_client, sample_document
    ):
        """Test that correlation ID is included in event."""
        with patch(
            "services.document_registry.app.events.publisher.get_correlation_id",
            return_value="test-correlation-id"
        ):
            await publisher.publish_document_registered(
                document=sample_document,
                s3_key="documents/test.pdf",
                user_id=uuid4(),
            )

        call_args = mock_sqs_client.send_message.call_args[0][0]
        assert call_args.correlation_id == "test-correlation-id"

    @pytest.mark.asyncio
    async def test_publish_document_registered_includes_timestamp(
        self, publisher, mock_sqs_client, sample_document
    ):
        """Test that timestamp is included in event."""
        await publisher.publish_document_registered(
            document=sample_document,
            s3_key="documents/test.pdf",
            user_id=uuid4(),
        )

        call_args = mock_sqs_client.send_message.call_args[0][0]
        assert call_args.timestamp is not None
        assert isinstance(call_args.timestamp, datetime)
        # Should have timezone info
        assert call_args.timestamp.tzinfo is not None


class TestPublishDuplicateDetected:
    """Tests for publish_duplicate_detected method."""

    @pytest.fixture
    def mock_sqs_client(self):
        """Create mock SQS client."""
        mock = MagicMock()
        mock.send_message = AsyncMock(return_value="test-message-id-456")
        return mock

    @pytest.fixture
    def publisher(self, mock_sqs_client):
        """Create publisher with mock SQS client."""
        return DocumentEventPublisher(mock_sqs_client)

    @pytest.mark.asyncio
    async def test_publish_duplicate_detected_success(self, publisher, mock_sqs_client):
        """Test successful duplicate detected event publication."""
        existing_document_id = uuid4()
        user_id = uuid4()

        message_id = await publisher.publish_duplicate_detected(
            content_hash="b" * 64,
            existing_document_id=existing_document_id,
            match_type="doi",
            user_id=user_id,
        )

        assert message_id == "test-message-id-456"
        mock_sqs_client.send_message.assert_called_once()

        # Verify event structure
        call_args = mock_sqs_client.send_message.call_args[0][0]
        assert call_args.existing_document_id == existing_document_id
        assert call_args.match_type == "doi"
        assert call_args.user_id == user_id

    @pytest.mark.asyncio
    async def test_publish_duplicate_detected_failure(self, publisher, mock_sqs_client):
        """Test duplicate detected event publication failure."""
        mock_sqs_client.send_message = AsyncMock(side_effect=Exception("SQS error"))

        message_id = await publisher.publish_duplicate_detected(
            content_hash="b" * 64,
            existing_document_id=uuid4(),
            match_type="content_hash",
            user_id=uuid4(),
        )

        assert message_id is None

    @pytest.mark.asyncio
    async def test_publish_duplicate_detected_with_different_match_types(
        self, publisher, mock_sqs_client
    ):
        """Test duplicate event with different match types."""
        match_types = ["doi", "content_hash", "composite", "fuzzy_title"]

        for match_type in match_types:
            mock_sqs_client.send_message.reset_mock()

            await publisher.publish_duplicate_detected(
                content_hash="c" * 64,
                existing_document_id=uuid4(),
                match_type=match_type,
                user_id=uuid4(),
            )

            call_args = mock_sqs_client.send_message.call_args[0][0]
            assert call_args.match_type == match_type


class TestPublishStateTransitionFailed:
    """Tests for publish_state_transition_failed method."""

    @pytest.fixture
    def mock_sqs_client(self):
        """Create mock SQS client."""
        mock = MagicMock()
        mock.send_message = AsyncMock(return_value="test-message-id-789")
        return mock

    @pytest.fixture
    def publisher(self, mock_sqs_client):
        """Create publisher with mock SQS client."""
        return DocumentEventPublisher(mock_sqs_client)

    @pytest.mark.asyncio
    async def test_publish_state_transition_failed_success(
        self, publisher, mock_sqs_client
    ):
        """Test successful state transition failed event publication."""
        document_id = uuid4()

        message_id = await publisher.publish_state_transition_failed(
            document_id=document_id,
            from_state="registered",
            to_state="processing",
            error_message="Optimistic lock conflict",
            worker_id="worker-1",
        )

        assert message_id == "test-message-id-789"
        mock_sqs_client.send_message.assert_called_once()

        # Verify event structure
        call_args = mock_sqs_client.send_message.call_args[0][0]
        assert call_args.document_id == document_id
        assert call_args.from_state == "registered"
        assert call_args.to_state == "processing"
        assert call_args.error_message == "Optimistic lock conflict"
        assert call_args.worker_id == "worker-1"

    @pytest.mark.asyncio
    async def test_publish_state_transition_failed_failure(
        self, publisher, mock_sqs_client
    ):
        """Test state transition failed event publication failure."""
        mock_sqs_client.send_message = AsyncMock(side_effect=Exception("SQS error"))

        message_id = await publisher.publish_state_transition_failed(
            document_id=uuid4(),
            from_state="processing",
            to_state="indexed",
            error_message="Some error",
            worker_id="worker-2",
        )

        assert message_id is None

    @pytest.mark.asyncio
    async def test_publish_state_transition_failed_includes_correlation_id(
        self, publisher, mock_sqs_client
    ):
        """Test that correlation ID is included in failure event."""
        with patch(
            "services.document_registry.app.events.publisher.get_correlation_id",
            return_value="failure-correlation-id"
        ):
            await publisher.publish_state_transition_failed(
                document_id=uuid4(),
                from_state="registered",
                to_state="processing",
                error_message="Lock conflict",
                worker_id="worker-1",
            )

        call_args = mock_sqs_client.send_message.call_args[0][0]
        assert call_args.correlation_id == "failure-correlation-id"


class TestEventPublisherMetrics:
    """Tests for event publisher metrics."""

    @pytest.fixture
    def mock_sqs_client(self):
        """Create mock SQS client."""
        mock = MagicMock()
        mock.send_message = AsyncMock(return_value="test-message-id")
        return mock

    @pytest.fixture
    def publisher(self, mock_sqs_client):
        """Create publisher with mock SQS client."""
        return DocumentEventPublisher(mock_sqs_client)

    @pytest.fixture
    def sample_document(self):
        """Create sample document for testing."""
        doc = MagicMock(spec=DocumentModel)
        doc.document_id = uuid4()
        doc.doi = "10.1234/metrics.doc"
        doc.content_hash = "d" * 64
        doc.title = "Metrics Test Document"
        return doc

    @pytest.mark.asyncio
    async def test_metrics_incremented_on_success(
        self, publisher, mock_sqs_client, sample_document
    ):
        """Test that success metrics are incremented."""
        with patch(
            "services.document_registry.app.events.publisher.EVENTS_PUBLISHED"
        ) as mock_published:
            await publisher.publish_document_registered(
                document=sample_document,
                s3_key="test.pdf",
                user_id=uuid4(),
            )

            mock_published.labels.assert_called_with(event_type="DocumentRegistered")
            mock_published.labels().inc.assert_called_once()

    @pytest.mark.asyncio
    async def test_metrics_incremented_on_failure(
        self, publisher, mock_sqs_client, sample_document
    ):
        """Test that failure metrics are incremented."""
        mock_sqs_client.send_message = AsyncMock(side_effect=Exception("Error"))

        with patch(
            "services.document_registry.app.events.publisher.EVENTS_FAILED"
        ) as mock_failed:
            await publisher.publish_document_registered(
                document=sample_document,
                s3_key="test.pdf",
                user_id=uuid4(),
            )

            mock_failed.labels.assert_called_with(event_type="DocumentRegistered")
            mock_failed.labels().inc.assert_called_once()


class TestEventPublisherConcurrency:
    """Tests for concurrent event publishing scenarios."""

    @pytest.fixture
    def mock_sqs_client(self):
        """Create mock SQS client."""
        mock = MagicMock()
        call_count = 0

        async def mock_send(event):
            nonlocal call_count
            call_count += 1
            return f"message-{call_count}"

        mock.send_message = AsyncMock(side_effect=mock_send)
        return mock

    @pytest.fixture
    def publisher(self, mock_sqs_client):
        """Create publisher with mock SQS client."""
        return DocumentEventPublisher(mock_sqs_client)

    @pytest.mark.asyncio
    async def test_multiple_events_published_sequentially(
        self, publisher, mock_sqs_client
    ):
        """Test publishing multiple events sequentially."""
        import asyncio

        tasks = []
        for i in range(5):
            doc = MagicMock(spec=DocumentModel)
            doc.document_id = uuid4()
            doc.doi = f"10.1234/concurrent.{i}"
            doc.content_hash = f"{i}" * 64
            doc.title = f"Concurrent Document {i}"

            tasks.append(
                publisher.publish_document_registered(
                    document=doc,
                    s3_key=f"documents/{i}.pdf",
                    user_id=uuid4(),
                )
            )

        results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(r is not None for r in results)
        assert len(set(results)) == 5  # All unique message IDs
        assert mock_sqs_client.send_message.call_count == 5
