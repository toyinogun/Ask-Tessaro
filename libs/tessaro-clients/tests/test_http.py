"""call_json(): one JSON call, with transport and status failures mapped to client errors."""

import httpx
import pytest

from tessaro_clients.errors import ApiError, Unreachable
from tessaro_clients.http import call_json


def client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="https://sys.example/api/", transport=handler)


async def test_a_json_answer_is_decoded() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}))
    async with client(transport) as http:
        assert await call_json(http, "sys", "GET", "x") == {"ok": True}


async def test_an_empty_answer_is_none() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(204))
    async with client(transport) as http:
        assert await call_json(http, "sys", "POST", "x") is None


async def test_an_error_status_names_the_call_and_status() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(403, text="denied"))
    async with client(transport) as http:
        with pytest.raises(ApiError, match="sys POST x failed with status 403: denied") as caught:
            await call_json(http, "sys", "POST", "x")
    assert caught.value.status == 403


async def test_a_body_that_is_not_json_is_an_api_error() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>"))
    async with client(transport) as http:
        with pytest.raises(ApiError, match="not JSON"):
            await call_json(http, "sys", "GET", "x")


async def test_a_timeout_is_unreachable() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    async with client(httpx.MockTransport(slow)) as http:
        with pytest.raises(Unreachable, match="timed out"):
            await call_json(http, "sys", "GET", "x")


async def test_a_refused_connection_is_unreachable() -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with client(httpx.MockTransport(refused)) as http:
        with pytest.raises(Unreachable, match="ConnectError"):
            await call_json(http, "sys", "GET", "x")
