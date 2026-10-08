"""`get_my_leave` 1.0: the caller's vacation balance and upcoming leave (spec 0003 AC-17)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tessaro_contracts.contract import IdentityMode, ToolContract
from tessaro_contracts.scopes import Scope

_CLOSED = ConfigDict(frozen=True, extra="forbid")


class GetMyLeaveInput(BaseModel):
    """No input: the person is always the caller named by the token."""

    model_config = _CLOSED


class LeaveBalance(BaseModel):
    """The year's vacation balance in whole working days. Pending is not deducted."""

    model_config = _CLOSED

    leave_type: Literal["vacation"]
    year: int
    entitled_days: int
    taken_days: int
    pending_days: int
    remaining_days: int


class UpcomingLeave(BaseModel):
    """One open or approved leave application that has not ended yet."""

    model_config = _CLOSED

    application_id: str
    leave_type: Literal["vacation", "sick", "parental", "special"]
    from_date: date
    to_date: date
    status: Literal["open", "approved"]


class GetMyLeaveOutput(BaseModel):
    """The caller's balance (empty when no allocation exists) and upcoming leave."""

    model_config = _CLOSED

    balances: tuple[LeaveBalance, ...] = Field(max_length=1)
    upcoming: tuple[UpcomingLeave, ...] = Field(max_length=50)
    truncated: bool


GET_MY_LEAVE = ToolContract(
    name="get_my_leave",
    version="1.0",
    owner="people-team",
    scope=Scope.HR_READ,
    identity=IdentityMode.SELF,
    authorization="OpenFGA check can_view_own_data on employee:<sub>",
    description=(
        "Your own leave: this year's vacation balance in whole working days (entitled, "
        "taken, pending and remaining, where pending is not yet deducted) and your open "
        "or approved leave that has not ended yet, soonest first, at most 50 entries "
        "(truncated is true when there were more). Takes no input: it always answers "
        "for the person asking."
    ),
    input_model=GetMyLeaveInput,
    output_model=GetMyLeaveOutput,
    never_returns=(
        "reason",
        "absence_reason",
        "medical_note",
        "notes",
        "description",
        "salary",
    ),
)
