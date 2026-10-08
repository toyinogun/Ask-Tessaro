"""Remaining leave, derived from allocations and approved applications (never stored)."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from tessaro_dataset.dates import working_days_between
from tessaro_dataset.models import LeaveAllocation, LeaveApplication, LeaveType

BALANCE_LEAVE_TYPE: LeaveType = "vacation"


@dataclass(frozen=True)
class LeaveBalance:
    """Remaining days after approved leave, and days still waiting for a decision."""

    remaining: int
    pending: int


def days_in_year(application: LeaveApplication, year: int) -> int:
    """Working days of an application that fall in `year` (a span over 31 December splits)."""
    start = max(application.from_date, date(year, 1, 1))
    end = min(application.to_date, date(year, 12, 31))
    return working_days_between(start, end)


def leave_balance(
    allocations: Iterable[LeaveAllocation],
    applications: Iterable[LeaveApplication],
    employee_id: str,
    leave_type: LeaveType,
    year: int,
) -> LeaveBalance:
    """Allocation minus approved working days in `year`; open applications count as pending.

    Only vacation has a balance. Raises `ValueError` for other leave types and for a year
    with no allocation.
    """
    if leave_type != BALANCE_LEAVE_TYPE:
        raise ValueError(f"{leave_type} leave has no allocation and no balance")
    allocated = [a.days for a in allocations if a.employee_id == employee_id and a.year == year]
    if not allocated:
        raise ValueError(f"{employee_id} has no {leave_type} allocation for {year}")
    own = [a for a in applications if a.employee_id == employee_id and a.leave_type == leave_type]
    used = sum(days_in_year(a, year) for a in own if a.status == "approved")
    pending = sum(days_in_year(a, year) for a in own if a.status == "open")
    return LeaveBalance(remaining=sum(allocated) - used, pending=pending)
