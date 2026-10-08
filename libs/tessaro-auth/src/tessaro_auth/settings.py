"""Token settings, mixed into a service's settings class. Both fail fast at startup."""

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tessaro_auth.claims import MAX_LIFETIME_SECONDS, kind_of_kid
from tessaro_auth.keys import KeySet, Signer, parse_jwks, private_key_from_base64url

_CONFIG = SettingsConfigDict(frozen=True, extra="ignore", env_ignore_empty=True)


class TokenVerifySettings(BaseSettings):
    """`TOKEN_VERIFY_KEYS`: the JWK set every verifying service needs (public keys only)."""

    model_config = _CONFIG

    token_verify_keys: str

    @field_validator("token_verify_keys")
    @classmethod
    def _parse(cls, value: str) -> str:
        parse_jwks(value)
        return value

    @property
    def keyset(self) -> KeySet:
        """The parsed, validated key set."""
        return parse_jwks(self.token_verify_keys)


class TokenSigningSettings(BaseSettings):
    """The minter's private key, its kid and the token lifetime. Minters only."""

    model_config = _CONFIG

    token_signing_key: SecretStr
    token_signing_kid: str
    token_ttl_seconds: int = Field(default=300, ge=1, le=MAX_LIFETIME_SECONDS)

    @field_validator("token_signing_key")
    @classmethod
    def _check_key(cls, value: SecretStr) -> SecretStr:
        private_key_from_base64url(value.get_secret_value())
        return value

    @field_validator("token_signing_kid")
    @classmethod
    def _check_kid(cls, value: str) -> str:
        if kind_of_kid(value) is None:
            raise ValueError("TOKEN_SIGNING_KID must match (adapter|worker)-<n>")
        return value

    @property
    def signer(self) -> Signer:
        """The signer built from the key and kid."""
        return Signer.from_base64url(
            self.token_signing_kid, self.token_signing_key.get_secret_value()
        )
