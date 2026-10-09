"""Fail closed, request errors, upstream errors and the log line (spec 0006 AC-8 to AC-12)."""

import json
from typing import Any

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from tessaro_privacy_proxy.analyzer.fake import FakeAnalyzer
from tessaro_privacy_proxy.chat.errors import validation_error_handler
from tessaro_privacy_proxy.mapping.redis_store import conversation_keys
from tessaro_privacy_proxy.masking.mask import Masker

from .conftest import CLIENT_KEY, CONVERSATION, TOOLS_MODEL, Proxy, ProxyFactory, answer, user


def _error(response: httpx.Response) -> tuple[int, str]:
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"message", "type", "code"}
    return response.status_code, body["error"]["code"]


async def test_analyzer_down_refuses_without_calling_the_model(make_proxy: ProxyFactory) -> None:
    """covers: AC-8"""
    proxy = make_proxy(analyzer=FakeAnalyzer(down=True))
    response = await proxy.chat([user("hello Daan")])
    assert _error(response) == (503, "analyzer_unavailable")
    assert proxy.upstream.requests == []


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(500),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json=[{"start": "x"}]),
    ],
)
async def test_the_http_analyzer_fails_closed_on_bad_replies(
    make_proxy: ProxyFactory, reply: httpx.Response
) -> None:
    """covers: AC-8 (real HttpAnalyzer adapter: non 200 or unparsable reply)"""
    proxy = make_proxy(analyzer_transport=httpx.MockTransport(lambda _r: reply))
    assert _error(await proxy.chat([user("hi")])) == (503, "analyzer_unavailable")
    assert proxy.upstream.requests == []


async def test_the_http_analyzer_fails_closed_when_unreachable(make_proxy: ProxyFactory) -> None:
    """covers: AC-8 (timeout or network error)"""

    def unreachable(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no analyzer")

    proxy = make_proxy(analyzer_transport=httpx.MockTransport(unreachable))
    assert _error(await proxy.chat([user("hi")])) == (503, "analyzer_unavailable")
    assert proxy.upstream.requests == []


async def test_the_http_analyzer_sends_the_spec_request(make_proxy: ProxyFactory) -> None:
    """covers: AC-3 (four types, English, the threshold) and analyzer offsets in use"""
    seen: list[dict[str, Any]] = []

    def analyze(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append(payload)
        start = payload["text"].find("Zebedeus")
        hits = [{"entity_type": "PERSON", "start": start, "end": start + 8, "score": 0.9}]
        return httpx.Response(200, json=hits if start >= 0 else [])

    proxy = make_proxy(analyzer_transport=httpx.MockTransport(analyze))
    await proxy.chat([user("ask Zebedeus now")])
    assert seen == [
        {
            "text": "ask Zebedeus now",
            "language": "en",
            "entities": ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE"],
            "score_threshold": 0.4,
        }
    ]
    assert proxy.upstream.bodies[0]["messages"][0]["content"] == "ask <PERSON_1> now"


async def test_redis_down_refuses_without_calling_the_model(
    make_proxy: ProxyFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """covers: AC-8"""
    proxy = make_proxy()

    async def dead(*_args: object) -> object:
        raise RedisConnectionError("down")

    monkeypatch.setattr(proxy.redis, "eval", dead)
    assert _error(await proxy.chat([user("hi")])) == (503, "mapping_store_unavailable")
    assert proxy.upstream.requests == []


async def test_partly_present_keys_refuse_without_calling_the_model(proxy: Proxy) -> None:
    """covers: AC-6, AC-8"""
    await proxy.chat([user("Daan de Wit")])
    await proxy.redis.delete(conversation_keys(CONVERSATION)[2])
    assert _error(await proxy.chat([user("again")])) == (503, "mapping_store_unavailable")
    assert len(proxy.upstream.requests) == 1


async def test_an_unexpected_masking_error_is_a_500_without_a_model_call(
    proxy: Proxy, monkeypatch: pytest.MonkeyPatch
) -> None:
    """covers: AC-8 (any other error while masking)"""

    async def broken(*_a: object, **_k: object) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(Masker, "mask_request", broken)
    assert _error(await proxy.chat([user("hi")])) == (500, "internal_error")
    assert proxy.upstream.requests == []


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"key": None}, (401, "invalid_api_key")),
        ({"key": "wrong" * 10}, (401, "invalid_api_key")),
        ({"conversation": None}, (400, "missing_conversation_id")),
        ({"conversation": "has space"}, (400, "missing_conversation_id")),
        ({"conversation": "x" * 129}, (400, "missing_conversation_id")),
        ({"stream": True}, (400, "streaming_not_supported")),
        ({"model": "gpt-4o"}, (400, "model_not_allowed")),
        ({"functions": [{"name": "f"}]}, (400, "unsupported_content")),
        ({"function_call": "auto"}, (400, "unsupported_content")),
    ],
)
async def test_request_errors(
    proxy: Proxy, kwargs: dict[str, Any], expected: tuple[int, str]
) -> None:
    """covers: AC-9 (no analyzer, Redis or upstream call)"""
    response = await proxy.chat([user("Daan de Wit")], **kwargs)
    assert _error(response) == expected
    assert proxy.upstream.requests == []
    assert await proxy.redis.keys("*") == []


