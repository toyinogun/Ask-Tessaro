"""Correlation: read or create `X-Request-ID` at every entry point and bind it to logs."""

import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

import structlog
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id() -> str | None:
    """The request ID of the call being handled, if any."""
    return _request_id.get()


def new_request_id() -> str:
    return uuid.uuid4().hex


async def request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Reuse the caller's request ID or mint one, bind it for logs, echo it back."""
    request_id = request.headers.get(REQUEST_ID_HEADER) or new_request_id()
    token = _request_id.set(request_id)
    structlog.contextvars.bind_contextvars(request_id=request_id)
    try:
        response = await call_next(request)
    finally:
        structlog.contextvars.unbind_contextvars("request_id")
        _request_id.reset(token)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response
