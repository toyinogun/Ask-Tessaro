"""Date expression grammar (AC-2) and anchor handling (AC-3)."""

from datetime import UTC, date, datetime, timedelta

import pytest

from tessaro_dataset.dates import (
    AMSTERDAM,
    DateContext,
    DateExpressionError,
    anchor_warnings,
    default_anchor,
    is_working_day,
    normalise_anchor,
    resolve,
    resolve_date,
    resolve_timestamp,
    resolve_year,
    working_days_between,
)

FRIDAY = datetime(2026, 10, 9, 10, 0, tzinfo=AMSTERDAM)
SATURDAY = datetime(2026, 10, 10, 10, 0, tzinfo=AMSTERDAM)
WEDNESDAY = datetime(2026, 10, 7, 10, 0, tzinfo=AMSTERDAM)


def ctx(anchor: datetime, minutes: int = 15) -> DateContext:
    return DateContext(anchor=anchor, stand_in_duration=timedelta(minutes=minutes))


@pytest.mark.parametrize(
    ("anchor", "expr", "expected"),
    [
        (FRIDAY, "@anchor", date(2026, 10, 9)),
        (FRIDAY, "@anchor+1wd", date(2026, 10, 12)),
        (SATURDAY, "@anchor+1wd", date(2026, 10, 12)),
        (SATURDAY, "@anchor-1wd", date(2026, 10, 9)),
        (FRIDAY, "@anchor+5wd", date(2026, 10, 16)),
        (FRIDAY, "@anchor-2d", date(2026, 10, 7)),
        (FRIDAY, "@anchor+3d", date(2026, 10, 12)),
        (FRIDAY, "@next_monday", date(2026, 10, 12)),
        (SATURDAY, "@next_monday", date(2026, 10, 12)),
        (datetime(2026, 10, 12, 9, 0, tzinfo=AMSTERDAM), "@next_monday", date(2026, 10, 19)),
        (FRIDAY, "2026-12-24", date(2026, 12, 24)),
    ],
)
def test_day_expressions_resolve_in_date_fields(
    anchor: datetime, expr: str, expected: date
) -> None:
    assert resolve_date(expr, ctx(anchor)) == expected


def test_plain_date_object_passes_through() -> None:
    assert resolve_date(date(2026, 1, 2), ctx(FRIDAY)) == date(2026, 1, 2)


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("@anchor", datetime(2026, 10, 9, 9, 0, tzinfo=AMSTERDAM)),
        ("@anchor-2d", datetime(2026, 10, 7, 9, 0, tzinfo=AMSTERDAM)),
        ("@anchor+2dT14:00", datetime(2026, 10, 11, 14, 0, tzinfo=AMSTERDAM)),
        ("@next_mondayT08:30", datetime(2026, 10, 12, 8, 30, tzinfo=AMSTERDAM)),
        ("@anchor-90m", datetime(2026, 10, 9, 8, 30, tzinfo=AMSTERDAM)),
        ("@anchor+2h", datetime(2026, 10, 9, 12, 0, tzinfo=AMSTERDAM)),
        ("@standin_end", datetime(2026, 10, 9, 10, 15, tzinfo=AMSTERDAM)),
        ("2026-10-01T08:00:00+02:00", datetime(2026, 10, 1, 8, 0, tzinfo=AMSTERDAM)),
        ("2026-10-01T08:00", datetime(2026, 10, 1, 8, 0, tzinfo=AMSTERDAM)),
    ],
)
def test_expressions_resolve_in_timestamp_fields(expr: str, expected: datetime) -> None:
    resolved = resolve_timestamp(expr, ctx(FRIDAY))
    assert resolved == expected
    assert resolved.tzinfo is AMSTERDAM


def test_plain_date_in_timestamp_field_is_nine_oclock() -> None:
    assert resolve_timestamp(date(2026, 10, 1), ctx(FRIDAY)) == datetime(
        2026, 10, 1, 9, 0, tzinfo=AMSTERDAM
    )


def test_stand_in_end_uses_the_duration() -> None:
    assert resolve_timestamp("@standin_end", ctx(FRIDAY, minutes=5)) == datetime(
        2026, 10, 9, 10, 5, tzinfo=AMSTERDAM
    )


