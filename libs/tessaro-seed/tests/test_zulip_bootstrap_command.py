"""The `tessaro-seed zulip-bootstrap` edge: the context guard, exit codes and the `.env` write."""

from pathlib import Path
from typing import Any

import pytest

from tessaro_seed.zulip_bootstrap import command
from tessaro_seed.zulip_bootstrap.realm import OWNER_EMAIL

# Any: the conftest's FakeServer (test modules cannot import conftest under importlib mode).
Server = Any
CONTEXT = "k3s-test"
KEY = "owner-api-key"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TESSARO_KUBE_CONTEXT", CONTEXT)
    monkeypatch.setenv("ZULIP_SITE", "https://chat.example")


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, zulip_server: Server) -> Server:
    """The command talks to the fake server and its fake `ZulipAdmin`, in context CONTEXT."""

    async def context() -> str:
        return CONTEXT

    monkeypatch.setattr(command, "current_context", context)
    monkeypatch.setattr(command, "KubectlZulipServer", lambda ctx: zulip_server)
    monkeypatch.setattr(command, "HttpZulipAdmin", lambda http: zulip_server.chat)
    return zulip_server


def root_with_env(tmp_path: Path, text: str = "ZULIP_SITE=https://chat.example\n") -> Path:
    (tmp_path / ".env").write_text(text)
    return tmp_path


@pytest.mark.usefixtures("env", "wired")
def test_a_run_prints_each_step_and_writes_the_owner_into_env(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = root_with_env(tmp_path, "ZULIP_SITE=https://chat.example\nZULIP_ADMIN_API_KEY=\n")
    assert command.main(["--root", str(root)]) == command.EXIT_OK
    out = capsys.readouterr().out
    assert "realm Tessaro: created" in out
    assert KEY not in out
    text = (root / ".env").read_text()
    assert f"ZULIP_ADMIN_EMAIL={OWNER_EMAIL}\n" in text
    assert f"ZULIP_ADMIN_API_KEY={KEY}\n" in text
    assert text.startswith("ZULIP_SITE=https://chat.example\n")
    assert (root / ".env").stat().st_mode & 0o777 == 0o600


@pytest.mark.usefixtures("env", "wired")
def test_a_second_run_leaves_env_as_it_was(tmp_path: Path) -> None:
    root = root_with_env(tmp_path)
    command.main(["--root", str(root)])
    first = (root / ".env").read_text()
    assert command.main(["--root", str(root)]) == command.EXIT_OK
    assert (root / ".env").read_text() == first


@pytest.mark.usefixtures("env", "wired")
def test_another_context_is_refused_before_any_step(
    monkeypatch: pytest.MonkeyPatch,
    zulip_server: Server,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def other() -> str:
        return "prod"

    monkeypatch.setattr(command, "current_context", other)
    root = root_with_env(tmp_path)
    assert command.main(["--root", str(root)]) == command.EXIT_FAILED
    assert "refusing" in capsys.readouterr().err
    assert zulip_server.calls == []


@pytest.mark.usefixtures("env", "wired")
def test_a_failed_step_writes_nothing(
    zulip_server: Server, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    zulip_server.ready_ = False
    root = root_with_env(tmp_path)
    assert command.main(["--root", str(root)]) == command.EXIT_FAILED
    assert "not ready" in capsys.readouterr().err
    assert (root / ".env").read_text() == "ZULIP_SITE=https://chat.example\n"


@pytest.mark.usefixtures("env", "wired")
def test_a_failing_zulip_api_writes_nothing(
    zulip_server: Server, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    zulip_server.chat.broken = frozenset({"update_realm"})
    root = root_with_env(tmp_path)
    assert command.main(["--root", str(root)]) == command.EXIT_FAILED
    assert "zulip bootstrap failed" in capsys.readouterr().err
    assert "ZULIP_ADMIN_API_KEY" not in (root / ".env").read_text()


@pytest.mark.usefixtures("wired")
def test_missing_settings_are_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("TESSARO_KUBE_CONTEXT", raising=False)
    monkeypatch.delenv("ZULIP_SITE", raising=False)
    assert command.main(["--root", str(root_with_env(tmp_path))]) == command.EXIT_FAILED
    assert "TESSARO_KUBE_CONTEXT, ZULIP_SITE" in capsys.readouterr().err


@pytest.mark.usefixtures("env", "wired")
def test_a_missing_env_file_is_created(tmp_path: Path) -> None:
    assert command.main(["--root", str(tmp_path)]) == command.EXIT_OK
    assert f"ZULIP_ADMIN_API_KEY={KEY}" in (tmp_path / ".env").read_text()
