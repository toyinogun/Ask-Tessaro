"""The real dataset: counts, demo seeds, traps and the demo cast (AC-1, AC-4, AC-5, AC-15)."""

from collections import Counter
from datetime import date, datetime

import pytest

from tessaro_dataset import AMSTERDAM, Dataset, export_demo_actions, export_openfga, load_dataset
from tessaro_dataset.dates import add_working_days
from tessaro_dataset.registry import DEMO_CAST, PERSONA_CLAIM_ID

from .conftest import PATHS


def test_team_sizes_and_people(dataset: Dataset) -> None:
    seed_members = Counter(e.team_id for e in dataset.employees if e.is_seed and e.team_id)
    assert seed_members == {"payments": 10, "it": 6, "people": 5, "finance": 5, "workplace": 4}
    assert sum(seed_members.values()) == 30
    assert dataset.ceo.team_id is None
    joiners = [e for e in dataset.employees if not e.is_seed]
    assert [(j.id, j.team_id) for j in joiners] == [
        ("TES-01042", "payments"),
        ("TES-01043", "payments"),
    ]


def test_dataset_is_frozen(dataset: Dataset) -> None:
    with pytest.raises(AttributeError):
        dataset.anchor = datetime.now(AMSTERDAM)  # type: ignore[misc]
    with pytest.raises(ValueError, match="frozen"):
        dataset.employees[0].first_name = "X"  # type: ignore[misc]


def test_happy_path_dates(dataset: Dataset) -> None:
    lisa = dataset.cast("joiner")
    assert lisa.joining_date == date(2026, 10, 12)
    actions = export_demo_actions(dataset).actions
    leaver = next(a for a in actions if a.action == "set_relieving_date")
    assert {v.field: v.value for v in leaver.values} == {"relieving_date": "2026-10-07"}
    stand_in = next(
        t
        for t in export_openfga(dataset).tuples
        if t.relation == "stand_in" and t.object == "team:payments"
    )
    assert stand_in.condition is not None
    assert stand_in.condition.context.valid_until == "2026-10-07T10:15:00+02:00"
    assert stand_in.condition.context.valid_from == "2026-10-05T09:00:00+02:00"


def test_traps_are_tagged_once(dataset: Dataset) -> None:
    daan = next(e for e in dataset.employees if "dutch_name" in e.traps)
    assert (daan.first_name, daan.tussenvoegsel, daan.last_name) == ("Daan", "de", "Wit")
    sick = next(a for a in dataset.applications if "sensitive_absence" in a.traps)
    assert sick.leave_type == "sick"
    assert sick.status == "approved"
    assert sick.reason
    assert dataset.employee(sick.employee_id).team_id == "payments"
    ticket, article = next(
        (t, a) for t in dataset.tickets for a in t.articles if "prompt_injection" in a.traps
    )
    assert not article.internal
    assert ticket.customer_id == DEMO_CAST["persona"]
    assert ticket.queue == "it"
    assert "leave" in article.body
    assert "sick notes" in article.body
    assert "IT" in article.body


def test_demo_walk(dataset: Dataset) -> None:
    """Each PRD 14.6 step finds the records it needs in the right state."""
    today = dataset.anchor.date()
    persona, refused = dataset.cast("persona"), dataset.cast("refused_colleague")
    # Step 1: own balance answers, the colleague's is a real record to refuse.
    assert dataset.leave_balance(persona.id, "vacation", today.year).remaining > 0
    assert refused.team_id == persona.team_id == "payments"
    assert dataset.leave_balance(refused.id, "vacation", today.year).remaining >= 0
    # The persona's laptop repair ticket, approved Berlin claim and future bookings.
    repair = next(t for t in dataset.tickets if t.customer_id == persona.id and t.asset_tag)
    laptop = next(d for d in dataset.devices if d.asset_tag == repair.asset_tag)
    assert (laptop.status, laptop.assigned_to, repair.state) == ("in_repair", persona.id, "open")
    claim = next(c for c in dataset.claims if c.id == PERSONA_CLAIM_ID)
    assert (claim.employee_id, claim.status) == (persona.id, "approved")
    assert "Berlin" in claim.description
    future = [b for b in dataset.bookings if b.employee_id == persona.id and b.date > today]
    kinds = {next(s.kind for s in dataset.spaces if s.id == b.space_id) for b in future}
    assert kinds == {"desk", "room"}
    # Steps 3 and 5: Maria approves, Pieter stands in, Sanne and the IT approver exist.
    maria, pieter = dataset.cast("manager"), dataset.cast("stand_in")
    assert dataset.teams_by_id["payments"].manager_id == maria.id
    assert any(s.user_id == pieter.id and s.team_id == "payments" for s in dataset.standins)
    assert dataset.cast("people_advisor").id in dataset.teams_by_id["payments"].hr_advisor_ids
    assert dataset.cast("people_advisor").id in dataset.teams_by_id["it"].hr_advisor_ids
    second = dataset.cast("second_advisor").id
    for team in ("finance", "workplace", "people"):
        assert second in dataset.teams_by_id[team].hr_advisor_ids
    assert dataset.cast("it_approver").it_approver
    # Step 6: Lisa joins next Monday. Step 7: the leaver has something for every step.
    assert dataset.cast("joiner").joining_date.weekday() == 0
    leaver = dataset.cast("leaver")
    assert leaver.relieving_date == today
    assert any(d.assigned_to == leaver.id for d in dataset.devices)
    assert any(c.employee_id == leaver.id and c.status == "submitted" for c in dataset.claims)
    assert any(s.user_id == leaver.id and s.team_id != "payments" for s in dataset.standins)
    mover = dataset.cast("mover")
    assert mover.team_id == "finance"
    assert mover.pending_move is not None
    assert mover.pending_move.move_date == add_working_days(today, 5)
    assert dataset.cast("sick_colleague").id == next(
        a.employee_id for a in dataset.applications if "sensitive_absence" in a.traps
    )


def test_every_cast_role_has_its_fixed_id(dataset: Dataset) -> None:
    for role, employee_id in DEMO_CAST.items():
        assert dataset.employee(employee_id).demo_role == role
    assert dataset.cast("joiner").id == "TES-01042"
    assert dataset.cast("second_joiner").id == "TES-01043"


def test_states_and_handbook(dataset: Dataset) -> None:
    assert len({a.status for a in dataset.applications}) == 4
    assert len({a.leave_type for a in dataset.applications}) == 4
    assert len({c.status for c in dataset.claims}) == 5
    assert len({t.state for t in dataset.tickets}) == 4
    assert len(dataset.pages) == 20
    slugs = {p.slug for p in dataset.pages}
    assert {"working-abroad", "reporting-sick"} <= slugs


def test_weekend_anchor_loads_and_warns() -> None:
    saturday = load_dataset(PATHS, anchor=datetime(2026, 10, 10, 11, 0, tzinfo=AMSTERDAM))
    assert any("weekend" in w for w in saturday.warnings)
