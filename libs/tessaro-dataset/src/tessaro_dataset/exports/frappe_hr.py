"""Frappe HR: departments, employees, vacation allocations and leave applications.

The system of record, so it is the one export that keeps the sensitive leave `reason`.
The leaver's relieving date and the mover's change are held back (see `demo_actions`).
"""

from datetime import date

from tessaro_dataset.balances import BALANCE_LEAVE_TYPE
from tessaro_dataset.dataset import Dataset
from tessaro_dataset.dates import working_days_between
from tessaro_dataset.derive import display_name, email, iban, reports_to
from tessaro_dataset.exports.base import ExportRecord
from tessaro_dataset.models import Employee


class FrappeDepartment(ExportRecord):
    """A department, one per team."""

    department_id: str
    department_name: str


class FrappeEmployee(ExportRecord):
    """An Employee doctype record in its seeded ("before") state."""

    employee: str
    first_name: str
    middle_name: str | None
    last_name: str
    employee_name: str
    designation: str
    department: str | None
    branch: str
    date_of_joining: date
    relieving_date: date | None
    reports_to: str | None
    company_email: str
    cell_number: str
    current_address: str
    bank_ac_no: str
    status: str


class FrappeLeaveAllocation(ExportRecord):
    """Vacation days allocated for one year."""

    employee: str
    leave_type: str
    from_date: date
    to_date: date
    new_leaves_allocated: int


class FrappeLeaveApplication(ExportRecord):
    """A leave application; `reason` is sensitive and stays in this export only."""

    name: str
    employee: str
    leave_type: str
    from_date: date
    to_date: date
    total_leave_days: int
    status: str
    reason: str | None


class FrappeHrExport(ExportRecord):
    """Everything the Frappe HR seed job writes."""

    departments: tuple[FrappeDepartment, ...]
    employees: tuple[FrappeEmployee, ...]
    leave_allocations: tuple[FrappeLeaveAllocation, ...]
    leave_applications: tuple[FrappeLeaveApplication, ...]


def employee_record(dataset: Dataset, employee: Employee) -> FrappeEmployee:
    """One employee as seeded: no relieving date and the current team, whatever is pending."""
    address = employee.home_address
    return FrappeEmployee(
        employee=employee.id,
        first_name=employee.first_name,
        middle_name=employee.tussenvoegsel,
        last_name=employee.last_name,
        employee_name=display_name(employee),
        designation=employee.title,
        department=employee.team_id,
        branch=employee.office_id,
        date_of_joining=employee.joining_date,
        relieving_date=None,
        reports_to=reports_to(dataset, employee),
        company_email=email(employee),
        cell_number=employee.phone,
        current_address=f"{address.street}, {address.postcode} {address.city}",
        bank_ac_no=iban(employee.account_number),
        status="Active",
    )


def export_frappe_hr(dataset: Dataset, include_demo_inputs: bool = False) -> FrappeHrExport:
    """The Frappe HR seed, without the demo input joiners unless asked."""
    people = dataset.seed_employees(include_demo_inputs=include_demo_inputs)
    ids = {e.id for e in people}
    return FrappeHrExport(
        departments=tuple(
            FrappeDepartment(department_id=t.id, department_name=t.name)
            for t in sorted(dataset.teams, key=lambda t: t.id)
        ),
        employees=tuple(employee_record(dataset, e) for e in sorted(people, key=lambda e: e.id)),
        leave_allocations=tuple(
            FrappeLeaveAllocation(
                employee=a.employee_id,
                leave_type=BALANCE_LEAVE_TYPE,
                from_date=date(a.year, 1, 1),
                to_date=date(a.year, 12, 31),
                new_leaves_allocated=a.days,
            )
            for a in sorted(dataset.allocations, key=lambda a: (a.employee_id, a.year))
            if a.employee_id in ids
        ),
        leave_applications=tuple(
            FrappeLeaveApplication(
                name=a.id,
                employee=a.employee_id,
                leave_type=a.leave_type,
                from_date=a.from_date,
                to_date=a.to_date,
                total_leave_days=working_days_between(a.from_date, a.to_date),
                status=a.status,
                reason=a.reason,
            )
            for a in sorted(dataset.applications, key=lambda a: a.id)
            if a.employee_id in ids
        ),
    )
