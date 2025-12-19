"""FastAPI dependency injection."""

from typing import Annotated, AsyncGenerator

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from shared.utils.db import get_db_session
from shared.utils.logging import set_correlation_id
from shared.utils.sqs import SQSClient
from shared.utils.s3 import S3Client
from services.document_registry.app.config import Settings, get_settings


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session dependency."""
    async with get_db_session() as session:
        yield session


async def get_correlation_id_dep(
    x_correlation_id: Annotated[str | None, Header()] = None,
) -> str:
    """Extract or generate correlation ID from request headers."""
    return set_correlation_id(x_correlation_id)


def get_sqs_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SQSClient:
    """Get SQS client dependency."""
    return SQSClient(
        queue_url=settings.sqs_queue_url,
        region=settings.sqs_region,
        endpoint_url=settings.sqs_endpoint_url,
    )


def get_s3_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> S3Client:
    """Get S3 client dependency."""
    return S3Client(
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url,
    )


# Type aliases for cleaner function signatures
DBSession = Annotated[AsyncSession, Depends(get_db)]
CorrelationID = Annotated[str, Depends(get_correlation_id_dep)]
SQS = Annotated[SQSClient, Depends(get_sqs_client)]
S3 = Annotated[S3Client, Depends(get_s3_client)]
AppSettings = Annotated[Settings, Depends(get_settings)]
