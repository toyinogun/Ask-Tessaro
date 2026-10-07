"""Typed settings base. Every service subclasses this; values come from env vars only."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class ServiceSettings(BaseSettings):
    """Common settings. Subclasses set a default `service_name` and add their own fields.

    A required field with no default makes the service fail fast at startup when its
    env var is missing.
    """

    model_config = SettingsConfigDict(frozen=True, extra="ignore")

    service_name: str
    log_level: LogLevel = "INFO"
    log_json: bool = True
