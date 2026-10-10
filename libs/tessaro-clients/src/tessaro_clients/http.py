"""One JSON call over httpx, mapping transport and status failures to the client errors."""

from collections.abc import Mapping
from typing import Any

import httpx

from tessaro_clients.errors import ApiError, Unreachable

# Any: request parameters and response bodies are each system's own open ended JSON.
Json = Any

MAX_DETAIL = 300


async def call_json(
    http: httpx.AsyncClient,
    system: str,
    method: str,
    path: str,
    *,
    json: Json = None,
    data: Mapping[str, str] | None = None,
    params: Mapping[str, str | int] | None = None,
    headers: Mapping[str, str] | None = None,
    auth: httpx.Auth | None = None,
) -> Json:
    """The decoded JSON body of a 2xx answer, or None for an empty one (204).

    Raises Unreachable when no answer arrives, and ApiError for any other status or a body that is
    not JSON. The error carries the method and path, never the credentials.
    """
    call = f"{method} {path}"
    try:
        response = await http.request(
            method,
            path,
            json=json,
            data=data,
            params=params,
            headers=headers,
            auth=auth if auth is not None else httpx.USE_CLIENT_DEFAULT,
        )
    except httpx.TimeoutException as exc:
        raise Unreachable(system, call, "timed out") from exc
    except httpx.HTTPError as exc:
        raise Unreachable(system, call, type(exc).__name__) from exc
    if not response.is_success:
        raise ApiError(system, call, response.status_code, response.text[:MAX_DETAIL])
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise ApiError(system, call, response.status_code, "the body is not JSON") from exc
