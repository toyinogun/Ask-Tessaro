"""Seatsurfing: offices as locations, desks and rooms as spaces, and bookings."""

from datetime import datetime, time

from tessaro_dataset.dataset import Dataset
from tessaro_dataset.dates import at_local
from tessaro_dataset.derive import email
from tessaro_dataset.exports.base import ExportRecord


class SeatLocation(ExportRecord):
    """An office."""

    id: str
    name: str
    address: str
    timezone: str


class SeatSpace(ExportRecord):
    """A desk or room."""

    id: str
    location_id: str
    name: str
    kind: str
    capacity: int


class SeatBooking(ExportRecord):
    """A booking with its start and end as Amsterdam timestamps."""

    id: str
    space_id: str
    user_email: str
    enter: datetime
    leave: datetime
    status: str


class SeatsurfingExport(ExportRecord):
    """Everything the Seatsurfing seed job writes."""

    locations: tuple[SeatLocation, ...]
    spaces: tuple[SeatSpace, ...]
    bookings: tuple[SeatBooking, ...]


def _clock(value: str) -> time:
    return time.fromisoformat(value)


def export_seatsurfing(dataset: Dataset, include_demo_inputs: bool = False) -> SeatsurfingExport:
    """Locations, spaces and bookings, sorted by ID."""
    people = {e.id: e for e in dataset.seed_employees(include_demo_inputs=include_demo_inputs)}
    return SeatsurfingExport(
        locations=tuple(
            SeatLocation(
                id=o.id,
                name=o.name,
                address=f"{o.street}, {o.postcode} {o.city}",
                timezone=o.timezone,
            )
            for o in sorted(dataset.offices, key=lambda o: o.id)
        ),
        spaces=tuple(
            SeatSpace(
                id=s.id, location_id=s.office_id, name=s.name, kind=s.kind, capacity=s.capacity
            )
            for s in sorted(dataset.spaces, key=lambda s: s.id)
        ),
        bookings=tuple(
            SeatBooking(
                id=b.id,
                space_id=b.space_id,
                user_email=email(people[b.employee_id]),
                enter=at_local(b.date, _clock(b.start)),
                leave=at_local(b.date, _clock(b.end)),
                status=b.status,
            )
            for b in sorted(dataset.bookings, key=lambda b: b.id)
            if b.employee_id in people
        ),
    )
