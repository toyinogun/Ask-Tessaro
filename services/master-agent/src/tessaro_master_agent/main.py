"""master-agent entry point: `uvicorn tessaro_master_agent.main:app --port 8080`."""

from fastapi import FastAPI

from tessaro_core import create_app
from tessaro_master_agent.settings import Settings


def build_app(settings: Settings | None = None) -> FastAPI:
    return create_app(settings or Settings())


app = build_app()
