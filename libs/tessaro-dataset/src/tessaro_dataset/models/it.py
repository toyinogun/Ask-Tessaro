"""Devices and tickets."""

from typing import Literal

from pydantic import Field

from tessaro_dataset.models.common import (
    Count,
    EmployeeId,
    Flag,
    Record,
    Slug,
    Text,
    TimestampField,
    Trap,
)
from tessaro_dataset.models.organisation import TicketQueue

DeviceStatus = Literal["ready_to_deploy", "deployed", "in_repair", "archived"]
TicketState = Literal["new", "open", "pending_reminder", "closed"]
AssetTag = Text


class Device(Record):
    """A laptop, assigned or in stock."""

    asset_tag: AssetTag = Field(pattern=r"^TES-LT-\d{4}$")
    model: Text
    laptop_profile: Slug
    serial: Text
    status: DeviceStatus
    assigned_to: EmployeeId | None = None

    def state_problem(self) -> str | None:
        """Why this device's status and assignment disagree, if they do."""
        if self.status in ("deployed", "in_repair") and self.assigned_to is None:
            return f"a {self.status} device needs assigned_to"
        if self.status == "ready_to_deploy" and self.assigned_to is not None:
            return "a ready_to_deploy device must not be assigned"
        return None


class TicketArticle(Record):
    """One message on a ticket; internal notes are hidden from the customer."""

    seq: Count = Field(ge=1)
    author_id: EmployeeId
    at: TimestampField
    body: Text
    internal: Flag = False
    traps: tuple[Trap, ...] = ()


class Ticket(Record):
    """A ticket in one of the four team queues."""

    id: Text = Field(pattern=r"^T-\d{4}$")
    queue: TicketQueue
    title: Text
    customer_id: EmployeeId
    owner_id: EmployeeId | None = None
    state: TicketState
    priority: Literal["low", "normal", "high"]
    asset_tag: AssetTag | None = None
    created_at: TimestampField
    pending_until: TimestampField | None = None
    articles: tuple[TicketArticle, ...] = Field(min_length=1)
