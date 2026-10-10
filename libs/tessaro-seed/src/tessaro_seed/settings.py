"""`SeedSettings`: the env vars `tessaro-seed` reads (spec 0008 *Configuration required*).

Every value is optional when loading, because each subcommand needs a different set; a
subcommand calls `require` with its own names first and stops before any network call, naming
every missing variable at once.
"""

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MissingSettings(Exception):
    """Variables a subcommand needs are unset or empty."""


class SeedSettings(BaseSettings):
    """Authentik and Zulip endpoints and credentials, from the environment (`.env` via just)."""

    model_config = SettingsConfigDict(frozen=True, extra="ignore", env_ignore_empty=True)

    authentik_url: str | None = None
    authentik_seed_token: SecretStr | None = None
    authentik_bootstrap_token: SecretStr | None = None
    zulip_adapter_authentik_token: SecretStr | None = None
    zulip_site: str | None = None
    zulip_admin_email: str | None = None
    zulip_admin_api_key: SecretStr | None = None
    tessaro_demo_password: SecretStr | None = None

    @field_validator("authentik_url", "zulip_site")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("https://", "http://")):
            raise ValueError("must start with https:// or http://")
        return value.rstrip("/") if value is not None else None

    def require(self, *names: str) -> None:
        """Raise MissingSettings naming every one of ``names`` that is unset."""
        missing = [name.upper() for name in names if getattr(self, name) is None]
        if missing:
            raise MissingSettings(f"missing settings: {', '.join(missing)}")

    def secret(self, name: str) -> str:
        """The plain value of a secret setting; MissingSettings when it is unset."""
        self.require(name)
        value: SecretStr = getattr(self, name)
        return value.get_secret_value()
