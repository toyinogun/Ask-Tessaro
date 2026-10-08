"""Desk and room bookings."""

from typing import Literal

from tessaro_dataset.models.common import ClockTime, DayField, EmployeeId, Record, Slug


class Booking(Record):
    """A desk or room booking on one working day."""

    id: Slug
    employee_id: EmployeeId
    space_id: Slug
    date: DayField
    start: ClockTime
    end: ClockTime
    status: Literal["booked", "cancelled"]
