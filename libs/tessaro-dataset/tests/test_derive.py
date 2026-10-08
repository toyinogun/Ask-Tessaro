"""Derived values: groups, reports to, emails, IBANs and leave balances (AC-9, AC-11, AC-14)."""

import re
from datetime import date

import pytest

from tessaro_dataset import Dataset
from tessaro_dataset.balances import days_in_year, leave_balance
from tessaro_dataset.dates import DateContext
from tessaro_dataset.derive import (
    authentik_groups,
    directory_forms,
    email,
    iban,
    iban_is_valid,
    reports_to,
    zulip_channels,
)
from tessaro_dataset.models import LeaveAllocation, LeaveApplication

from .conftest import WEDNESDAY_10

CTX = DateContext(anchor=WEDNESDAY_10)


def test_groups(dataset: Dataset) -> None:
    maria, pieter = dataset.cast("manager"), dataset.cast("stand_in")
    assert {"managers", "team-payments", "staff", "eng"} <= set(authentik_groups(dataset, maria))
    assert "managers" not in authentik_groups(dataset, pieter)
    assert "prod-readonly" not in authentik_groups(dataset, pieter)
    assert authentik_groups(dataset, dataset.ceo) == ("staff",)
    assert "people-advisors" in authentik_groups(dataset, dataset.cast("people_advisor"))
    assert "it-agents" in authentik_groups(dataset, dataset.cast("it_approver"))
    finance = dataset.employee("TES-01024")
    assert "finance-team" in authentik_groups(dataset, finance)
    assert "workplace-team" in authentik_groups(dataset, dataset.employee("TES-01028"))


def test_reports_to(dataset: Dataset) -> None:
    assert reports_to(dataset, dataset.cast("persona")) == dataset.cast("manager").id
    assert reports_to(dataset, dataset.cast("manager")) == dataset.ceo.id
    assert reports_to(dataset, dataset.ceo) is None


def test_channels(dataset: Dataset) -> None:
    assert zulip_channels(dataset, dataset.cast("persona")) == (
        "engineering",
        "general",
        "payments",
    )
    assert zulip_channels(dataset, dataset.ceo) == ("announcements", "general")
    assert "workplace" in zulip_channels(dataset, dataset.cast("leaver"))


def test_identifiers(dataset: Dataset) -> None:
    for e in dataset.employees:
        assert email(e).endswith("@tessaro.example")
        account = iban(e.account_number)
        assert account[4:8] == "XTSR"
        assert iban_is_valid(account)
        assert re.fullmatch(r"\+31 6 1234 5\d{3}", e.phone)
        assert e.home_address.street
    daan = next(e for e in dataset.employees if e.first_name == "Daan")
    assert email(daan) == "daan.dewit@tessaro.example"
    assert {"Daan de Wit", "de Wit", "Wit", "Daan Wit", "@**Daan de Wit**"} <= set(
        directory_forms(daan)
    )
    assert not iban_is_valid("NL00XTSR0000000000")
    overridden = daan.model_copy(update={"email_override": "dw@tessaro.example"})
    assert email(overridden) == "dw@tessaro.example"


def test_balance(dataset: Dataset) -> None:
    persona = dataset.cast("persona")
    balance = dataset.leave_balance(persona.id, "vacation", 2026)
    approved_2026 = sum(
        days_in_year(a, 2026)
        for a in dataset.applications
        if a.employee_id == persona.id and a.status == "approved" and a.leave_type == "vacation"
    )
    assert balance.remaining == 25 - approved_2026
    assert balance.pending == 5
    with pytest.raises(ValueError, match="no allocation"):
        dataset.leave_balance("TES-01003", "sick", 2026)
    with pytest.raises(KeyError):
        dataset.leave_balance("TES-09999", "vacation", 2026)
    with pytest.raises(ValueError, match="no vacation allocation"):
        dataset.leave_balance(persona.id, "vacation", 2031)


def _application(start: str, end: str, status: str = "approved") -> LeaveApplication:
    return LeaveApplication.model_validate(
        {
            "id": "x",
            "employee_id": "TES-01003",
            "leave_type": "vacation",
            "from_date": start,
            "to_date": end,
            "status": status,
        },
        context=CTX,
    )


def test_leave_spanning_new_year_splits() -> None:
    span = _application("2026-12-28", "2027-01-05")
    assert days_in_year(span, 2026) == 4
    assert days_in_year(span, 2027) == 3
    allocations = [
        LeaveAllocation(employee_id="TES-01003", year=2026, days=25),
        LeaveAllocation(employee_id="TES-01003", year=2027, days=25),
    ]
    pending = _application("2027-02-01", "2027-02-02", "open")
    rejected = _application("2027-03-01", "2027-03-05", "rejected")
    apps = [span, pending, rejected]
    assert leave_balance(allocations, apps, "TES-01003", "vacation", 2026).remaining == 21
    after = leave_balance(allocations, apps, "TES-01003", "vacation", 2027)
    assert (after.remaining, after.pending) == (22, 2)
    assert days_in_year(span, 2025) == 0
    assert date(2027, 1, 5) == span.to_date
