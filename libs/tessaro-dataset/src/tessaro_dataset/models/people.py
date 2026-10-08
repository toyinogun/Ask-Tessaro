"""Employees and stand in arrangements."""

from typing import Literal

from pydantic import Field

from tessaro_dataset.models.common import (
    DayField,
    EmployeeId,
    Flag,
    Record,
    Slug,
    Text,
    TimestampField,
    Trap,
)
from tessaro_dataset.registry import DemoRole

PHONE_PATTERN = r"^\+31 6 1234 5\d{3}$"


class HomeAddress(Record):
    """An invented home address."""

    street: Text
    postcode: Text = Field(pattern=r"^\d{4} [A-Z]{2}$")
    city: Text


class PendingMove(Record):
    """A team change applied on camera by a demo action, never seeded."""

    to_team_id: Slug
    move_date: DayField


class Employee(Record):
    """A person at Tessaro: a team member, the CEO or a demo input joiner."""

    id: EmployeeId
    first_name: Text
    last_name: Text
    tussenvoegsel: Text | None = None
    title: Text
    team_id: Slug | None = None
    office_id: Slug
    phone: Text = Field(pattern=PHONE_PATTERN)
    home_address: HomeAddress
    account_number: Text = Field(pattern=r"^\d{10}$")
    joining_date: DayField
    relieving_date: DayField | None = None
    pending_move: PendingMove | None = None
    it_agent: Flag = False
    it_approver: Flag = False
    is_ceo: Flag = False
    load: Literal["seed", "demo_input"] = "seed"
    demo_role: DemoRole | None = None
    email_override: Text | None = None
    traps: tuple[Trap, ...] = ()

    @property
    def is_seed(self) -> bool:
        """True for records in the initial seed; False for the joiners created on camera."""
        return self.load == "seed"


class StandIn(Record):
    """A time boxed stand in arrangement: someone approves for a team they do not manage."""

    id: Slug
    user_id: EmployeeId
    team_id: Slug
    valid_from: TimestampField
    valid_until: TimestampField
