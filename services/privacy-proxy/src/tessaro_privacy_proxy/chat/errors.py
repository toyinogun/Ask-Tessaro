"""OpenAI style errors, one mapping from every typed error to a status and code (AC-9)."""

from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse

from tessaro_privacy_proxy.masking.errors import (
    AnalyzerUnavailable,
    MappingStoreUnavailable,
    UnsupportedContent,
)
from tessaro_privacy_proxy.upstream.client import UpstreamError, UpstreamTimeout


@dataclass(frozen=True)
class ErrorSpec:
    """An error the edge returns as `{"error": {"message", "type", "code"}}`."""

    status: int
    code: str
    message: str
    type: str = "invalid_request_error"


class ApiError(Exception):
    """Raised by the edge's own checks; carries the error to return."""

    def __init__(self, spec: ErrorSpec) -> None:
        super().__init__(spec.code)
        self.spec = spec


_MAPPED: tuple[tuple[type[Exception], ErrorSpec], ...] = (
    (
        AnalyzerUnavailable,
        ErrorSpec(
            503, "analyzer_unavailable", "the privacy analyzer is unavailable", "server_error"
        ),
    ),
    (
        MappingStoreUnavailable,
        ErrorSpec(
            503, "mapping_store_unavailable", "the mapping store is unavailable", "server_error"
        ),
    ),
    (UnsupportedContent, ErrorSpec(400, "unsupported_content", "only text content is supported")),
    (
        UpstreamTimeout,
        ErrorSpec(504, "upstream_timeout", "the model did not answer in time", "server_error"),
    ),
    (UpstreamError, ErrorSpec(502, "upstream_error", "the model call failed", "server_error")),
)

INTERNAL = ErrorSpec(500, "internal_error", "the proxy failed", "server_error")
INVALID_REQUEST = ErrorSpec(400, "invalid_request", "the request body is not a valid chat request")


def to_error_spec(exc: Exception) -> ErrorSpec:
    """The error to return for a typed error; anything unexpected is a 500 with no detail."""
    if isinstance(exc, ApiError):
        return exc.spec
    for kind, error in _MAPPED:
        if isinstance(exc, kind):
            return error
    return INTERNAL


def error_response(error: ErrorSpec) -> JSONResponse:
    """The JSON response for `error`. Never echoes any part of the request."""
    return JSONResponse(
        status_code=error.status,
        content={"error": {"message": error.message, "type": error.type, "code": error.code}},
    )


async def validation_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
    """Replaces FastAPI's 422 handler, which would echo the invalid input back."""
    return error_response(INVALID_REQUEST)
