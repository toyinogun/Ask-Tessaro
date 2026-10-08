"""Expense claims."""

from datetime import date
from typing import Literal

from pydantic import Field

from tessaro_dataset.models.common import Amount, DayField, EmployeeId, Record, Text

ClaimStatus = Literal["draft", "submitted", "approved", "paid", "rejected"]


class ExpenseClaim(Record):
    """An expense claim in EUR and the dates its state requires."""

    id: Text = Field(pattern=r"^EXP-\d{4}$")
    employee_id: EmployeeId
    approver_id: EmployeeId
    description: Text
    amount: Amount
    status: ClaimStatus
    submitted_on: DayField | None = None
    approved_on: DayField | None = None
    expected_payment_date: DayField | None = None
    paid_on: DayField | None = None

    def missing_fields(self) -> tuple[str, ...]:
        """The fields this claim's state requires but leaves empty."""
        required: dict[str, date | None] = {}
        if self.status in ("submitted", "approved", "paid", "rejected"):
            required["submitted_on"] = self.submitted_on
        if self.status in ("approved", "paid"):
            required["approved_on"] = self.approved_on
            required["expected_payment_date"] = self.expected_payment_date
        if self.status == "paid":
            required["paid_on"] = self.paid_on
        return tuple(name for name, value in required.items() if value is None)
