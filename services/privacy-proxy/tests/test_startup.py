"""Settings, the directory at startup, `just keys` and the lazy `app` (spec 0006 config)."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

import tessaro_privacy_proxy.main as main
from tessaro_privacy_proxy.devkeys import MANAGED, ensure_proxy_keys
from tessaro_privacy_proxy.devkeys import main as devkeys_main
from tessaro_privacy_proxy.mapping.cipher import decode_key
from tessaro_privacy_proxy.masking.errors import DirectoryError
from tessaro_privacy_proxy.settings import Settings

from .conftest import CLIENT_KEY, LOOKUP_KEY, MAPPING_KEY, make_settings

REDIS_URL = "redis://localhost:6379/0"  # never connected: the tests drive the retry policy only


def test_defaults_and_derived_values(directory_file: Path) -> None:
    settings = make_settings(directory_file)
    assert settings.service_name == "privacy-proxy"
    assert settings.mapping_ttl_seconds == 24 * 3600
    assert settings.proxy_score_threshold == 0.4
    assert settings.allowed_models == {"deepseek-v4-pro", "deepseek-v4-flash"}


@pytest.mark.parametrize(
    "override",
    [
        {"proxy_fail_closed": False},
        {"proxy_client_key": "short"},
        {"proxy_mapping_key": "not-a-key"},
        {"proxy_lookup_key": MAPPING_KEY[:-4]},
        {"proxy_score_threshold": 1.5},
        {"proxy_mapping_ttl_hours": 0},
        {"proxy_lookup_key": MAPPING_KEY},
        {"proxy_upstream_url": "http://api.deepseek.com"},
        {"proxy_upstream_url": "ftp://api.deepseek.com"},
        {"proxy_upstream_api_key": ""},
    ],
)
def test_bad_settings_stop_startup(directory_file: Path, override: dict[str, object]) -> None:
    """covers: AC-8 (PROXY_FAIL_CLOSED cannot be turned off), configuration fails fast"""
    with pytest.raises(ValidationError):
        make_settings(directory_file, **override)


@pytest.mark.parametrize("value", ["yes", "1", "on", " true", "", "false", 1])
def test_fail_closed_accepts_only_the_literal_true(directory_file: Path, value: object) -> None:
    """covers: AC-8"""
    with pytest.raises(ValidationError):
        make_settings(directory_file, proxy_fail_closed=value)


@pytest.mark.parametrize("url", ["http://localhost:9000", "http://127.0.0.1:9000", "http://[::1]"])
def test_a_loopback_upstream_may_use_http_and_no_key(directory_file: Path, url: str) -> None:
    """A local fake upstream for development; anything else needs https and a key."""
    settings = make_settings(directory_file, proxy_upstream_url=url, proxy_upstream_api_key="")
    assert settings.proxy_upstream_url == url


@pytest.mark.parametrize("value", ["true", "TRUE", True])
def test_fail_closed_true_passes(directory_file: Path, value: object) -> None:
    """covers: AC-8"""
    assert make_settings(directory_file, proxy_fail_closed=value).proxy_fail_closed is True


def test_the_mapping_client_retries_once_and_readiness_never_retries() -> None:
    """covers: AC-8 (one retry after a stale connection), AC-11 (readiness reports the truth)"""
    mapping = main.mapping_redis("redis://localhost:6379/0")
    kwargs = mapping.connection_pool.connection_kwargs
    assert kwargs["health_check_interval"] == 30
    retry = kwargs["retry"]
    assert retry._retries == 1
    assert {RedisConnectionError, RedisTimeoutError} <= set(retry._supported_errors)
    probe = main.readiness_redis("redis://localhost:6379/0")
    assert probe.connection_pool.connection_kwargs.get("retry") in (None,) or (
        probe.connection_pool.connection_kwargs["retry"]._retries == 0
    )


class _Flaky:
    """An operation that raises the given errors in turn, then returns "ok"."""

    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.attempts = 0

    async def __call__(self) -> str:
        self.attempts += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


async def _ignore(_: Exception) -> None:
    return None


def _retry_of(client: Redis) -> Retry:
    retry = client.connection_pool.connection_kwargs["retry"]
    assert isinstance(retry, Retry)
    return retry


@pytest.mark.parametrize("error", [RedisConnectionError("gone"), RedisTimeoutError("slow")])
async def test_the_mapping_client_recovers_after_one_dropped_call(error: Exception) -> None:
    """covers: AC-8 (the first request after a Redis restart succeeds)"""
    op = _Flaky(error)
    result = await _retry_of(main.mapping_redis(REDIS_URL)).call_with_retry(op, _ignore)
    assert (result, op.attempts) == ("ok", 2)


async def test_the_mapping_client_gives_up_after_the_second_failure() -> None:
    """covers: AC-8 (two failures in a row reach the 503 path)"""
    op = _Flaky(RedisConnectionError("gone"), RedisConnectionError("still gone"))
    with pytest.raises(RedisConnectionError, match="still gone"):
        await _retry_of(main.mapping_redis(REDIS_URL)).call_with_retry(op, _ignore)
    assert op.attempts == 2


async def test_the_mapping_client_never_retries_other_redis_errors() -> None:
    """covers: AC-8 (any other Redis error fails at once)"""
    op = _Flaky(ResponseError("NOSCRIPT"))
    with pytest.raises(ResponseError):
        await _retry_of(main.mapping_redis(REDIS_URL)).call_with_retry(op, _ignore)
    assert op.attempts == 1


async def test_the_readiness_client_makes_a_single_attempt() -> None:
    """covers: AC-11 (readiness reports a Redis outage at once)"""
    op = _Flaky(RedisConnectionError("gone"))
    with pytest.raises(RedisConnectionError):
        await _retry_of(main.readiness_redis(REDIS_URL)).call_with_retry(op, _ignore)
    assert op.attempts == 1


def test_settings_come_from_env_vars(directory_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        "PROXY_CLIENT_KEY": CLIENT_KEY,
        "PROXY_MAPPING_KEY": MAPPING_KEY,
        "PROXY_LOOKUP_KEY": LOOKUP_KEY,
        "PROXY_DIRECTORY_PATH": str(directory_file),
        "PROXY_UPSTREAM_API_KEY": "upstream-secret",
        "PROXY_FAIL_CLOSED": "true",
        "LLM_MODEL_AGENT": "a",
        "LLM_MODEL_TOOLS": "b",
        "PRESIDIO_ANALYZER_URL": "http://analyzer.test",
        "REDIS_URL": "redis://localhost:6379/0",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    app = main.app
    assert app.title == "privacy-proxy"
    monkeypatch.setenv("PROXY_FAIL_CLOSED", "")
    assert Settings().proxy_fail_closed is True  # an empty env value reads as unset
    monkeypatch.setenv("PROXY_FAIL_CLOSED", "false")
    with pytest.raises(ValidationError):
        _ = main.app
    with pytest.raises(AttributeError):
        _ = main.nothing_here


def test_a_missing_or_bad_directory_stops_startup(tmp_path: Path) -> None:
    """covers: AC-4"""
    with pytest.raises(DirectoryError):
        main.load_directory(make_settings(tmp_path / "absent.json"))
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(DirectoryError):
        main.load_directory(make_settings(bad))


def test_keys_fill_only_what_is_empty() -> None:
    text = "# comment\nPROXY_CLIENT_KEY=\nPROXY_MAPPING_KEY='keep-me'\nOTHER=1\n"
    updated = ensure_proxy_keys(text)
    assert updated is not None
    lines = dict(line.split("=", 1) for line in updated.splitlines() if "=" in line)
    assert lines["PROXY_MAPPING_KEY"] == "'keep-me'"
    assert len(lines["PROXY_CLIENT_KEY"]) >= 32
    assert len(decode_key(lines["PROXY_LOOKUP_KEY"])) == 32
    assert lines["OTHER"] == "1"
    assert updated.startswith("# comment\n")
    assert ensure_proxy_keys(updated.replace("'keep-me'", "x")) is None


def test_keys_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env_file = tmp_path / ".env"
    assert devkeys_main(["--env-file", str(env_file)]) == 1
    env_file.write_text("A=1\n", encoding="utf-8")
    assert devkeys_main(["--env-file", str(env_file)]) == 0
    written = env_file.read_text(encoding="utf-8")
    assert all(f"{name}=" in written for name in MANAGED)
    assert devkeys_main(["--env-file", str(env_file)]) == 0
    assert env_file.read_text(encoding="utf-8") == written
    assert "unchanged" in capsys.readouterr().out