async def test_image_parts_bad_bodies_and_big_bodies(proxy: Proxy) -> None:
    """covers: AC-9"""
    image = {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}
    assert _error(await proxy.chat([image])) == (400, "unsupported_content")
    headers = {"Authorization": f"Bearer {CLIENT_KEY}", "X-Conversation-ID": CONVERSATION}
    url = "/v1/chat/completions"
    for bad in (b"not json", b'{"model": "x"}', b'{"model": "x", "messages": []}'):
        response = await proxy.client.post(url, content=bad, headers=headers)
        assert _error(response) == (400, "invalid_request")
        assert "messages" not in response.text
    huge = json.dumps({"model": TOOLS_MODEL, "messages": [user("x" * (1024 * 1024))]})
    assert _error(await proxy.client.post(url, content=huge, headers=headers)) == (
        413,
        "request_too_large",
    )

    async def stream() -> Any:
        for _ in range(3):
            yield b"x" * (512 * 1024)

    chunked = await proxy.client.post(url, content=stream(), headers=headers)
    assert _error(chunked) == (413, "request_too_large")
    assert proxy.upstream.requests == []


async def test_the_tools_model_is_allowed(proxy: Proxy) -> None:
    """covers: AC-9"""
    assert (await proxy.chat([user("hi")], model=TOOLS_MODEL)).status_code == 200


async def test_the_validation_handler_echoes_nothing() -> None:
    """covers: AC-9 (FastAPI's 422 handler is replaced)"""
    response = await validation_error_handler(None, ValueError("Daan de Wit"))  # type: ignore[arg-type]
    assert response.status_code == 400
    assert b"Daan" not in response.body


@pytest.mark.parametrize(
    ("status", "content", "expected"),
    [
        (500, b"{}", (502, "upstream_error")),
        (429, b"{}", (502, "upstream_error")),
        (200, b"not json", (502, "upstream_error")),
        (200, b"[1, 2]", (502, "upstream_error")),
    ],
)
async def test_upstream_failures(
    proxy: Proxy, status: int, content: bytes, expected: tuple[int, str]
) -> None:
    """covers: AC-10"""
    proxy.upstream.status = status
    proxy.upstream.raw = content
    assert _error(await proxy.chat([user("hi")])) == expected
    assert len(proxy.upstream.requests) == 1  # never retried


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ReadTimeout("slow"), (504, "upstream_timeout")),
        (httpx.ConnectError("refused"), (502, "upstream_error")),
    ],
)
async def test_upstream_timeouts_and_network_errors(
    proxy: Proxy, error: Exception, expected: tuple[int, str]
) -> None:
    """covers: AC-10"""
    proxy.upstream.raise_error = error
    assert _error(await proxy.chat([user("hi")])) == expected
    assert len(proxy.upstream.requests) == 1


async def test_one_model_call_log_line_with_counts_and_no_text(
    proxy: Proxy, capsys: pytest.CaptureFixture[str]
) -> None:
    """covers: AC-12"""
    proxy.upstream.reply = lambda _body: answer("<PERSON_1> is in")
    await proxy.chat([user("Is Daan de Wit (TES-01005) in?")])
    out = capsys.readouterr().out
    lines = [json.loads(line) for line in out.splitlines()]
    calls = [e for e in lines if e["event"] == "model_call"]
    assert len(calls) == 1
    call = calls[0]
    assert call["conversation_id"] == CONVERSATION
    assert call["entities"] == {"EMPLOYEE_ID": 1, "PERSON": 1}
    assert call["upstream_status"] == 200
    assert call["request_id"]
    assert isinstance(call["duration_ms"], int)
    assert "Daan" not in out
    assert "TES-01005" not in out


async def test_a_failed_request_logs_one_failure_line_with_no_text(
    make_proxy: ProxyFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    """covers: AC-12 (class name only, never the exception message)"""
    proxy = make_proxy(analyzer=FakeAnalyzer(down=True))
    await proxy.chat([user("Is Daan de Wit in?")])
    out = capsys.readouterr().out
    lines = [json.loads(line) for line in out.splitlines()]
    failures = [e for e in lines if e["event"] == "model_call_failed"]
    assert len(failures) == 1
    failure = failures[0]
    assert failure["code"] == "analyzer_unavailable"
    assert failure["error"] == "AnalyzerUnavailable"
    assert failure["upstream_status"] is None
    assert isinstance(failure["duration_ms"], int)
    assert not any(e["event"] == "model_call" for e in lines)
    assert "Daan" not in out
