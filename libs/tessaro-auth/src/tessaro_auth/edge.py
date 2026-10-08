"""The HTTP edge: turn an `Authorization: Bearer` header into a Principal, or a 401.

The only module in this package that imports Starlette or structlog.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Final

import structlog
from starlette.exceptions import HTTPException

from tessaro_auth.claims import Principal
from tessaro_auth.keys import KeySet
from tessaro_auth.verify import TokenInvalid, verify

REQUEST_ID_HEADER: Final = "x-request-id"
UNTRUSTED_LOG_CHARS: Final = 64
"""Untrusted header values are cut to this length before they are logged."""

_log = structlog.get_logger("tessaro_auth")


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Case insensitive header lookup that works for plain dicts and Starlette headers."""
    value = headers.get(name)
    if value is not None:
        return value
    for key, candidate in headers.items():
        if key.lower() == name:
            return candidate
    return None


def _unauthorized(reason: str, headers: Mapping[str, str]) -> HTTPException:
    """Log why, never the token, and build the one fixed 401 every failure returns."""
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    if request_id is None:
        request_id = (_header(headers, REQUEST_ID_HEADER) or "")[:UNTRUSTED_LOG_CHARS] or None
    _log.warning("token_rejected", reason=reason, request_id=request_id)
    return HTTPException(
        status_code=401,
        detail="invalid token",
        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
    )


def principal_from_headers(
    headers: Mapping[str, str], keyset: KeySet, now: datetime | None = None
) -> Principal:
    """Verify the caller's bearer token; raise a 401 HTTPException on any failure.

    On success the token's request ID is bound into the structlog context, so every
    later log line in the call carries it.
    """
    authorization = _header(headers, "authorization")
    if authorization is None:
        raise _unauthorized("missing_token", headers)
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("not_bearer", headers)
    try:
        principal = verify(token.strip(), keyset, now or datetime.now(UTC))
    except TokenInvalid as exc:
        raise _unauthorized(exc.reason.value, headers) from None
    structlog.contextvars.bind_contextvars(request_id=principal.request_id)
    header_request_id = _header(headers, REQUEST_ID_HEADER)
    if header_request_id is not None and header_request_id != principal.request_id:
        _log.warning(
            "request_id_mismatch",
            request_id=principal.request_id,
            header_request_id=header_request_id[:UNTRUSTED_LOG_CHARS],
        )
    return principal
