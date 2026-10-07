import json
from collections.abc import Awaitable, Callable

import httpx
import pytest
import structlog
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from tessaro_core import (
    REQUEST_ID_HEADER,
    ReadinessCheck,
    ServiceSettings,
    configure_logging,
    create_app,
    create_http_client,
    current_request_id,
    get_logger,
)
from tessaro_core.request_id import request_id_middleware


async def _up() -> bool:
    return True


async def _down() -> bool:
    return False


async def _broken() -> bool:
    raise ConnectionError("redis unreachable")


def _settings() -> ServiceSettings:
    return ServiceSettings(service_name="test-service")


def test_settings_require_service_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERVICE_NAME", raising=False)
    with pytest.raises(ValidationError):
        ServiceSettings()


def test_settings_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "from-env")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = ServiceSettings()
    assert settings.service_name == "from-env"
    assert settings.log_level == "DEBUG"


def test_healthz_is_ok() -> None:
    client = TestClient(create_app(_settings()))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_ready_when_all_checks_pass() -> None:
    app = create_app(_settings(), [ReadinessCheck("redis", _up)])
    response = TestClient(app).get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"redis": True}}


@pytest.mark.parametrize("probe", [_down, _broken])
def test_readyz_not_ready_when_a_check_fails(probe: Callable[[], Awaitable[bool]]) -> None:
    app = create_app(_settings(), [ReadinessCheck("up", _up), ReadinessCheck("dep", probe)])
    response = TestClient(app).get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"up": True, "dep": False}}


def test_request_id_is_echoed_when_given() -> None:
    client = TestClient(create_app(_settings()))
    response = client.get("/healthz", headers={REQUEST_ID_HEADER: "abc123"})
    assert response.headers[REQUEST_ID_HEADER] == "abc123"


def test_request_id_is_minted_when_missing() -> None:
    client = TestClient(create_app(_settings()))
    response = client.get("/healthz")
    assert len(response.headers[REQUEST_ID_HEADER]) == 32


def test_logs_are_json_with_service_and_request_id(capsys: pytest.CaptureFixture[str]) -> None:
    app = create_app(_settings())

    @app.get("/log")
    async def log_something() -> dict[str, str | None]:
        get_logger().info("hello")
        return {"request_id": current_request_id()}

    TestClient(app).get("/log", headers={REQUEST_ID_HEADER: "req-1"})
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["event"] == "hello"
    assert line["service"] == "test-service"
    assert line["request_id"] == "req-1"


async def test_http_client_forwards_request_id() -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get(REQUEST_ID_HEADER))
        return httpx.Response(200)

    app = create_app(_settings())

    @app.get("/outbound")
    async def outbound() -> dict[str, str]:
        async with create_http_client(
            "http://upstream", transport=httpx.MockTransport(handler)
        ) as client:
            await client.get("/x")
        return {"ok": "yes"}

    TestClient(app).get("/outbound", headers={REQUEST_ID_HEADER: "fwd-1"})
    async with create_http_client("http://upstream", transport=httpx.MockTransport(handler)) as c:
        await c.get("/no-context")
    assert seen == ["fwd-1", None]


def _log_lines(output: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in output.strip().splitlines() if line.startswith("{")]


def _http_request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw})


# Settings


def test_settings_are_frozen() -> None:
    settings = _settings()
    with pytest.raises(ValidationError):
        settings.service_name = "changed"  # type: ignore[misc]


def test_settings_reject_an_unknown_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "svc")
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
    with pytest.raises(ValidationError):
        ServiceSettings()


def test_settings_read_log_json_false_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "svc")
    monkeypatch.setenv("LOG_JSON", "false")
    assert ServiceSettings().log_json is False


# App factory


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_interactive_docs_are_disabled(path: str) -> None:
    response = TestClient(create_app(_settings())).get(path)
    assert response.status_code == 404


# Health


def test_readyz_is_ready_with_no_checks() -> None:
    response = TestClient(create_app(_settings())).get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {}}


def test_readyz_runs_probes_on_every_request() -> None:
    state = {"up": True}

    async def flaky() -> bool:
        return state["up"]

    client = TestClient(create_app(_settings(), [ReadinessCheck("dep", flaky)]))
    assert client.get("/readyz").status_code == 200
    state["up"] = False
    assert client.get("/readyz").status_code == 503


