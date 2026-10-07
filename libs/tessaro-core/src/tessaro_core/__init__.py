"""Shared plumbing for every Ask Tessaro service."""

from tessaro_core.app import SERVICE_PORT, create_app
from tessaro_core.health import ReadinessCheck, health_router
from tessaro_core.http import create_http_client
from tessaro_core.logging import configure_logging, get_logger
from tessaro_core.request_id import REQUEST_ID_HEADER, current_request_id
from tessaro_core.settings import ServiceSettings

__all__ = [
    "REQUEST_ID_HEADER",
    "SERVICE_PORT",
    "ReadinessCheck",
    "ServiceSettings",
    "configure_logging",
    "create_app",
    "create_http_client",
    "current_request_id",
    "get_logger",
    "health_router",
]
