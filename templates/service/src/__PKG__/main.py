"""__SERVICE__ entry point: `uvicorn __PKG__.main:app --port 8080`."""

from fastapi import FastAPI

from tessaro_core import create_app
from __PKG__.settings import Settings


def build_app(settings: Settings | None = None) -> FastAPI:
    return create_app(settings or Settings())


app = build_app()
