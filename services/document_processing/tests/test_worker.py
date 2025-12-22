"""Tests for pipeline worker."""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.document_processing.app.core.schemas import (
    DocumentRegisteredEvent,
    ProcessingResult,
)


class TestPipelineWorkerInit:
    """Tests for PipelineWorker initialization."""

    @patch("services.document_processing.app.pipeline.worker.settings")
    @patch("services.document_processing.app.pipeline.worker.create_async_engine")
    @patch("services.document_processing.app.pipeline.worker.SQSClient")
    def test_init_with_defaults(self, mock_sqs, mock_engine, mock_settings):
        """Test initialization with default values."""
        mock_settings.DATABASE_URL = "postgresql+asyncpg://test"
        mock_settings.DEBUG = False
        mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"
        mock_settings.AWS_REGION = "us-east-1"
        mock_settings.SQS_ENDPOINT_URL = None

        from services.document_processing.app.pipeline.worker import PipelineWorker

        worker = PipelineWorker()

        assert worker.worker_id.startswith("worker-")
        assert worker.max_concurrent == 5
        assert worker.running is False
        assert len(worker._tasks) == 0

    @patch("services.document_processing.app.pipeline.worker.settings")
    @patch("services.document_processing.app.pipeline.worker.create_async_engine")
    @patch("services.document_processing.app.pipeline.worker.SQSClient")
    def test_init_with_custom_values(self, mock_sqs, mock_engine, mock_settings):
        """Test initialization with custom values."""
        mock_settings.DATABASE_URL = "postgresql+asyncpg://test"
        mock_settings.DEBUG = True
        mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"
        mock_settings.AWS_REGION = "us-west-2"
        mock_settings.SQS_ENDPOINT_URL = "http://localhost:4566"

        from services.document_processing.app.pipeline.worker import PipelineWorker

        worker = PipelineWorker(worker_id="custom-worker", max_concurrent=10)

        assert worker.worker_id == "custom-worker"
        assert worker.max_concurrent == 10

    @patch("services.document_processing.app.pipeline.worker.settings")
    @patch("services.document_processing.app.pipeline.worker.create_async_engine")
    @patch("services.document_processing.app.pipeline.worker.SQSClient")
    def test_init_creates_semaphore(self, mock_sqs, mock_engine, mock_settings):
        """Test that semaphore is created with correct value."""
        mock_settings.DATABASE_URL = "postgresql+asyncpg://test"
        mock_settings.DEBUG = False
        mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"
        mock_settings.AWS_REGION = "us-east-1"
        mock_settings.SQS_ENDPOINT_URL = None

        from services.document_processing.app.pipeline.worker import PipelineWorker

        worker = PipelineWorker(max_concurrent=3)

        # Semaphore should allow 3 concurrent tasks
        assert worker.semaphore._value == 3


class TestPipelineWorkerLifecycle:
    """Tests for worker start/stop lifecycle."""

    @pytest.fixture
    def mock_worker(self):
        """Create a mocked worker."""
        with patch("services.document_processing.app.pipeline.worker.settings") as mock_settings:
            mock_settings.DATABASE_URL = "postgresql+asyncpg://test"
            mock_settings.DEBUG = False
            mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"
            mock_settings.AWS_REGION = "us-east-1"
            mock_settings.SQS_ENDPOINT_URL = None

            with patch("services.document_processing.app.pipeline.worker.create_async_engine") as mock_engine:
                mock_engine_instance = MagicMock()
                mock_engine_instance.dispose = AsyncMock()
                mock_engine.return_value = mock_engine_instance

                with patch("services.document_processing.app.pipeline.worker.SQSClient"):
                    from services.document_processing.app.pipeline.worker import PipelineWorker

                    worker = PipelineWorker(worker_id="test-worker")
                    worker.engine = mock_engine_instance
                    yield worker

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, mock_worker):
        """Test that stop sets running to False."""
        mock_worker.running = True

        await mock_worker.stop()

        assert mock_worker.running is False

    @pytest.mark.asyncio
    async def test_stop_disposes_engine(self, mock_worker):
        """Test that stop disposes the database engine."""
        mock_worker.running = True

        await mock_worker.stop()

        mock_worker.engine.dispose.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_waits_for_tasks(self, mock_worker):
        """Test that stop waits for in-flight tasks."""
        mock_worker.running = True

        # Add a mock task
        async def mock_task():
            await asyncio.sleep(0.01)

        task = asyncio.create_task(mock_task())
        mock_worker._tasks.add(task)

        await mock_worker.stop()

        # Task should be done
        assert task.done()


