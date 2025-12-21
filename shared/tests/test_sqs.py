"""Tests for SQS client utilities."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from shared.utils.sqs import SQSClient


class SampleMessage(BaseModel):
    """Sample Pydantic model for testing."""

    event_type: str
    document_id: str
    status: str


class TestSQSClientInit:
    """Tests for SQSClient initialization."""

    def test_init_with_required_params(self):
        """Test initialization with required parameters."""
        client = SQSClient(queue_url="https://sqs.us-east-1.amazonaws.com/123/my-queue")
        assert client.queue_url == "https://sqs.us-east-1.amazonaws.com/123/my-queue"
        assert client.region == "us-east-1"
        assert client.endpoint_url is None

    def test_init_with_all_params(self):
        """Test initialization with all parameters."""
        client = SQSClient(
            queue_url="https://sqs.eu-west-1.amazonaws.com/123/my-queue",
            region="eu-west-1",
            endpoint_url="http://localhost:4566",
        )
        assert client.queue_url == "https://sqs.eu-west-1.amazonaws.com/123/my-queue"
        assert client.region == "eu-west-1"
        assert client.endpoint_url == "http://localhost:4566"

    def test_init_creates_session(self):
        """Test that initialization creates an aiobotocore session."""
        client = SQSClient(queue_url="https://sqs.us-east-1.amazonaws.com/123/queue")
        assert client._session is not None


class TestSQSClientSendMessage:
    """Tests for SQSClient.send_message."""

    @pytest.fixture
    def sqs_client(self):
        """Create an SQSClient for testing."""
        return SQSClient(
            queue_url="https://sqs.us-east-1.amazonaws.com/123/test-queue",
            endpoint_url="http://localhost:4566",
        )

    @pytest.mark.asyncio
    async def test_send_message_dict(self, sqs_client):
        """Test sending a dict message."""
        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.send_message = AsyncMock(
                return_value={"MessageId": "msg-123"}
            )
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            message = {"event": "document_registered", "doc_id": "doc-456"}
            result = await sqs_client.send_message(message)

            assert result == "msg-123"
            mock_client.send_message.assert_called_once()
            call_kwargs = mock_client.send_message.call_args[1]
            assert call_kwargs["QueueUrl"] == sqs_client.queue_url
            assert json.loads(call_kwargs["MessageBody"]) == message

    @pytest.mark.asyncio
    async def test_send_message_pydantic_model(self, sqs_client):
        """Test sending a Pydantic model message."""
        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.send_message = AsyncMock(
                return_value={"MessageId": "msg-789"}
            )
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            message = SampleMessage(
                event_type="document_processed",
                document_id="doc-123",
                status="completed",
            )
            result = await sqs_client.send_message(message)

            assert result == "msg-789"
            call_kwargs = mock_client.send_message.call_args[1]
            body = json.loads(call_kwargs["MessageBody"])
            assert body["event_type"] == "document_processed"
            assert body["document_id"] == "doc-123"
            assert body["status"] == "completed"

    @pytest.mark.asyncio
    async def test_send_message_with_fifo_params(self, sqs_client):
        """Test sending a message with FIFO queue parameters."""
        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.send_message = AsyncMock(
                return_value={"MessageId": "msg-fifo"}
            )
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            await sqs_client.send_message(
                message={"data": "test"},
                message_group_id="group-1",
                deduplication_id="dedup-123",
            )

            call_kwargs = mock_client.send_message.call_args[1]
            assert call_kwargs["MessageGroupId"] == "group-1"
            assert call_kwargs["MessageDeduplicationId"] == "dedup-123"

    @pytest.mark.asyncio
    async def test_send_message_custom_queue_url(self, sqs_client):
        """Test sending a message to a different queue URL."""
        custom_url = "https://sqs.us-east-1.amazonaws.com/123/other-queue"

        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.send_message = AsyncMock(
                return_value={"MessageId": "msg-custom"}
            )
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            await sqs_client.send_message(
                message={"data": "test"},
                queue_url=custom_url,
            )

            call_kwargs = mock_client.send_message.call_args[1]
            assert call_kwargs["QueueUrl"] == custom_url

    @pytest.mark.asyncio
    async def test_send_message_without_optional_params(self, sqs_client):
        """Test that optional params are not included when not provided."""
        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.send_message = AsyncMock(
                return_value={"MessageId": "msg-123"}
            )
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            await sqs_client.send_message(message={"data": "test"})

            call_kwargs = mock_client.send_message.call_args[1]
            assert "MessageGroupId" not in call_kwargs
            assert "MessageDeduplicationId" not in call_kwargs


class TestSQSClientSendMessageBatch:
    """Tests for SQSClient.send_message_batch."""

    @pytest.fixture
    def sqs_client(self):
        """Create an SQSClient for testing."""
        return SQSClient(
            queue_url="https://sqs.us-east-1.amazonaws.com/123/test-queue",
        )

    @pytest.mark.asyncio
    async def test_send_message_batch_dicts(self, sqs_client):
        """Test sending a batch of dict messages."""
        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.send_message_batch = AsyncMock(
                return_value={
                    "Successful": [
                        {"Id": "0", "MessageId": "msg-1"},
                        {"Id": "1", "MessageId": "msg-2"},
                    ],
                    "Failed": [],
                }
            )
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            messages = [
                {"event": "event1", "data": "data1"},
                {"event": "event2", "data": "data2"},
            ]
            result = await sqs_client.send_message_batch(messages)

            assert result == ["msg-1", "msg-2"]
            mock_client.send_message_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_batch_pydantic_models(self, sqs_client):
        """Test sending a batch of Pydantic model messages."""
        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.send_message_batch = AsyncMock(
                return_value={
                    "Successful": [
                        {"Id": "0", "MessageId": "msg-p1"},
                        {"Id": "1", "MessageId": "msg-p2"},
                    ],
                    "Failed": [],
                }
            )
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            messages = [
                SampleMessage(event_type="evt1", document_id="doc1", status="new"),
                SampleMessage(event_type="evt2", document_id="doc2", status="done"),
            ]
            result = await sqs_client.send_message_batch(messages)

            assert result == ["msg-p1", "msg-p2"]
            call_kwargs = mock_client.send_message_batch.call_args[1]
            entries = call_kwargs["Entries"]
            assert len(entries) == 2
            assert entries[0]["Id"] == "0"
            assert entries[1]["Id"] == "1"

    @pytest.mark.asyncio
    async def test_send_message_batch_partial_failure(self, sqs_client):
        """Test batch send with partial failures."""
        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.send_message_batch = AsyncMock(
                return_value={
                    "Successful": [{"Id": "0", "MessageId": "msg-ok"}],
                    "Failed": [{"Id": "1", "Code": "InternalError"}],
                }
            )
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            messages = [{"msg": "1"}, {"msg": "2"}]
            result = await sqs_client.send_message_batch(messages)

            # Should return only successful message IDs
            assert result == ["msg-ok"]

    @pytest.mark.asyncio
    async def test_send_message_batch_empty(self, sqs_client):
        """Test batch send with empty list."""
        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.send_message_batch = AsyncMock(
                return_value={"Successful": [], "Failed": []}
            )
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            result = await sqs_client.send_message_batch([])
            assert result == []

    @pytest.mark.asyncio
    async def test_send_message_batch_mixed_types(self, sqs_client):
        """Test batch send with mixed dict and Pydantic messages."""
        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.send_message_batch = AsyncMock(
                return_value={
                    "Successful": [
                        {"Id": "0", "MessageId": "msg-dict"},
                        {"Id": "1", "MessageId": "msg-pydantic"},
                    ],
                    "Failed": [],
                }
            )
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            messages = [
                {"plain": "dict"},
                SampleMessage(event_type="e", document_id="d", status="s"),
            ]
            result = await sqs_client.send_message_batch(messages)

            assert result == ["msg-dict", "msg-pydantic"]


class TestSQSClientReceiveMessages:
    """Tests for SQSClient.receive_messages."""

    @pytest.fixture
    def sqs_client(self):
        """Create an SQSClient for testing."""
        return SQSClient(
            queue_url="https://sqs.us-east-1.amazonaws.com/123/test-queue",
        )

    @pytest.mark.asyncio
    async def test_receive_messages_success(self, sqs_client):
        """Test receiving messages successfully."""
        mock_messages = [
            {
                "MessageId": "msg-1",
                "ReceiptHandle": "handle-1",
                "Body": '{"event": "test"}',
            },
            {
                "MessageId": "msg-2",
                "ReceiptHandle": "handle-2",
                "Body": '{"event": "test2"}',
            },
        ]

        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.receive_message = AsyncMock(
                return_value={"Messages": mock_messages}
            )
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            result = await sqs_client.receive_messages()

            assert len(result) == 2
            assert result[0]["MessageId"] == "msg-1"
            assert result[1]["MessageId"] == "msg-2"

    @pytest.mark.asyncio
    async def test_receive_messages_empty(self, sqs_client):
        """Test receiving when no messages available."""
        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.receive_message = AsyncMock(return_value={})
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            result = await sqs_client.receive_messages()
            assert result == []

    @pytest.mark.asyncio
    async def test_receive_messages_custom_params(self, sqs_client):
        """Test receiving with custom parameters."""
        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.receive_message = AsyncMock(return_value={"Messages": []})
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            await sqs_client.receive_messages(
                max_messages=5,
                visibility_timeout=60,
                wait_time=10,
            )

            call_kwargs = mock_client.receive_message.call_args[1]
            assert call_kwargs["MaxNumberOfMessages"] == 5
            assert call_kwargs["VisibilityTimeout"] == 60
            assert call_kwargs["WaitTimeSeconds"] == 10

    @pytest.mark.asyncio
    async def test_receive_messages_max_capped_at_10(self, sqs_client):
        """Test that max_messages is capped at 10 (SQS limit)."""
        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.receive_message = AsyncMock(return_value={"Messages": []})
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            await sqs_client.receive_messages(max_messages=20)

            call_kwargs = mock_client.receive_message.call_args[1]
            assert call_kwargs["MaxNumberOfMessages"] == 10

    @pytest.mark.asyncio
    async def test_receive_messages_custom_queue_url(self, sqs_client):
        """Test receiving from a different queue URL."""
        custom_url = "https://sqs.us-east-1.amazonaws.com/123/other-queue"

        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.receive_message = AsyncMock(return_value={"Messages": []})
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            await sqs_client.receive_messages(queue_url=custom_url)

            call_kwargs = mock_client.receive_message.call_args[1]
            assert call_kwargs["QueueUrl"] == custom_url

    @pytest.mark.asyncio
    async def test_receive_messages_includes_attributes(self, sqs_client):
        """Test that receive requests all attributes."""
        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.receive_message = AsyncMock(return_value={"Messages": []})
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            await sqs_client.receive_messages()

            call_kwargs = mock_client.receive_message.call_args[1]
            assert call_kwargs["AttributeNames"] == ["All"]
            assert call_kwargs["MessageAttributeNames"] == ["All"]


class TestSQSClientDeleteMessage:
    """Tests for SQSClient.delete_message."""

    @pytest.fixture
    def sqs_client(self):
        """Create an SQSClient for testing."""
        return SQSClient(
            queue_url="https://sqs.us-east-1.amazonaws.com/123/test-queue",
        )

    @pytest.mark.asyncio
    async def test_delete_message_success(self, sqs_client):
        """Test deleting a message successfully."""
        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.delete_message = AsyncMock(return_value={})
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            await sqs_client.delete_message(receipt_handle="handle-123")

            mock_client.delete_message.assert_called_once()
            call_kwargs = mock_client.delete_message.call_args[1]
            assert call_kwargs["QueueUrl"] == sqs_client.queue_url
            assert call_kwargs["ReceiptHandle"] == "handle-123"

    @pytest.mark.asyncio
    async def test_delete_message_custom_queue_url(self, sqs_client):
        """Test deleting a message from a different queue."""
        custom_url = "https://sqs.us-east-1.amazonaws.com/123/other-queue"

        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.delete_message = AsyncMock(return_value={})
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            await sqs_client.delete_message(
                receipt_handle="handle-456",
                queue_url=custom_url,
            )

            call_kwargs = mock_client.delete_message.call_args[1]
            assert call_kwargs["QueueUrl"] == custom_url


class TestSQSClientChangeVisibility:
    """Tests for SQSClient.change_visibility."""

    @pytest.fixture
    def sqs_client(self):
        """Create an SQSClient for testing."""
        return SQSClient(
            queue_url="https://sqs.us-east-1.amazonaws.com/123/test-queue",
        )

    @pytest.mark.asyncio
    async def test_change_visibility_success(self, sqs_client):
        """Test changing message visibility successfully."""
        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.change_message_visibility = AsyncMock(return_value={})
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            await sqs_client.change_visibility(
                receipt_handle="handle-789",
                visibility_timeout=120,
            )

            mock_client.change_message_visibility.assert_called_once()
            call_kwargs = mock_client.change_message_visibility.call_args[1]
            assert call_kwargs["QueueUrl"] == sqs_client.queue_url
            assert call_kwargs["ReceiptHandle"] == "handle-789"
            assert call_kwargs["VisibilityTimeout"] == 120

    @pytest.mark.asyncio
    async def test_change_visibility_custom_queue_url(self, sqs_client):
        """Test changing visibility on a different queue."""
        custom_url = "https://sqs.us-east-1.amazonaws.com/123/other-queue"

        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.change_message_visibility = AsyncMock(return_value={})
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            await sqs_client.change_visibility(
                receipt_handle="handle-abc",
                visibility_timeout=60,
                queue_url=custom_url,
            )

            call_kwargs = mock_client.change_message_visibility.call_args[1]
            assert call_kwargs["QueueUrl"] == custom_url

    @pytest.mark.asyncio
    async def test_change_visibility_zero_timeout(self, sqs_client):
        """Test setting visibility timeout to zero (make message immediately visible)."""
        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.change_message_visibility = AsyncMock(return_value={})
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            await sqs_client.change_visibility(
                receipt_handle="handle-xyz",
                visibility_timeout=0,
            )

            call_kwargs = mock_client.change_message_visibility.call_args[1]
            assert call_kwargs["VisibilityTimeout"] == 0


class TestSQSClientIntegration:
    """Integration-style tests for SQSClient workflows."""

    @pytest.fixture
    def sqs_client(self):
        """Create an SQSClient for testing."""
        return SQSClient(
            queue_url="https://sqs.us-east-1.amazonaws.com/123/test-queue",
            endpoint_url="http://localhost:4566",
        )

    @pytest.mark.asyncio
    async def test_send_receive_delete_workflow(self, sqs_client):
        """Test a complete send-receive-delete workflow."""
        sent_message = {"workflow": "test", "step": 1}
        received_message = {
            "MessageId": "workflow-msg",
            "ReceiptHandle": "workflow-handle",
            "Body": json.dumps(sent_message),
        }

        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.send_message = AsyncMock(
                return_value={"MessageId": "workflow-msg"}
            )
            mock_client.receive_message = AsyncMock(
                return_value={"Messages": [received_message]}
            )
            mock_client.delete_message = AsyncMock(return_value={})
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            # Send
            msg_id = await sqs_client.send_message(sent_message)
            assert msg_id == "workflow-msg"

            # Receive
            messages = await sqs_client.receive_messages()
            assert len(messages) == 1
            assert messages[0]["MessageId"] == "workflow-msg"

            # Delete
            await sqs_client.delete_message(messages[0]["ReceiptHandle"])
            mock_client.delete_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_receive_and_extend_visibility(self, sqs_client):
        """Test receiving a message and extending its visibility."""
        received_message = {
            "MessageId": "extend-msg",
            "ReceiptHandle": "extend-handle",
            "Body": '{"long_processing": true}',
        }

        with patch.object(sqs_client, "_session") as mock_session:
            mock_client = AsyncMock()
            mock_client.receive_message = AsyncMock(
                return_value={"Messages": [received_message]}
            )
            mock_client.change_message_visibility = AsyncMock(return_value={})
            mock_session.create_client.return_value.__aenter__.return_value = mock_client

            # Receive
            messages = await sqs_client.receive_messages()
            receipt_handle = messages[0]["ReceiptHandle"]

            # Extend visibility for long processing
            await sqs_client.change_visibility(
                receipt_handle=receipt_handle,
                visibility_timeout=300,  # 5 minutes
            )

            call_kwargs = mock_client.change_message_visibility.call_args[1]
            assert call_kwargs["VisibilityTimeout"] == 300
