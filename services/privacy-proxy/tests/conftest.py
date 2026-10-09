"""Shared fixtures: the real dataset's directory, fakeredis, the fake analyzer, a fake upstream.

`tessaro_dataset` is a workspace package (installed by `uv sync --all-packages`); the
proxy itself never imports it, only these tests do, to build `directory.json` the real way.
"""

import json
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fakeredis import FakeAsyncRedis

from tessaro_dataset import AMSTERDAM, Dataset, DatasetPaths, export_directory, load_dataset
from tessaro_privacy_proxy.analyzer.fake import FakeAnalyzer
from tessaro_privacy_proxy.main import Dependencies, build_app
from tessaro_privacy_proxy.mapping.cipher import KEY_BYTES, MappingCipher, encode_key
from tessaro_privacy_proxy.mapping.redis_store import RedisMappingStore
from tessaro_privacy_proxy.masking.directory import Directory
from tessaro_privacy_proxy.masking.ports import Analyzer
from tessaro_privacy_proxy.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
ANCHOR = datetime(2026, 10, 7, 10, 0, tzinfo=AMSTERDAM)
CLIENT_KEY = "k" * 40
MAPPING_KEY = encode_key(b"m" * KEY_BYTES)
LOOKUP_KEY = encode_key(b"l" * KEY_BYTES)
AGENT_MODEL = "deepseek-v4-pro"
TOOLS_MODEL = "deepseek-v4-flash"
CONVERSATION = "thread-1"
DAAN = "TES-01005"

# Any: OpenAI JSON bodies are open ended.
Json = dict[str, Any]


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    """The real dataset at a pinned anchor."""
    return load_dataset(DatasetPaths.under(REPO_ROOT), anchor=ANCHOR)


@pytest.fixture(scope="session")
def directory_json(dataset: Dataset) -> str:
    """`directory.json` exactly as `just dataset` writes it."""
    return json.dumps(export_directory(dataset).model_dump(mode="json"), sort_keys=True)


@pytest.fixture(scope="session")
def directory(directory_json: str) -> Directory:
    """The matcher built from the real directory."""
    return Directory.from_json(directory_json)


@pytest.fixture
def directory_file(tmp_path: Path, directory_json: str) -> Path:
    """The directory written to disk, as `PROXY_DIRECTORY_PATH` points at it."""
    path = tmp_path / "directory.json"
    path.write_text(directory_json, encoding="utf-8")
    return path


def make_settings(directory_file: Path, **overrides: Any) -> Settings:
    """Settings with test keys and the given directory file."""
    values: dict[str, Any] = {
        "proxy_client_key": CLIENT_KEY,
        "proxy_mapping_key": MAPPING_KEY,
        "proxy_lookup_key": LOOKUP_KEY,
        "proxy_directory_path": directory_file,
        "proxy_upstream_url": "https://upstream.test",
        "proxy_upstream_api_key": "upstream-secret",
        "llm_model_agent": AGENT_MODEL,
        "llm_model_tools": TOOLS_MODEL,
        "presidio_analyzer_url": "http://analyzer.test",
        "redis_url": "redis://unused:6379/0",
        **overrides,
    }
    return Settings(**values)


@pytest.fixture
def settings(directory_file: Path) -> Settings:
    """Default test settings."""
    return make_settings(directory_file)


@pytest.fixture
async def redis() -> AsyncIterator[FakeAsyncRedis]:
    """A fresh in memory Redis with Lua support."""
    client = FakeAsyncRedis()
    yield client
    await client.aclose()


def make_store(redis: FakeAsyncRedis, ttl_seconds: int = 86_400) -> RedisMappingStore:
    """The real store over fakeredis, with the test keys."""
    cipher = MappingCipher(mapping_key=b"m" * KEY_BYTES, lookup_key=b"l" * KEY_BYTES)
    return RedisMappingStore(redis=redis, cipher=cipher, ttl_seconds=ttl_seconds)