def test_hour_expressions_are_exact_across_daylight_saving() -> None:
    # Clocks go back at 03:00 on 25 October 2026: two elapsed hours from 01:30 is 02:30 (CET).
    anchor = datetime(2026, 10, 25, 1, 30, tzinfo=AMSTERDAM)
    resolved = resolve_timestamp("@anchor+2h", ctx(anchor))
    assert resolved.astimezone(UTC) - anchor.astimezone(UTC) == timedelta(hours=2)
    assert resolved.utcoffset() == timedelta(hours=1)


@pytest.mark.parametrize("expr", ["@anchor+15m", "@anchor-1h", "@standin_end"])
def test_time_expressions_in_a_date_field_are_rejected(expr: str) -> None:
    with pytest.raises(DateExpressionError):
        resolve_date(expr, ctx(FRIDAY))


@pytest.mark.parametrize(
    "expr",
    ["@tomorrow", "next monday", "@anchor+1w", "@anchor+1dT25:00", "@anchor+2hT10:00", ""],
)
def test_unknown_expressions_are_rejected(expr: str) -> None:
    with pytest.raises(DateExpressionError):
        resolve_timestamp(expr, ctx(FRIDAY))


def test_suffix_on_a_date_field_is_rejected() -> None:
    with pytest.raises(DateExpressionError):
        resolve_date("@anchorT10:00", ctx(FRIDAY))


def test_non_string_values_are_rejected() -> None:
    with pytest.raises(DateExpressionError):
        resolve_date(630, ctx(FRIDAY))
    with pytest.raises(DateExpressionError):
        resolve_year(True, ctx(FRIDAY))


def test_years() -> None:
    late = datetime(2026, 12, 31, 23, 0, tzinfo=AMSTERDAM)
    assert resolve_year("@anchor_year", ctx(late)) == 2026
    assert resolve_year("@anchor_year+1", ctx(late)) == 2027
    assert resolve_year(2025, ctx(late)) == 2025
    with pytest.raises(DateExpressionError):
        resolve_year("@anchor_year+x", ctx(late))


def test_generic_resolve_picks_the_natural_type() -> None:
    c = ctx(FRIDAY)
    assert resolve("@anchor+1wd", c) == date(2026, 10, 12)
    assert resolve("@anchor+1dT10:00", c) == datetime(2026, 10, 10, 10, 0, tzinfo=AMSTERDAM)
    assert resolve("@anchor+1h", c) == datetime(2026, 10, 9, 11, 0, tzinfo=AMSTERDAM)
    assert resolve(date(2026, 1, 1), c) == date(2026, 1, 1)


def test_normalise_anchor_truncates_and_converts() -> None:
    utc_anchor = datetime.fromisoformat("2026-10-09T08:00:42.5+00:00")
    assert normalise_anchor(utc_anchor) == datetime(2026, 10, 9, 10, 0, tzinfo=AMSTERDAM)
    with pytest.raises(ValueError, match="time zone"):
        normalise_anchor(datetime(2026, 10, 9, 10, 0))


def test_context_rejects_a_non_positive_duration() -> None:
    with pytest.raises(ValueError, match="above 0"):
        DateContext(anchor=FRIDAY, stand_in_duration=timedelta(0))


def test_default_anchor_is_now_in_amsterdam() -> None:
    anchor = default_anchor()
    assert anchor.tzinfo is AMSTERDAM
    assert anchor.second == 0
    assert anchor.microsecond == 0


def test_warnings() -> None:
    assert anchor_warnings(WEDNESDAY) == ()
    assert any("weekend" in w for w in anchor_warnings(SATURDAY))
    late = datetime(2026, 10, 7, 18, 0, tzinfo=AMSTERDAM)
    assert any("17:30" in w for w in anchor_warnings(late))
    assert anchor_warnings(datetime(2026, 10, 7, 17, 30, tzinfo=AMSTERDAM)) == ()


def test_working_day_helpers() -> None:
    assert is_working_day(date(2026, 10, 9))
    assert not is_working_day(date(2026, 10, 10))
    assert working_days_between(date(2026, 10, 9), date(2026, 10, 12)) == 2
    assert working_days_between(date(2026, 10, 12), date(2026, 10, 9)) == 0
