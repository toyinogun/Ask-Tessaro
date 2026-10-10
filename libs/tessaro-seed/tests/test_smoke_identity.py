"""`tessaro-seed smoke identity`: check (a), the persona signs in to Zulip (spec 0008 AC-14)."""

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tessaro_dataset import Dataset
from tessaro_seed.smoke import command
from tessaro_seed.smoke.identity import Persona, SmokeError, persona_of, smoke_identity

REPO_ROOT = Path(__file__).resolve().parents[3]
SITE = "https://chat.example"
DEMO = "demo-pass"


@dataclass
class FakeBrowser:
    """Signs a known username and password in, answering the email Zulip would give the session."""

    accounts: dict[tuple[str, str], str] = field(default_factory=dict)
    failure: str | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def zulip_session_email(self, site: str, username: str, password: str) -> str | None:
        self.calls.append((site, username))
        if self.failure is not None:
            raise SmokeError(self.failure)
        return self.accounts.get((username, password))


def persona(dataset: Dataset) -> Persona:
    return persona_of(dataset)


def test_the_persona_is_the_demo_cast_persona_from_the_export(dataset: Dataset) -> None:
    found = persona(dataset)
    assert found.employee_id == "TES-01003"
    assert found.email.endswith("@tessaro.example")
    assert "staff" in found.groups
    assert found.username == found.email.split("@")[0]


async def test_a_session_with_the_persona_email_passes(dataset: Dataset) -> None:
    who = persona(dataset)
    browser = FakeBrowser({(who.username, DEMO): who.email})
    (check,) = await smoke_identity(browser, SITE, who, DEMO)
    assert check.passed
    assert check.name == "a. demo persona signs in to Zulip through Authentik"
    assert browser.calls == [(SITE, who.username)]


async def test_no_session_fails(dataset: Dataset) -> None:
    (check,) = await smoke_identity(FakeBrowser(), SITE, persona(dataset), DEMO)
    assert not check.passed
    assert "no Zulip session" in check.detail


async def test_another_email_fails(dataset: Dataset) -> None:
    who = persona(dataset)
    browser = FakeBrowser({(who.username, DEMO): "someone@else"})
    (check,) = await smoke_identity(browser, SITE, who, DEMO)
    assert not check.passed
    assert "someone@else" in check.detail


async def test_a_browser_failure_is_a_failed_check_not_a_crash(dataset: Dataset) -> None:
    browser = FakeBrowser(failure="stuck on auth.example/if/flow/x")
    (check,) = await smoke_identity(browser, SITE, persona(dataset), DEMO)
    assert not check.passed
    assert "stuck on" in check.detail


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZULIP_SITE", SITE)
    monkeypatch.setenv("TESSARO_DEMO_PASSWORD", DEMO)


@pytest.mark.usefixtures("env")
def test_the_command_passes_when_every_check_passes(
    monkeypatch: pytest.MonkeyPatch, dataset: Dataset, capsys: pytest.CaptureFixture[str]
) -> None:
    who = persona(dataset)
    monkeypatch.setattr(
        command, "PlaywrightSignIn", lambda: FakeBrowser({(who.username, DEMO): who.email})
    )
    assert command.main(["identity", "--root", str(REPO_ROOT)]) == command.EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("PASS a. demo persona")
    assert DEMO not in out


@pytest.mark.usefixtures("env")
def test_the_command_fails_naming_the_failed_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(command, "PlaywrightSignIn", FakeBrowser)
    assert command.main(["identity", "--root", str(REPO_ROOT)]) == command.EXIT_FAILED
    assert "FAIL a. demo persona" in capsys.readouterr().out


def test_missing_settings_are_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ZULIP_SITE", raising=False)
    monkeypatch.delenv("TESSARO_DEMO_PASSWORD", raising=False)
    assert command.main(["identity", "--root", str(REPO_ROOT)]) == command.EXIT_FAILED
    assert "ZULIP_SITE, TESSARO_DEMO_PASSWORD" in capsys.readouterr().err


def test_an_unknown_smoke_is_bad_usage() -> None:
    with pytest.raises(SystemExit) as exit_:
        command.main(["chat"])
    assert exit_.value.code == command.EXIT_USAGE
