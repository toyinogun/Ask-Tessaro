"""ERPNext: expense claims, paid out to the claimant's derived IBAN."""

from datetime import date
from decimal import Decimal

from tessaro_dataset.dataset import Dataset
from tessaro_dataset.derive import iban
from tessaro_dataset.exports.base import ExportRecord

CURRENCY = "EUR"


class ErpExpenseClaim(ExportRecord):
    """An Expense Claim doctype record."""

    name: str
    employee: str
    expense_approver: str
    description: str
    total_claimed_amount: Decimal
    currency: str
    status: str
    posting_date: date | None
    approval_date: date | None
    expected_payment_date: date | None
    paid_on: date | None
    payable_iban: str


class ErpNextExport(ExportRecord):
    """Everything the ERPNext seed job writes."""

    expense_claims: tuple[ErpExpenseClaim, ...]


def export_erpnext(dataset: Dataset, include_demo_inputs: bool = False) -> ErpNextExport:
    """Expense claims, sorted by ID; claims of demo input joiners only when asked."""
    people = {e.id: e for e in dataset.seed_employees(include_demo_inputs=include_demo_inputs)}
    return ErpNextExport(
        expense_claims=tuple(
            ErpExpenseClaim(
                name=c.id,
                employee=c.employee_id,
                expense_approver=c.approver_id,
                description=c.description,
                total_claimed_amount=c.amount,
                currency=CURRENCY,
                status=c.status,
                posting_date=c.submitted_on,
                approval_date=c.approved_on,
                expected_payment_date=c.expected_payment_date,
                paid_on=c.paid_on,
                payable_iban=iban(people[c.employee_id].account_number),
            )
            for c in sorted(dataset.claims, key=lambda c: c.id)
            if c.employee_id in people
        )
    )
