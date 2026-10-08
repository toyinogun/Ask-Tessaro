"""Leave allocations and applications."""

from typing import Annotated, Literal

from tessaro_dataset.models.common import (
    Count,
    DayField,
    EmployeeId,
    Record,
    Sensitive,
    Slug,
    Text,
    Trap,
    YearField,
)

LeaveType = Literal["vacation", "sick", "parental", "special"]
LeaveStatus = Literal["open", "approved", "rejected", "cancelled"]


class LeaveAllocation(Record):
    """Vacation days allocated to one employee for one year."""

    employee_id: EmployeeId
    year: YearField
    days: Count


class LeaveApplication(Record):
    """A leave request in some state; `reason` is sensitive (health data in a real build)."""

    id: Slug
    employee_id: EmployeeId
    leave_type: LeaveType
    from_date: DayField
    to_date: DayField
    status: LeaveStatus
    reason: Annotated[Text | None, Sensitive("may hold health data")] = None
    traps: tuple[Trap, ...] = ()
