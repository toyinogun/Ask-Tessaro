import httpx

from tessaro_privacy_proxy.analyzer.fake import FakeAnalyzer

from .conftest import Proxy, ProxyFactory


async def test_healthz(proxy: Proxy) -> None:
    response = await proxy.client.get("/healthz")
    assert response.json() == {"status": "ok"}


async def test_request_id_is_echoed(proxy: Proxy) -> None:
    response = await proxy.client.get("/healthz", headers={"X-Request-ID": "svc-1"})
    assert response.headers["X-Request-ID"] == "svc-1"


async def test_readyz_checks_the_analyzer_and_redis(make_proxy: ProxyFactory) -> None:
    """covers: AC-11"""
    healthy = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    ready = await make_proxy(analyzer_transport=healthy).client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "checks": {"analyzer": True, "redis": True}}

    down = httpx.MockTransport(lambda _r: httpx.Response(503))
    not_ready = await make_proxy(analyzer=FakeAnalyzer(), analyzer_transport=down).client.get(
        "/readyz"
    )
    assert not_ready.status_code == 503
    assert not_ready.json()["checks"] == {"analyzer": False, "redis": True}
