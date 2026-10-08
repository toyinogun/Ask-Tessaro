"""The loaded, validated company: every record by kind, plus the anchor it was resolved at."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cached_property
from types import MappingProxyType
from typing import TYPE_CHECKING

from tessaro_dataset.balances import LeaveBalance, leave_balance
from tessaro_dataset.models import (
    AccessBundle,
    Booking,
    Channel,
    Device,
    Employee,
    ExpenseClaim,
    HandbookPage,
    LeaveAllocation,
    LeaveApplication,
    LeaveType,
    Office,
    Space,
    StandIn,
    Team,
    Ticket,
)
from tessaro_dataset.registry import DEMO_CAST, DemoRole

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class Dataset:
    """The whole fictional company. Frozen: exporters read it and return new records."""

    anchor: datetime
    stand_in_duration: timedelta
    offices: tuple[Office, ...] = ()
    spaces: tuple[Space, ...] = ()
    teams: tuple[Team, ...] = ()
    employees: tuple[Employee, ...] = ()
    standins: tuple[StandIn, ...] = ()
    allocations: tuple[LeaveAllocation, ...] = ()
    applications: tuple[LeaveApplication, ...] = ()
    claims: tuple[ExpenseClaim, ...] = ()
    devices: tuple[Device, ...] = ()
    tickets: tuple[Ticket, ...] = ()
    bookings: tuple[Booking, ...] = ()
    channels: tuple[Channel, ...] = ()
    pages: tuple[HandbookPage, ...] = ()
    bundles: tuple[AccessBundle, ...] = ()
    warnings: tuple[str, ...] = field(default=())

    @cached_property
    def employees_by_id(self) -> "Mapping[str, Employee]":
        """Employees keyed by ID."""
        return MappingProxyType({e.id: e for e in self.employees})

    @cached_property
    def teams_by_id(self) -> "Mapping[str, Team]":
        """Teams keyed by ID."""
        return MappingProxyType({t.id: t for t in self.teams})

    @cached_property
    def bundles_by_team(self) -> "Mapping[str, AccessBundle]":
        """Access bundles keyed by team ID."""
        return MappingProxyType({b.team: b for b in self.bundles})

    @property
    def ceo(self) -> Employee:
        """The one CEO, outside every team."""
        return next(e for e in self.employees if e.is_ceo)

    def employee(self, employee_id: str) -> Employee:
        """The employee with this ID; `KeyError` when there is none."""
        return self.employees_by_id[employee_id]

    def cast(self, role: DemoRole) -> Employee:
        """The employee holding a demo cast role."""
        return self.employee(DEMO_CAST[role])

    def members(self, team_id: str, *, include_demo_inputs: bool = False) -> tuple[Employee, ...]:
        """A team's members, without the demo input joiners unless asked."""
        return tuple(
            e for e in self.employees if e.team_id == team_id and (include_demo_inputs or e.is_seed)
        )

    def seed_employees(self, *, include_demo_inputs: bool = False) -> tuple[Employee, ...]:
        """Everyone in the initial seed, plus the joiners when asked."""
        return tuple(e for e in self.employees if include_demo_inputs or e.is_seed)

    def leave_balance(self, employee_id: str, leave_type: LeaveType, year: int) -> LeaveBalance:
        """Remaining and pending leave for one employee and year (AC-14)."""
        self.employee(employee_id)
        return leave_balance(self.allocations, self.applications, employee_id, leave_type, year)