def test_readyz_ignores_checks_added_after_the_app_is_built() -> None:
    checks = [ReadinessCheck("up", _up)]
    client = TestClient(create_app(_settings(), checks))
    checks.append(ReadinessCheck("late", _down))
    assert client.get("/readyz").json() == {"status": "ready", "checks": {"up": True}}


def test_readyz_logs_a_warning_naming_the_check_that_raised(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = TestClient(create_app(_settings(), [ReadinessCheck("redis", _broken)]))
    client.get("/readyz")
    failures = [
        line
        for line in _log_lines(capsys.readouterr().out)
        if line["event"] == "readiness_check_failed"
    ]
    assert len(failures) == 1
    assert failures[0]["check"] == "redis"
    assert failures[0]["level"] == "warning"
    assert "redis unreachable" in str(failures[0]["exception"])


# Request ID


def test_request_id_is_minted_when_header_is_empty() -> None:
    response = TestClient(create_app(_settings())).get("/healthz", headers={REQUEST_ID_HEADER: ""})
    assert len(response.headers[REQUEST_ID_HEADER]) == 32


def test_request_id_is_echoed_on_not_found_responses() -> None:
    client = TestClient(create_app(_settings()))
    response = client.get("/no-such-route", headers={REQUEST_ID_HEADER: "nf-1"})
    assert response.status_code == 404
    assert response.headers[REQUEST_ID_HEADER] == "nf-1"


def test_minted_request_ids_are_unique_per_request() -> None:
    client = TestClient(create_app(_settings()))
    ids = {client.get("/healthz").headers[REQUEST_ID_HEADER] for _ in range(5)}
    assert len(ids) == 5


async def test_request_id_is_cleared_after_the_request() -> None:
    seen: list[str | None] = []

    async def call_next(request: Request) -> Response:
        seen.append(current_request_id())
        return PlainTextResponse("ok")

    await request_id_middleware(_http_request({REQUEST_ID_HEADER: "scoped-1"}), call_next)
    assert seen == ["scoped-1"]
    assert current_request_id() is None
    assert "request_id" not in structlog.contextvars.get_contextvars()


async def test_request_id_is_cleared_when_the_handler_raises() -> None:
    async def call_next(request: Request) -> Response:
        raise RuntimeError("handler blew up")

    with pytest.raises(RuntimeError):
        await request_id_middleware(_http_request({REQUEST_ID_HEADER: "boom-1"}), call_next)
    assert current_request_id() is None
    assert "request_id" not in structlog.contextvars.get_contextvars()


# Outbound HTTP


def test_http_client_keeps_an_explicit_request_id() -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get(REQUEST_ID_HEADER))
        return httpx.Response(200)

    app = create_app(_settings())

    @app.get("/outbound")
    async def outbound() -> dict[str, str]:
        async with create_http_client(
            "http://upstream", transport=httpx.MockTransport(handler)
        ) as client:
            await client.get("/x", headers={REQUEST_ID_HEADER: "explicit"})
        return {"ok": "yes"}

    TestClient(app).get("/outbound", headers={REQUEST_ID_HEADER: "inbound"})
    assert seen == ["explicit"]


async def test_http_client_uses_the_default_timeout() -> None:
    async with create_http_client() as client:
        assert client.timeout == httpx.Timeout(10.0)


# Logging


def test_logs_below_the_configured_level_are_dropped(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("svc", "WARNING")
    logger = get_logger()
    logger.info("quiet")
    logger.warning("loud")
    events = [line["event"] for line in _log_lines(capsys.readouterr().out)]
    assert events == ["loud"]


def test_log_lines_carry_level_and_utc_timestamp(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("svc")
    get_logger().info("stamped")
    line = _log_lines(capsys.readouterr().out)[-1]
    assert line["level"] == "info"
    assert str(line["timestamp"]).endswith("Z")


def test_console_logs_are_not_json_when_json_is_off(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("svc", json=False)
    get_logger().info("human readable")
    output = capsys.readouterr().out
    assert "human readable" in output
    assert _log_lines(output) == []


def test_configure_logging_drops_context_from_before(capsys: pytest.CaptureFixture[str]) -> None:
    structlog.contextvars.bind_contextvars(stale="leftover")
    configure_logging("fresh")
    get_logger().info("clean")
    line = _log_lines(capsys.readouterr().out)[-1]
    assert line["service"] == "fresh"
    assert "stale" not in line
