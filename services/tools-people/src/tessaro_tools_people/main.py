"""tools-people entry point: `uvicorn tessaro_tools_people.main:app --port 8080`."""

from fastapi import FastAPI

from tessaro_core import create_app
from tessaro_tools_people.settings import Settings


def build_app(settings: Settings | None = None) -> FastAPI:
    return create_app(settings or Settings())


app = build_app()
