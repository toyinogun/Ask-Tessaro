"""tool-gateway settings, read from env vars only."""

from tessaro_core import ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "tool-gateway"
