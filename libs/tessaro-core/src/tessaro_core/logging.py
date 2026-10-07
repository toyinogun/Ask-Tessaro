"""structlog setup: JSON lines to stdout, with request ID and service name on every line."""

import logging
import sys

import structlog

from tessaro_core.settings import LogLevel


def configure_logging(service_name: str, level: LogLevel = "INFO", json: bool = True) -> None:
    """Configure structlog once per process. A cluster log agent ships stdout to Loki."""
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str | None = None) -> structlog.typing.FilteringBoundLogger:
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger(name)
    return logger
