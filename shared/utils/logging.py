"""Structured logging with correlation ID support."""

import contextvars
import logging
import sys
import uuid
from typing import Any

import structlog

# Context variable for correlation ID
_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)


def get_correlation_id() -> str:
    """Get the current correlation ID from context."""
    return _correlation_id.get()


def set_correlation_id(correlation_id: str | None = None) -> str:
    """Set correlation ID in context. Generates one if not provided."""
    cid = correlation_id or str(uuid.uuid4())
    _correlation_id.set(cid)
    return cid


def add_correlation_id(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Processor to add correlation ID to log events."""
    correlation_id = get_correlation_id()
    if correlation_id:
        event_dict["correlation_id"] = correlation_id
    return event_dict


def configure_logging(
    service_name: str,
    log_level: str = "INFO",
    json_format: bool = True,
) -> None:
    """Configure structured logging for a service.

    Args:
        service_name: Name of the service for log context
        log_level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_format: Whether to output JSON logs (True for production)
    """
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        add_correlation_id,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if json_format:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )

    # Add service name to all logs
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a configured logger instance."""
    return structlog.get_logger(name)


# Alias for backwards compatibility
setup_logging = configure_logging
