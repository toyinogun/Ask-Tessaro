"""tool-gateway entry point: `uvicorn tessaro_tool_gateway.main:app --port 8080`."""

from fastapi import FastAPI

from tessaro_core import create_app
from tessaro_tool_gateway.settings import Settings


def build_app(settings: Settings | None = None) -> FastAPI:
    return create_app(settings or Settings())


app = build_app()
