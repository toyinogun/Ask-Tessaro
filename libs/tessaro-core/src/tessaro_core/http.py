"""httpx factory: async clients that forward the current `X-Request-ID` on every call."""

import httpx

from tessaro_core.request_id import REQUEST_ID_HEADER, current_request_id

DEFAULT_TIMEOUT_SECONDS = 10.0


async def _forward_request_id(request: httpx.Request) -> None:
    request_id = current_request_id()
    if request_id and REQUEST_ID_HEADER not in request.headers:
        request.headers[REQUEST_ID_HEADER] = request_id


def create_http_client(
    base_url: str = "",
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """Build an AsyncClient for outbound calls. Pass `transport` in tests (e.g. MockTransport)."""
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=timeout,
        transport=transport,
        event_hooks={"request": [_forward_request_id]},
    )
