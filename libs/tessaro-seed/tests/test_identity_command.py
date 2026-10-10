"""The `tessaro-seed identity` edge: settings, exit codes and what it prints."""

from pathlib import Path

import pytest

from tessaro_clients.authentik import FakeAuthentikDirectory
from tessaro_clients.zulip import FakeZulipAdmin
from tessaro_dataset import Dataset
from tessaro_seed.identity import command
from tessaro_seed.identity.reconcile import IdentityInput

REPO_ROOT = Path(__file__).resolve().parents[3]

ENV = {
    "AUTHENTIK_URL": "https://auth.example",
    "AUTHENTIK_SEED_TOKEN": "seed-token",
    "ZULIP_SITE": "https://chat.example",
    "ZULIP_ADMIN_EMAIL": "tessaro-admin@tessaro.example",
    "ZULIP_ADMIN_API_KEY": "owner-key",
    "TESSARO_DEMO_PASSWORD": "demo-pass",
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def fakes(
    monkeypatch: pytest.MonkeyPatch, data: IdentityInput
) -> tuple[FakeAuthentikDirectory, FakeZulipAdmin]:
    directory = FakeAuthentikDirectory.with_groups(data.managed_groups)
    chat = FakeZulipAdmin()
    monkeypatch.setattr(command, "HttpAuthentikDirectory", lambda http: directory)
    monkeypatch.setattr(command, "HttpZulipAdmin", lambda http: chat)
    return directory, chat


def test_identity_input_excludes_joiners_but_manages_their_groups(dataset: Dataset) -> None:
    data = command.identity_input(dataset, "pw")
    seeded = {u.employee_id for u in data.authentik.users}
    assert seeded == {e.id for e in dataset.employees if e.is_seed}
    assert {g for u in data.authentik.users for g in u.groups} <= data.managed_groups


@pytest.mark.usefixtures("env", "fakes")
def test_a_run_prints_each_write_and_the_counts(capsys: pytest.CaptureFixture[str]) -> None:
    assert command.main(["--root", str(REPO_ROOT)]) == command.EXIT_OK
    out = capsys.readouterr().out
    assert "authentik: create user " in out
    assert "zulip: create channel " in out
    assert "authentik users: " in out
    assert " 0 updated, 0 unchanged" in out


@pytest.mark.usefixtures("env")
def test_a_dry_run_says_would_and_writes_nothing(
    fakes: tuple[FakeAuthentikDirectory, FakeZulipAdmin], capsys: pytest.CaptureFixture[str]
) -> None:
    assert command.main(["--root", str(REPO_ROOT), "--dry-run"]) == command.EXIT_OK
    assert "authentik: would create user " in capsys.readouterr().out
    assert fakes[0].writes == fakes[1].writes == []


@pytest.mark.usefixtures("env")
def test_a_reconcile_error_exits_1(
    fakes: tuple[FakeAuthentikDirectory, FakeZulipAdmin], capsys: pytest.CaptureFixture[str]
) -> None:
    fakes[1].realm = False
    assert command.main(["--root", str(REPO_ROOT)]) == command.EXIT_FAILED
    assert "just zulip-bootstrap" in capsys.readouterr().err


def test_missing_owner_settings_point_at_the_bootstrap(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("ZULIP_ADMIN_API_KEY")
    assert command.main(["--root", str(REPO_ROOT)]) == command.EXIT_FAILED
    err = capsys.readouterr().err
    assert "ZULIP_ADMIN_API_KEY" in err
    assert "just zulip-bootstrap" in err


def test_other_missing_settings_point_at_identity_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("AUTHENTIK_SEED_TOKEN")
    assert command.main(["--root", str(REPO_ROOT)]) == command.EXIT_FAILED
    err = capsys.readouterr().err
    assert "AUTHENTIK_SEED_TOKEN" in err
    assert "zulip-bootstrap" not in err
    assert "just identity-secrets" in err


def test_a_bad_dataset_root_exits_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    assert command.main(["--root", str(tmp_path)]) == command.EXIT_FAILED
    assert "identity seed failed" in capsys.readouterr().err


def test_an_unknown_flag_is_bad_usage() -> None:
    with pytest.raises(SystemExit) as caught:
        command.main(["--nope"])
    assert caught.value.code == 2