class TestPipelineWorkerPollLoop:
    """Tests for the polling loop."""

    @pytest.fixture
    def mock_worker(self):
        """Create a mocked worker."""
        with patch("services.document_processing.app.pipeline.worker.settings") as mock_settings:
            mock_settings.DATABASE_URL = "postgresql+asyncpg://test"
            mock_settings.DEBUG = False
            mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"
            mock_settings.AWS_REGION = "us-east-1"
            mock_settings.SQS_ENDPOINT_URL = None
            mock_settings.PIPELINE_VISIBILITY_TIMEOUT = 300

            with patch("services.document_processing.app.pipeline.worker.create_async_engine") as mock_engine:
                mock_engine_instance = MagicMock()
                mock_engine_instance.dispose = AsyncMock()
                mock_engine.return_value = mock_engine_instance

                with patch("services.document_processing.app.pipeline.worker.SQSClient") as mock_sqs:
                    mock_sqs_instance = MagicMock()
                    mock_sqs_instance.receive_messages = AsyncMock(return_value=[])
                    mock_sqs.return_value = mock_sqs_instance

                    from services.document_processing.app.pipeline.worker import PipelineWorker

                    worker = PipelineWorker(worker_id="test-worker")
                    worker.engine = mock_engine_instance
                    worker.sqs_client = mock_sqs_instance
                    yield worker

    @pytest.mark.asyncio
    async def test_poll_loop_exits_when_not_running(self, mock_worker):
        """Test that poll loop exits when running is False."""
        mock_worker.running = False

        # Should exit immediately
        await mock_worker._poll_loop()

        # No messages should be received since we're not running
        mock_worker.sqs_client.receive_messages.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_loop_receives_messages(self, mock_worker):
        """Test that poll loop receives messages from SQS."""
        call_count = 0

        async def mock_receive(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                mock_worker.running = False
            return []

        mock_worker.sqs_client.receive_messages = mock_receive
        mock_worker.running = True

        await mock_worker._poll_loop()

        assert call_count >= 1

    @pytest.mark.asyncio
    async def test_poll_loop_handles_errors(self, mock_worker):
        """Test that poll loop handles errors and backs off."""
        call_count = 0

        async def mock_receive(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("SQS error")
            mock_worker.running = False
            return []

        mock_worker.sqs_client.receive_messages = mock_receive
        mock_worker.running = True

        # Mock sleep to avoid actual delay
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await mock_worker._poll_loop()

        assert call_count >= 1


class TestPipelineWorkerProcessMessage:
    """Tests for message processing."""

    @pytest.fixture
    def mock_worker(self):
        """Create a mocked worker."""
        with patch("services.document_processing.app.pipeline.worker.settings") as mock_settings:
            mock_settings.DATABASE_URL = "postgresql+asyncpg://test"
            mock_settings.DEBUG = False
            mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"
            mock_settings.AWS_REGION = "us-east-1"
            mock_settings.SQS_ENDPOINT_URL = None

            with patch("services.document_processing.app.pipeline.worker.create_async_engine") as mock_engine:
                mock_engine_instance = MagicMock()
                mock_engine_instance.dispose = AsyncMock()
                mock_engine.return_value = mock_engine_instance

                with patch("services.document_processing.app.pipeline.worker.SQSClient") as mock_sqs:
                    mock_sqs_instance = MagicMock()
                    mock_sqs_instance.receive_messages = AsyncMock(return_value=[])
                    mock_sqs_instance.delete_message = AsyncMock()
                    mock_sqs_instance.change_visibility = AsyncMock()
                    mock_sqs_instance.send_message = AsyncMock()
                    mock_sqs.return_value = mock_sqs_instance

                    from services.document_processing.app.pipeline.worker import PipelineWorker

                    worker = PipelineWorker(worker_id="test-worker")
                    worker.engine = mock_engine_instance
                    worker.sqs_client = mock_sqs_instance
                    yield worker

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.worker.PipelineOrchestrator")
    @patch("services.document_processing.app.pipeline.worker.settings")
    async def test_process_message_success(self, mock_settings, mock_orchestrator, mock_worker):
        """Test successful message processing."""
        mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"

        doc_id = uuid4()
        user_id = uuid4()

        event_data = {
            "document_id": str(doc_id),
            "content_hash": "hash123",
            "doi": "10.1234/test",
            "title": "Test Document",
            "s3_key": f"documents/{doc_id}/original.pdf",
            "user_id": str(user_id),
            "correlation_id": "corr-123",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        message = {
            "MessageId": "msg-123",
            "ReceiptHandle": "receipt-123",
            "Body": json.dumps(event_data),
        }

        # Mock orchestrator
        mock_orch_instance = MagicMock()
        mock_orch_instance.process_document = AsyncMock(
            return_value=ProcessingResult(
                document_id=doc_id,
                success=True,
                chunk_count=10,
            )
        )
        mock_orchestrator.return_value = mock_orch_instance

        # Mock session
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_worker.async_session = MagicMock(return_value=mock_session)

        await mock_worker._process_message(message)

        # Should delete message on success
        mock_worker.sqs_client.delete_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.worker.PipelineOrchestrator")
    @patch("services.document_processing.app.pipeline.worker.settings")
    async def test_process_message_failure(self, mock_settings, mock_orchestrator, mock_worker):
        """Test message processing failure triggers retry."""
        mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"
        mock_settings.PIPELINE_MAX_RETRIES = 3
        mock_settings.PIPELINE_RETRY_DELAY = 30

        doc_id = uuid4()
        user_id = uuid4()

        event_data = {
            "document_id": str(doc_id),
            "content_hash": "hash123",
            "title": "Test Document",
            "s3_key": f"documents/{doc_id}/original.pdf",
            "user_id": str(user_id),
            "correlation_id": "corr-123",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        message = {
            "MessageId": "msg-123",
            "ReceiptHandle": "receipt-123",
            "Body": json.dumps(event_data),
            "Attributes": {"ApproximateReceiveCount": "1"},
        }

        # Mock orchestrator to return failure
        mock_orch_instance = MagicMock()
        mock_orch_instance.process_document = AsyncMock(
            return_value=ProcessingResult(
                document_id=doc_id,
                success=False,
                error="Processing failed",
            )
        )
        mock_orchestrator.return_value = mock_orch_instance

        # Mock session
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_worker.async_session = MagicMock(return_value=mock_session)

        await mock_worker._process_message(message)

        # Should change visibility for retry (not delete)
        mock_worker.sqs_client.change_visibility.assert_called_once()
        mock_worker.sqs_client.delete_message.assert_not_called()

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.worker.settings")
    async def test_process_message_json_decode_error(self, mock_settings, mock_worker):
        """Test handling of invalid JSON in message."""
        mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"
        mock_settings.SQS_DLQ_URL = "http://sqs/dlq"

        message = {
            "MessageId": "msg-123",
            "ReceiptHandle": "receipt-123",
            "Body": "invalid json {{{",
        }

        await mock_worker._process_message(message)

        # Should send to DLQ
        mock_worker.sqs_client.send_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.worker.PipelineOrchestrator")
    @patch("services.document_processing.app.pipeline.worker.settings")
    async def test_process_message_exception(self, mock_settings, mock_orchestrator, mock_worker):
        """Test handling of exceptions during processing."""
        mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"
        mock_settings.PIPELINE_MAX_RETRIES = 3
        mock_settings.PIPELINE_RETRY_DELAY = 30

        doc_id = uuid4()
        user_id = uuid4()

        event_data = {
            "document_id": str(doc_id),
            "content_hash": "hash123",
            "title": "Test Document",
            "s3_key": f"documents/{doc_id}/original.pdf",
            "user_id": str(user_id),
            "correlation_id": "corr-123",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        message = {
            "MessageId": "msg-123",
            "ReceiptHandle": "receipt-123",
            "Body": json.dumps(event_data),
            "Attributes": {"ApproximateReceiveCount": "1"},
        }

        # Mock orchestrator to raise exception
        mock_orch_instance = MagicMock()
        mock_orch_instance.process_document = AsyncMock(
            side_effect=Exception("Unexpected error")
        )
        mock_orchestrator.return_value = mock_orch_instance

        # Mock session
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_worker.async_session = MagicMock(return_value=mock_session)

        await mock_worker._process_message(message)

        # Should trigger failure handling
        mock_worker.sqs_client.change_visibility.assert_called_once()


class TestPipelineWorkerHandleFailure:
    """Tests for failure handling."""

    @pytest.fixture
    def mock_worker(self):
        """Create a mocked worker."""
        with patch("services.document_processing.app.pipeline.worker.settings") as mock_settings:
            mock_settings.DATABASE_URL = "postgresql+asyncpg://test"
            mock_settings.DEBUG = False
            mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"
            mock_settings.AWS_REGION = "us-east-1"
            mock_settings.SQS_ENDPOINT_URL = None
            mock_settings.PIPELINE_MAX_RETRIES = 3
            mock_settings.PIPELINE_RETRY_DELAY = 30

            with patch("services.document_processing.app.pipeline.worker.create_async_engine") as mock_engine:
                mock_engine_instance = MagicMock()
                mock_engine_instance.dispose = AsyncMock()
                mock_engine.return_value = mock_engine_instance

                with patch("services.document_processing.app.pipeline.worker.SQSClient") as mock_sqs:
                    mock_sqs_instance = MagicMock()
                    mock_sqs_instance.change_visibility = AsyncMock()
                    mock_sqs_instance.send_message = AsyncMock()
                    mock_sqs_instance.delete_message = AsyncMock()
                    mock_sqs.return_value = mock_sqs_instance

                    from services.document_processing.app.pipeline.worker import PipelineWorker

                    worker = PipelineWorker(worker_id="test-worker")
                    worker.engine = mock_engine_instance
                    worker.sqs_client = mock_sqs_instance
                    yield worker

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.worker.settings")
    async def test_handle_failure_retries_when_under_max(self, mock_settings, mock_worker):
        """Test that failure triggers retry when under max retries."""
        mock_settings.PIPELINE_MAX_RETRIES = 3
        mock_settings.PIPELINE_RETRY_DELAY = 30
        mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"

        message = {
            "MessageId": "msg-123",
            "ReceiptHandle": "receipt-123",
            "Attributes": {"ApproximateReceiveCount": "1"},
        }

        await mock_worker._handle_failure(message, "Test error")

        mock_worker.sqs_client.change_visibility.assert_called_once()

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.worker.settings")
    async def test_handle_failure_moves_to_dlq_at_max_retries(self, mock_settings, mock_worker):
        """Test that failure moves to DLQ at max retries."""
        mock_settings.PIPELINE_MAX_RETRIES = 3
        mock_settings.PIPELINE_RETRY_DELAY = 30
        mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"
        mock_settings.SQS_DLQ_URL = "http://sqs/dlq"

        message = {
            "MessageId": "msg-123",
            "ReceiptHandle": "receipt-123",
            "Body": '{"test": "data"}',
            "Attributes": {"ApproximateReceiveCount": "3"},
        }

        await mock_worker._handle_failure(message, "Max retries exceeded")

        # Should send to DLQ
        mock_worker.sqs_client.send_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.worker.settings")
    async def test_handle_failure_exponential_backoff(self, mock_settings, mock_worker):
        """Test exponential backoff in retry delay."""
        mock_settings.PIPELINE_MAX_RETRIES = 5
        mock_settings.PIPELINE_RETRY_DELAY = 30
        mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"

        # First retry - delay should be 30 * 2^0 = 30
        message1 = {
            "MessageId": "msg-123",
            "ReceiptHandle": "receipt-123",
            "Attributes": {"ApproximateReceiveCount": "1"},
        }
        await mock_worker._handle_failure(message1, "Error")

        call_args1 = mock_worker.sqs_client.change_visibility.call_args
        assert call_args1.kwargs["visibility_timeout"] == 30

        mock_worker.sqs_client.change_visibility.reset_mock()

        # Second retry - delay should be 30 * 2^1 = 60
        message2 = {
            "MessageId": "msg-124",
            "ReceiptHandle": "receipt-124",
            "Attributes": {"ApproximateReceiveCount": "2"},
        }
        await mock_worker._handle_failure(message2, "Error")

        call_args2 = mock_worker.sqs_client.change_visibility.call_args
        assert call_args2.kwargs["visibility_timeout"] == 60

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.worker.settings")
    async def test_handle_failure_max_delay_cap(self, mock_settings, mock_worker):
        """Test that retry delay is capped at 600 seconds."""
        mock_settings.PIPELINE_MAX_RETRIES = 10
        mock_settings.PIPELINE_RETRY_DELAY = 100  # Would be 100 * 2^9 = 51200 without cap
        mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"

        message = {
            "MessageId": "msg-123",
            "ReceiptHandle": "receipt-123",
            "Attributes": {"ApproximateReceiveCount": "9"},
        }

        await mock_worker._handle_failure(message, "Error")

        call_args = mock_worker.sqs_client.change_visibility.call_args
        # Should be capped at 600
        assert call_args.kwargs["visibility_timeout"] == 600


class TestPipelineWorkerMoveToDlq:
    """Tests for DLQ handling."""

    @pytest.fixture
    def mock_worker(self):
        """Create a mocked worker."""
        with patch("services.document_processing.app.pipeline.worker.settings") as mock_settings:
            mock_settings.DATABASE_URL = "postgresql+asyncpg://test"
            mock_settings.DEBUG = False
            mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"
            mock_settings.AWS_REGION = "us-east-1"
            mock_settings.SQS_ENDPOINT_URL = None
            mock_settings.SQS_DLQ_URL = "http://sqs/dlq"

            with patch("services.document_processing.app.pipeline.worker.create_async_engine") as mock_engine:
                mock_engine_instance = MagicMock()
                mock_engine_instance.dispose = AsyncMock()
                mock_engine.return_value = mock_engine_instance

                with patch("services.document_processing.app.pipeline.worker.SQSClient") as mock_sqs:
                    mock_sqs_instance = MagicMock()
                    mock_sqs_instance.send_message = AsyncMock()
                    mock_sqs_instance.delete_message = AsyncMock()
                    mock_sqs.return_value = mock_sqs_instance

                    from services.document_processing.app.pipeline.worker import PipelineWorker

                    worker = PipelineWorker(worker_id="test-worker")
                    worker.engine = mock_engine_instance
                    worker.sqs_client = mock_sqs_instance
                    yield worker

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.worker.settings")
    async def test_move_to_dlq_sends_message(self, mock_settings, mock_worker):
        """Test that message is sent to DLQ."""
        mock_settings.SQS_DLQ_URL = "http://sqs/dlq"
        mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"

        message = {
            "MessageId": "msg-123",
            "ReceiptHandle": "receipt-123",
            "Body": '{"document_id": "123"}',
        }

        await mock_worker._move_to_dlq(message, "Test error")

        # Should send to DLQ with metadata
        mock_worker.sqs_client.send_message.assert_called_once()
        call_args = mock_worker.sqs_client.send_message.call_args
        dlq_message = call_args.kwargs["message"]

        assert dlq_message["original_body"] == '{"document_id": "123"}'
        assert dlq_message["original_message_id"] == "msg-123"
        assert dlq_message["error"] == "Test error"
        assert dlq_message["worker_id"] == "test-worker"

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.worker.settings")
    async def test_move_to_dlq_deletes_original(self, mock_settings, mock_worker):
        """Test that original message is deleted after DLQ move."""
        mock_settings.SQS_DLQ_URL = "http://sqs/dlq"
        mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"

        message = {
            "MessageId": "msg-123",
            "ReceiptHandle": "receipt-123",
            "Body": '{"test": "data"}',
        }

        await mock_worker._move_to_dlq(message, "Error")

        mock_worker.sqs_client.delete_message.assert_called_once_with(
            queue_url="http://sqs/queue",
            receipt_handle="receipt-123",
        )

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.worker.settings")
    async def test_move_to_dlq_no_dlq_configured(self, mock_settings, mock_worker):
        """Test behavior when DLQ is not configured."""
        mock_settings.SQS_DLQ_URL = None

        message = {
            "MessageId": "msg-123",
            "ReceiptHandle": "receipt-123",
            "Body": '{"test": "data"}',
        }

        # Should not raise, just return
        await mock_worker._move_to_dlq(message, "Error")

        mock_worker.sqs_client.send_message.assert_not_called()
        mock_worker.sqs_client.delete_message.assert_not_called()

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.worker.settings")
    async def test_move_to_dlq_handles_errors(self, mock_settings, mock_worker):
        """Test that errors during DLQ move are handled."""
        mock_settings.SQS_DLQ_URL = "http://sqs/dlq"
        mock_settings.SQS_DOCUMENT_REGISTERED_URL = "http://sqs/queue"

        mock_worker.sqs_client.send_message = AsyncMock(
            side_effect=Exception("SQS error")
        )

        message = {
            "MessageId": "msg-123",
            "ReceiptHandle": "receipt-123",
            "Body": '{"test": "data"}',
        }

        # Should not raise
        await mock_worker._move_to_dlq(message, "Error")


class TestRunWorker:
    """Tests for run_worker function."""

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.worker.PipelineWorker")
    async def test_run_worker_creates_and_starts(self, mock_worker_class):
        """Test that run_worker creates and starts a worker."""
        mock_worker = MagicMock()
        mock_worker.start = AsyncMock()
        mock_worker_class.return_value = mock_worker

        from services.document_processing.app.pipeline.worker import run_worker

        await run_worker()

        mock_worker_class.assert_called_once_with(max_concurrent=5)
        mock_worker.start.assert_called_once()
