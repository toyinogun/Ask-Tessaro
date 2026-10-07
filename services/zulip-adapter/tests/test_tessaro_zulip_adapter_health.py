from fastapi.testclient import TestClient

from tessaro_zulip_adapter.main import build_app
from tessaro_zulip_adapter.settings import Settings


def test_healthz() -> None:
    client = TestClient(build_app())
    assert client.get("/healthz").json() == {"status": "ok"}


def test_service_name_default() -> None:
    assert Settings().service_name == "zulip-adapter"


def test_readyz_is_ready_and_echoes_the_request_id() -> None:
    client = TestClient(build_app())
    response = client.get("/readyz", headers={"X-Request-ID": "svc-1"})
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {}}
    assert response.headers["X-Request-ID"] == "svc-1"
