"""privacy-proxy entry point: `uvicorn tessaro_privacy_proxy.main:app --port 8080`."""

from dataclasses import dataclass

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from redis.asyncio import Redis

from tessaro_core import ReadinessCheck, create_app, create_http_client
from tessaro_privacy_proxy.analyzer.http import HttpAnalyzer
from tessaro_privacy_proxy.chat.errors import validation_error_handler
from tessaro_privacy_proxy.chat.routes import ChatService, chat_router
from tessaro_privacy_proxy.mapping.cipher import MappingCipher, decode_key
from tessaro_privacy_proxy.mapping.redis_store import RedisMappingStore
from tessaro_privacy_proxy.masking.directory import Directory
from tessaro_privacy_proxy.masking.errors import DirectoryError
from tessaro_privacy_proxy.masking.mask import Masker
from tessaro_privacy_proxy.masking.ports import Analyzer
from tessaro_privacy_proxy.settings import Settings
from tessaro_privacy_proxy.upstream.client import UpstreamClient


@dataclass(frozen=True)
class Dependencies:
    """Adapters `build_app` would otherwise create; tests pass fakes here."""

    redis: Redis | None = None
    analyzer: Analyzer | None = None
    upstream_transport: httpx.AsyncBaseTransport | None = None
    analyzer_transport: httpx.AsyncBaseTransport | None = None


def load_directory(settings: Settings) -> Directory:
    """The directory from `PROXY_DIRECTORY_PATH`; the service refuses to start without it."""
    path = settings.proxy_directory_path
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DirectoryError(f"cannot read the directory file {path}") from exc
    return Directory.from_json(text)


def _store(settings: Settings, redis: Redis) -> RedisMappingStore:
    cipher = MappingCipher(
        mapping_key=decode_key(settings.proxy_mapping_key.get_secret_value()),
        lookup_key=decode_key(settings.proxy_lookup_key.get_secret_value()),
    )
    return RedisMappingStore(redis=redis, cipher=cipher, ttl_seconds=settings.mapping_ttl_seconds)


def build_app(settings: Settings, deps: Dependencies | None = None) -> FastAPI:
    """Wire the proxy. Fails at startup on a bad setting or a missing directory."""
    given = deps or Dependencies()
    redis = given.redis or Redis.from_url(settings.redis_url)
    http_analyzer = HttpAnalyzer(
        client=create_http_client(
            settings.presidio_analyzer_url,
            timeout=settings.proxy_analyzer_timeout_seconds,
            transport=given.analyzer_transport,
        ),
        score_threshold=settings.proxy_score_threshold,
    )
    store = _store(settings, redis)
    upstream = UpstreamClient(
        # A plain client: nothing from the caller, not even our request ID, goes upstream.
        client=httpx.AsyncClient(
            base_url=settings.proxy_upstream_url,
            timeout=settings.proxy_upstream_timeout_seconds,
            transport=given.upstream_transport,
        ),
        api_key=settings.proxy_upstream_api_key.get_secret_value(),
    )
    masker = Masker(
        directory=load_directory(settings),
        analyzer=given.analyzer or http_analyzer,
        store=store,
        score_threshold=settings.proxy_score_threshold,
    )

    async def redis_ready() -> bool:
        return bool(await redis.ping())

    app = create_app(
        settings,
        readiness_checks=(
            ReadinessCheck("analyzer", http_analyzer.healthy),
            ReadinessCheck("redis", redis_ready),
        ),
    )
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(
        chat_router(
            ChatService(
                masker=masker,
                store=store,
                upstream=upstream,
                client_key=settings.proxy_client_key.get_secret_value(),
                allowed_models=settings.allowed_models,
            )
        )
    )
    return app


def __getattr__(name: str) -> FastAPI:
    """`app` for uvicorn, built on first access so importing this module needs no env vars."""
    if name == "app":
        return build_app(Settings())
    raise AttributeError(name)
