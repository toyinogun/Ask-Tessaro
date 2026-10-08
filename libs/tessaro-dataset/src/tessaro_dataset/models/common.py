"""Shared field types for every dataset model.

Date fields hold expressions in the YAML and resolve during validation against the
`DateContext` passed as pydantic's validation context. Scalars use strict types, so a
YAML quirk (an unquoted `10:30` read as a number, `no` read as a boolean) becomes a
validation problem instead of a silent wrong value.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationInfo,
)

from tessaro_dataset.dates import (
    AMSTERDAM,
    DateContext,
    resolve_date,
    resolve_timestamp,
    resolve_year,
)

Trap = Literal["prompt_injection", "sensitive_absence", "dutch_name"]
TRAPS: tuple[Trap, ...] = ("prompt_injection", "sensitive_absence", "dutch_name")


@dataclass(frozen=True)
class Sensitive:
    """Marks a field whose value may reach only its system of record's export."""

    reason: str


def _context(info: ValidationInfo) -> DateContext:
    ctx = info.context
    if not isinstance(ctx, DateContext):
        raise TypeError("dataset models validate with a DateContext as the context")
    return ctx


def _to_date(value: object, info: ValidationInfo) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return resolve_date(value, _context(info))


def _to_timestamp(value: object, info: ValidationInfo) -> datetime:
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(AMSTERDAM)
    return resolve_timestamp(value, _context(info))


def _to_year(value: object, info: ValidationInfo) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return resolve_year(value, _context(info))


def _to_amount(value: object) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"write amounts as quoted strings like '12.50', got {value!r}")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{value!r} is not an amount") from exc
    if amount <= 0 or amount.as_tuple().exponent != -2:
        raise ValueError(f"{value!r} must be above 0 with exactly 2 decimal places")
    return amount


DayField = Annotated[date, BeforeValidator(_to_date)]
TimestampField = Annotated[datetime, BeforeValidator(_to_timestamp)]
YearField = Annotated[int, BeforeValidator(_to_year)]
Amount = Annotated[Decimal, BeforeValidator(_to_amount)]
Text = Annotated[StrictStr, Field(min_length=1)]
ClockTime = Annotated[StrictStr, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
EmployeeId = Annotated[StrictStr, Field(pattern=r"^TES-\d{5}$")]
Slug = Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9-]*$")]
Flag = StrictBool
Count = StrictInt


class Record(BaseModel):
    """Base for every dataset record: frozen, no unknown keys."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def sensitive_fields(model: type[BaseModel]) -> tuple[str, ...]:
    """The names of a model's fields marked `Sensitive`."""
    return tuple(
        name
        for name, info in model.model_fields.items()
        if any(isinstance(marker, Sensitive) for marker in info.metadata)
    )
