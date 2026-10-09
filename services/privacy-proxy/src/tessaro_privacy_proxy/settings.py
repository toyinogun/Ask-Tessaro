"""privacy-proxy settings, read from env vars only. A missing or bad value stops startup."""

from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import SettingsConfigDict

from tessaro_core import ServiceSettings
from tessaro_privacy_proxy.mapping.cipher import decode_key

MIN_CLIENT_KEY_LENGTH = 32
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def is_loopback(url: str) -> bool:
    """Whether `url` points at this machine (a local fake upstream during development)."""
    return urlsplit(url).hostname in LOOPBACK_HOSTS


class Settings(ServiceSettings):
    """Spec 0006 *Configuration required*. Names from PRD 14.3 kept where they exist."""

    model_config = SettingsConfigDict(frozen=True, extra="ignore", env_ignore_empty=True)

    service_name: str = "privacy-proxy"

    proxy_client_key: SecretStr = Field(min_length=MIN_CLIENT_KEY_LENGTH)
    proxy_mapping_key: SecretStr
    proxy_lookup_key: SecretStr
    proxy_directory_path: Path
    proxy_upstream_url: str = "https://api.deepseek.com"
    proxy_upstream_api_key: SecretStr = SecretStr("")  # empty only for a loopback upstream
    proxy_mapping_ttl_hours: int = Field(default=24, ge=1)
    proxy_fail_closed: bool = True
    proxy_score_threshold: float = Field(default=0.4, ge=0.0, le=1.0)
    proxy_analyzer_timeout_seconds: float = Field(default=5.0, gt=0)
    proxy_upstream_timeout_seconds: float = Field(default=60.0, gt=0)

    llm_model_agent: str
    llm_model_tools: str
    presidio_analyzer_url: str
    redis_url: str

    @field_validator("proxy_mapping_key", "proxy_lookup_key")
    @classmethod
    def _check_key(cls, value: SecretStr) -> SecretStr:
        decode_key(value.get_secret_value())
        return value

    @field_validator("proxy_upstream_url")
    @classmethod
    def _check_upstream_url(cls, value: str) -> str:
        scheme = urlsplit(value).scheme
        if scheme == "https" or (scheme == "http" and is_loopback(value)):
            return value
        raise ValueError("PROXY_UPSTREAM_URL must be https (plain http only on loopback)")

    @model_validator(mode="after")
    def _check_secrets(self) -> Self:
        if self.proxy_mapping_key.get_secret_value() == self.proxy_lookup_key.get_secret_value():
            raise ValueError("PROXY_MAPPING_KEY and PROXY_LOOKUP_KEY must be different keys")
        if not self.proxy_upstream_api_key.get_secret_value() and not is_loopback(
            self.proxy_upstream_url
        ):
            raise ValueError("PROXY_UPSTREAM_API_KEY is required for a remote upstream")
        return self

    @field_validator("proxy_fail_closed", mode="before")
    @classmethod
    def _always_closed(cls, value: object) -> bool:
        # Only the literal `true` (any case): pydantic's bool would also take yes, 1 and on.
        if value is True or (isinstance(value, str) and value.lower() == "true"):
            return True
        raise ValueError("PROXY_FAIL_CLOSED must be true: the proxy never fails open")

    @property
    def allowed_models(self) -> frozenset[str]:
        """The model names a caller may ask for."""
        return frozenset({self.llm_model_agent, self.llm_model_tools})

    @property
    def mapping_ttl_seconds(self) -> int:
        """`PROXY_MAPPING_TTL_HOURS` in seconds."""
        return self.proxy_mapping_ttl_hours * 3600
