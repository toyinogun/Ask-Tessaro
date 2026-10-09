"""privacy-proxy settings, read from env vars only. A missing or bad value stops startup."""

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import SettingsConfigDict

from tessaro_core import ServiceSettings
from tessaro_privacy_proxy.mapping.cipher import decode_key

MIN_CLIENT_KEY_LENGTH = 32


class Settings(ServiceSettings):
    """Spec 0006 *Configuration required*. Names from PRD 14.3 kept where they exist."""

    model_config = SettingsConfigDict(frozen=True, extra="ignore", env_ignore_empty=True)

    service_name: str = "privacy-proxy"

    proxy_client_key: SecretStr = Field(min_length=MIN_CLIENT_KEY_LENGTH)
    proxy_mapping_key: SecretStr
    proxy_lookup_key: SecretStr
    proxy_directory_path: Path
    proxy_upstream_url: str = "https://api.deepseek.com"
    proxy_upstream_api_key: SecretStr = SecretStr("")
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
