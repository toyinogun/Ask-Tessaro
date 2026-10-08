"""The real dataset validates at about 20 anchors, not only the pinned one (AC-13)."""

from datetime import datetime, timedelta

import pytest

from tessaro_dataset import AMSTERDAM, load_dataset

from .conftest import PATHS

SWEEP = [
    datetime(2026, 10, 5, 10, 0),  # Monday
    datetime(2026, 10, 6, 10, 0),  # Tuesday
    datetime(2026, 10, 7, 10, 0),  # Wednesday
    datetime(2026, 10, 8, 10, 0),  # Thursday
    datetime(2026, 10, 9, 10, 0),  # Friday
    datetime(2026, 10, 10, 10, 0),  # Saturday
    datetime(2026, 10, 11, 10, 0),  # Sunday
    datetime(2026, 12, 31, 9, 0),  # last working day of 2026
    datetime(2027, 1, 1, 9, 0),  # first working day of 2027
    datetime(2027, 12, 31, 16, 0),  # last working day of 2027 (Friday)
    datetime(2028, 1, 3, 9, 0),  # first working day of 2028 (Monday)
    datetime(2026, 3, 29, 3, 30),  # daylight saving starts
    datetime(2026, 10, 25, 2, 30),  # daylight saving ends
    datetime(2026, 10, 7, 18, 0),  # after 17:30
    datetime(2026, 10, 7, 17, 30),  # exactly 17:30
    datetime(2026, 10, 9, 23, 59),  # Friday night
    datetime(2026, 2, 27, 9, 0),  # end of February
    datetime(2028, 2, 29, 9, 0),  # leap day
    datetime(2026, 6, 15, 7, 0),  # early morning
    datetime(2026, 12, 24, 12, 0),  # Christmas Eve
]


@pytest.mark.parametrize("anchor", SWEEP, ids=lambda a: a.strftime("%Y-%m-%d_%H%M"))
def test_dataset_validates_at_anchor(anchor: datetime) -> None:
    dataset = load_dataset(
        PATHS, anchor=anchor.replace(tzinfo=AMSTERDAM), stand_in_duration=timedelta(minutes=15)
    )
    assert len(dataset.employees) == 33
