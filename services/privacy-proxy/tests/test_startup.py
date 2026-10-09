"""Settings, the directory at startup, `just keys` and the lazy `app` (spec 0006 config)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

import tessaro_privacy_proxy.main as main
from tessaro_privacy_proxy.devkeys import MANAGED, ensure_proxy_keys
from tessaro_privacy_proxy.devkeys import main as devkeys_main
from tessaro_privacy_proxy.mapping.cipher import decode_key
from tessaro_privacy_proxy.masking.errors import DirectoryError

from .conftest import CLIENT_KEY, LOOKUP_KEY, MAPPING_KEY, make_settings


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
    ],
)
def test_bad_settings_stop_startup(directory_file: Path, override: dict[str, object]) -> None:
    """covers: AC-8 (PROXY_FAIL_CLOSED cannot be turned off), configuration fails fast"""
    with pytest.raises(ValidationError):
        make_settings(directory_file, **override)


def test_settings_come_from_env_vars(directory_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        "PROXY_CLIENT_KEY": CLIENT_KEY,
        "PROXY_MAPPING_KEY": MAPPING_KEY,
        "PROXY_LOOKUP_KEY": LOOKUP_KEY,
        "PROXY_DIRECTORY_PATH": str(directory_file),
        "PROXY_UPSTREAM_API_KEY": "",
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