@pytest.fixture
def store(redis: FakeAsyncRedis) -> RedisMappingStore:
    """The store under test."""
    return make_store(redis)


Reply = Callable[[Json], Json]


def answer(content: str | None = None, tool_calls: list[Json] | None = None) -> Json:
    """An OpenAI completion with one choice."""
    message: Json = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "id": "cmpl-1",
        "object": "chat.completion",
        "model": AGENT_MODEL,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
    }


def tool_call(name: str, arguments: Json | str, call_id: str = "call-1") -> Json:
    """One OpenAI tool call."""
    args = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


@dataclass
class Upstream:
    """A fake model API that records every request and answers with `reply`."""

    reply: Reply = field(default=lambda _body: answer("ok"))
    status: int = 200
    raw: bytes | None = None
    raise_error: Exception | None = None
    requests: list[httpx.Request] = field(default_factory=list)

    @property
    def bodies(self) -> list[Json]:
        """The JSON bodies sent upstream, in order."""
        return [json.loads(r.content) for r in self.requests]

    def handler(self, request: httpx.Request) -> httpx.Response:
        """MockTransport handler."""
        self.requests.append(request)
        if self.raise_error is not None:
            raise self.raise_error
        if self.raw is not None:
            return httpx.Response(self.status, content=self.raw)
        return httpx.Response(self.status, json=self.reply(json.loads(request.content)))

    @property
    def transport(self) -> httpx.MockTransport:
        """The transport to give `build_app`."""
        return httpx.MockTransport(self.handler)


@pytest.fixture
def upstream() -> Upstream:
    """A fresh fake upstream."""
    return Upstream()


@dataclass
class Proxy:
    """A running proxy app and the client that calls it."""

    client: httpx.AsyncClient
    upstream: Upstream
    redis: FakeAsyncRedis

    async def chat(
        self,
        messages: list[Json],
        *,
        conversation: str | None = CONVERSATION,
        key: str | None = CLIENT_KEY,
        **extra: Any,
    ) -> httpx.Response:
        """POST a chat completion with the usual headers (drop one by passing None)."""
        headers: dict[str, str] = {}
        if key is not None:
            headers["Authorization"] = f"Bearer {key}"
        if conversation is not None:
            headers["X-Conversation-ID"] = conversation
        body = {"model": AGENT_MODEL, "messages": messages, **extra}
        return await self.client.post("/v1/chat/completions", json=body, headers=headers)


ProxyFactory = Callable[..., Proxy]


@pytest.fixture
def make_proxy(settings: Settings, redis: FakeAsyncRedis, upstream: Upstream) -> ProxyFactory:
    """Build a proxy. Pass `analyzer` (default: a fake that finds nothing), an
    `analyzer_transport` for the real adapter over a mock, or `live_analyzer=True`."""

    def factory(
        analyzer: Analyzer | None = None,
        analyzer_transport: httpx.MockTransport | None = None,
        app_settings: Settings | None = None,
        live_analyzer: bool = False,
    ) -> Proxy:
        if analyzer is None and analyzer_transport is None and not live_analyzer:
            analyzer = FakeAnalyzer()
        deps = Dependencies(
            redis=redis,
            analyzer=analyzer,
            upstream_transport=upstream.transport,
            analyzer_transport=analyzer_transport,
        )
        app = build_app(app_settings or settings, deps)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://proxy")
        return Proxy(client=client, upstream=upstream, redis=redis)

    return factory


@pytest.fixture
def proxy(make_proxy: ProxyFactory) -> Proxy:
    """A proxy whose analyzer finds nothing: only the directory and patterns mask."""
    return make_proxy()


def user(text: str) -> Json:
    """A user message."""
    return {"role": "user", "content": text}


def everything_in(mapping: Mapping[str, Any]) -> str:
    """The JSON text of a body, for leak assertions."""
    return json.dumps(mapping, ensure_ascii=False)
