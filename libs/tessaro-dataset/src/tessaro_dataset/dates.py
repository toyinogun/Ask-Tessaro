"""The date expression grammar: dates written relative to a demo day anchor.

Pure domain code, no I/O. Day expressions (`@anchor+3wd`, `@next_monday`) give a date,
or 09:00 local in a timestamp field unless they carry a `THH:MM` suffix. Hour and
minute expressions (`@anchor-90m`) are exact elapsed time and only fit timestamp fields.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
DEFAULT_DAY_TIME = time(9, 0)
LEAVER_RUN_TIME = time(17, 30)
DEFAULT_STAND_IN_DURATION = timedelta(minutes=15)

_SUFFIX = r"(?:T(?P<hh>[01]\d|2[0-3]):(?P<mm>[0-5]\d))?"
_DAY_RE = re.compile(
    r"@(?:(?P<next_monday>next_monday)|anchor(?:(?P<sign>[+-])(?P<n>\d+)(?P<unit>wd|d))?)"
    + _SUFFIX
    + r"$"
)
_TIME_RE = re.compile(r"@anchor(?P<sign>[+-])(?P<n>\d+)(?P<unit>h|m)$")
_YEAR_RE = re.compile(r"@anchor_year(?:\+(?P<n>\d+))?$")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}$")


class DateExpressionError(ValueError):
    """A value that is not a valid date expression for the field it sits in."""


@dataclass(frozen=True)
class DateContext:
    """What every expression resolves against: the anchor and the stand in duration."""

    anchor: datetime
    stand_in_duration: timedelta = DEFAULT_STAND_IN_DURATION

    def __post_init__(self) -> None:
        if self.stand_in_duration <= timedelta(0):
            raise ValueError("stand_in_duration must be above 0")
        object.__setattr__(self, "anchor", normalise_anchor(self.anchor))


def normalise_anchor(anchor: datetime) -> datetime:
    """Return the anchor in Amsterdam time, truncated to the minute; reject naive values."""
    if anchor.tzinfo is None or anchor.utcoffset() is None:
        raise ValueError("the anchor needs a time zone offset")
    local = anchor.astimezone(AMSTERDAM)
    return local.replace(second=0, microsecond=0)


def default_anchor() -> datetime:
    """The anchor used when none is pinned: now, in Amsterdam, to the minute."""
    return normalise_anchor(datetime.now(AMSTERDAM))


def anchor_warnings(anchor: datetime) -> tuple[str, ...]:
    """Warnings for an anchor that gives odd demo results, without failing the load."""
    local = normalise_anchor(anchor)
    warnings: list[str] = []
    if not is_working_day(local.date()):
        warnings.append(
            f"the anchor {local:%A %Y-%m-%d} is a weekend day: the leaver's last day and "
            "other 'today' dates fall on a weekend"
        )
    if local.time() > LEAVER_RUN_TIME:
        warnings.append(
            f"the anchor time {local:%H:%M} is after 17:30: the leaver's 17:30 run has "
            "already passed today"
        )
    return tuple(warnings)


def is_working_day(day: date) -> bool:
    """Monday to Friday; the dataset has no holiday calendar."""
    return day.weekday() < 5


def add_working_days(day: date, count: int) -> date:
    """Step `count` working days forward (or back when negative) from `day`."""
    step = 1 if count >= 0 else -1
    remaining = abs(count)
    current = day
    while remaining:
        current += timedelta(days=step)
        if is_working_day(current):
            remaining -= 1
    return current


def working_days_between(start: date, end: date) -> int:
    """Count the working days from `start` to `end`, both included (0 when end < start)."""
    total = 0
    current = start
    while current <= end:
        total += is_working_day(current)
        current += timedelta(days=1)
    return total


def next_monday(day: date) -> date:
    """The first Monday strictly after `day`."""
    return day + timedelta(days=7 - day.weekday())


def at_local(day: date, at: time) -> datetime:
    """A day and a wall clock time in Amsterdam."""
    return datetime.combine(day, at, tzinfo=AMSTERDAM)


def _exact(anchor: datetime, delta: timedelta) -> datetime:
    """Add elapsed time through UTC so a daylight saving change does not skew it."""
    return (anchor.astimezone(UTC) + delta).astimezone(AMSTERDAM)


def _parse_day(expr: str, ctx: DateContext) -> tuple[date, time | None] | None:
    match = _DAY_RE.match(expr)
    if match is None:
        return None
    base = ctx.anchor.date()
    if match["next_monday"]:
        day = next_monday(base)
    elif match["sign"] is None:
        day = base
    else:
        n = int(match["n"]) * (1 if match["sign"] == "+" else -1)
        day = add_working_days(base, n) if match["unit"] == "wd" else base + timedelta(days=n)
    suffix = time(int(match["hh"]), int(match["mm"])) if match["hh"] else None
    return day, suffix


def _parse_time(expr: str, ctx: DateContext) -> datetime | None:
    if expr == "@standin_end":
        return _exact(ctx.anchor, ctx.stand_in_duration)
    match = _TIME_RE.match(expr)
    if match is None:
        return None
    n = int(match["n"]) * (1 if match["sign"] == "+" else -1)
    delta = timedelta(hours=n) if match["unit"] == "h" else timedelta(minutes=n)
    return _exact(ctx.anchor, delta)


def _parse_iso(expr: str) -> date | datetime | None:
    try:
        if _ISO_DATE_RE.match(expr):
            return date.fromisoformat(expr)
        parsed = datetime.fromisoformat(expr)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=AMSTERDAM)
    return parsed.astimezone(AMSTERDAM)


def _require_text(value: object) -> str:
    if not isinstance(value, str):
        raise DateExpressionError(
            f"expected a date expression string, got {type(value).__name__} {value!r} "
            "(quote the value in YAML)"
        )
    return value


def resolve(expr: object, ctx: DateContext) -> date | datetime:
    """Resolve an expression to its natural type: a date, or a timestamp when it has a time."""
    if isinstance(expr, datetime):
        return expr.astimezone(AMSTERDAM)
    if isinstance(expr, date):
        return expr
    text = _require_text(expr)
    day = _parse_day(text, ctx)
    if day is not None:
        return day[0] if day[1] is None else at_local(day[0], day[1])
    exact = _parse_time(text, ctx)
    if exact is not None:
        return exact
    iso = _parse_iso(text)
    if iso is not None:
        return iso
    raise DateExpressionError(f"unknown date expression {text!r}")


def resolve_date(expr: object, ctx: DateContext) -> date:
    """Resolve an expression in a date field; time expressions and suffixes are problems."""
    if isinstance(expr, datetime):
        raise DateExpressionError(f"expected a date, got the timestamp {expr.isoformat()}")
    if isinstance(expr, date):
        return expr
    text = _require_text(expr)
    day = _parse_day(text, ctx)
    if day is not None:
        if day[1] is not None:
            raise DateExpressionError(f"{text!r} has a time suffix but this is a date field")
        return day[0]
    if _parse_time(text, ctx) is not None:
        raise DateExpressionError(f"{text!r} is a time expression but this is a date field")
    iso = _parse_iso(text)
    if isinstance(iso, datetime):
        raise DateExpressionError(f"{text!r} is a timestamp but this is a date field")
    if iso is not None:
        return iso
    raise DateExpressionError(f"unknown date expression {text!r}")


def resolve_timestamp(expr: object, ctx: DateContext) -> datetime:
    """Resolve an expression in a timestamp field; a bare day means 09:00 local."""
    if isinstance(expr, datetime):
        return expr.astimezone(AMSTERDAM)
    if isinstance(expr, date):
        return at_local(expr, DEFAULT_DAY_TIME)
    text = _require_text(expr)
    day = _parse_day(text, ctx)
    if day is not None:
        return at_local(day[0], day[1] or DEFAULT_DAY_TIME)
    exact = _parse_time(text, ctx)
    if exact is not None:
        return exact
    iso = _parse_iso(text)
    if isinstance(iso, datetime):
        return iso
    if iso is not None:
        return at_local(iso, DEFAULT_DAY_TIME)
    raise DateExpressionError(f"unknown date expression {text!r}")


def resolve_year(expr: object, ctx: DateContext) -> int:
    """Resolve an allocation year: `@anchor_year`, `@anchor_year+N`, or a plain year."""
    if isinstance(expr, int) and not isinstance(expr, bool):
        return expr
    text = _require_text(expr)
    match = _YEAR_RE.match(text)
    if match is None:
        raise DateExpressionError(f"unknown year expression {text!r}")
    return ctx.anchor.year + int(match["n"] or 0)
