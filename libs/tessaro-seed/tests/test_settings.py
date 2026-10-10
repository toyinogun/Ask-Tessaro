"""SeedSettings: every value optional at load, required per subcommand (fail fast, all named)."""

import pytest
from pydantic import ValidationError

from tessaro_seed.settings import MissingSettings, SeedSettings


def test_require_passes_when_everything_named_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTHENTIK_URL", "https://auth.example")
    monkeypatch.setenv("AUTHENTIK_SEED_TOKEN", "t")
    settings = SeedSettings()
    settings.require("authentik_url", "authentik_seed_token")
    assert settings.secret("authentik_seed_token") == "t"


def test_require_names_every_missing_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTHENTIK_URL", "https://auth.example")
    monkeypatch.delenv("ZULIP_SITE", raising=False)
    monkeypatch.setenv("ZULIP_ADMIN_API_KEY", "")
    with pytest.raises(MissingSettings) as caught:
        SeedSettings().require("authentik_url", "zulip_site", "zulip_admin_api_key")
    assert str(caught.value) == "missing settings: ZULIP_SITE, ZULIP_ADMIN_API_KEY"


def test_a_url_without_a_scheme_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZULIP_SITE", "chat.example")
    with pytest.raises(ValidationError, match="http"):
        SeedSettings()


def test_a_trailing_slash_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZULIP_SITE", "https://chat.example/")
    assert SeedSettings().zulip_site == "https://chat.example"


def test_secret_of_an_unset_value_is_a_missing_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TESSARO_DEMO_PASSWORD", raising=False)
    with pytest.raises(MissingSettings, match="TESSARO_DEMO_PASSWORD"):
        SeedSettings().secret("tessaro_demo_password")


def test_secrets_never_show_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTHENTIK_SEED_TOKEN", "very-secret")
    assert "very-secret" not in repr(SeedSettings())
