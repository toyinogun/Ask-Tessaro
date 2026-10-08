"""Shared base for export records: frozen, typed, serialised to JSON with sorted keys."""

from pydantic import BaseModel, ConfigDict


class ExportRecord(BaseModel):
    """A record written for one target system; frozen and closed to unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")
