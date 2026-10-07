"""App factory: every service gets logging, request IDs and health routes the same way."""

from collections.abc import Sequence

from fastapi import FastAPI

from tessaro_core.health import ReadinessCheck, health_router
from tessaro_core.logging import configure_logging
from tessaro_core.request_id import request_id_middleware
from tessaro_core.settings import ServiceSettings

SERVICE_PORT = 8080


def create_app(
    settings: ServiceSettings, readiness_checks: Sequence[ReadinessCheck] = ()
) -> FastAPI:
    configure_logging(settings.service_name, settings.log_level, settings.log_json)
    app = FastAPI(title=settings.service_name, docs_url=None, redoc_url=None)
    app.middleware("http")(request_id_middleware)
    app.include_router(health_router(readiness_checks))
    return app
