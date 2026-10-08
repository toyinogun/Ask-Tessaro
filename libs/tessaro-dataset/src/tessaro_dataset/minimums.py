"""The AC-4 seed minimums: enough of each thing, in the right states, for every demo step."""

from collections.abc import Iterator
from datetime import timedelta

from tessaro_dataset.dataset import Dataset
from tessaro_dataset.dates import add_working_days, next_monday
from tessaro_dataset.errors import Problem
from tessaro_dataset.models import Employee
from tessaro_dataset.registry import DEMO_CAST, DEMO_TEAM

MIN_STOCK_PER_PROFILE = 3
MIN_FREE_DESKS = 2
MIN_TEAM_VACATIONS = 2
VACATION_WINDOW_WORKING_DAYS = 5


def _problem(record: str, message: str) -> Problem:
    return Problem("minimums", record, message)


def _cast(ds: Dataset, role: str) -> Employee | None:
    return ds.employees_by_id.get(DEMO_CAST[role])


def check_states(ds: Dataset) -> Iterator[Problem]:
    """Leave, claims, tickets, devices and bookings each appear in more than one state."""
    kinds: dict[str, set[str]] = {
        "leave applications": {a.status for a in ds.applications},
        "expense claims": {c.status for c in ds.claims},
        "tickets": {t.state for t in ds.tickets},
        "devices": {d.status for d in ds.devices},
        "bookings": {b.status for b in ds.bookings},
    }
    for kind, states in kinds.items():
        if len(states) < 2:
            yield _problem(kind, "needs records in more than one state")


def check_manager_and_stand_in(ds: Dataset) -> Iterator[Problem]:
    """Maria is on approved vacation today and Pieter stands in for her team."""
    manager, stand_in = _cast(ds, "manager"), _cast(ds, "stand_in")
    today = ds.anchor.date()
    if manager is not None and not any(
        a.employee_id == manager.id
        and a.leave_type == "vacation"
        and a.status == "approved"
        and a.from_date <= today <= a.to_date
        for a in ds.applications
    ):
        yield _problem(manager.id, "the manager needs approved vacation covering the anchor date")
    if stand_in is not None and not any(
        s.user_id == stand_in.id and s.team_id == DEMO_TEAM and s.valid_from <= ds.anchor
        for s in ds.standins
    ):
        yield _problem(stand_in.id, f"needs an active stand in arrangement for {DEMO_TEAM}")


def check_leaver(ds: Dataset) -> Iterator[Problem]:
    """The leaver leaves today and holds something for every leaver step to act on."""
    leaver = _cast(ds, "leaver")
    if leaver is None:
        return
    today = ds.anchor.date()
    if leaver.team_id != DEMO_TEAM or leaver.relieving_date != today:
        yield _problem(leaver.id, f"the leaver must be in {DEMO_TEAM} and leave on the anchor date")
    needs = {
        "an assigned laptop": any(d.assigned_to == leaver.id for d in ds.devices),
        "a future booked booking": any(
            b.employee_id == leaver.id and b.status == "booked" and b.date > today
            for b in ds.bookings
        ),
        "an unpaid claim": any(
            c.employee_id == leaver.id and c.status in ("submitted", "approved") for c in ds.claims
        ),
        "a stand in arrangement for another team": any(
            s.user_id == leaver.id and s.team_id != leaver.team_id for s in ds.standins
        ),
    }
    for what, present in needs.items():
        if not present:
            yield _problem(leaver.id, f"the leaver needs {what}")


def check_mover(ds: Dataset) -> Iterator[Problem]:
    """The mover is in Finance with a pending move to the demo team."""
    mover = _cast(ds, "mover")
    if mover is None:
        return
    move = mover.pending_move
    if mover.team_id != "finance" or move is None or move.to_team_id != DEMO_TEAM:
        yield _problem(mover.id, f"the mover must move from finance to {DEMO_TEAM}")


def check_team_vacations(ds: Dataset) -> Iterator[Problem]:
    """At least two demo team members besides the manager are away in the coming week."""
    team = ds.teams_by_id.get(DEMO_TEAM)
    if team is None:
        return
    today = ds.anchor.date()
    window_start = add_working_days(today, 1)
    window_end = add_working_days(today, VACATION_WINDOW_WORKING_DAYS)
    away = {
        a.employee_id
        for a in ds.applications
        if a.leave_type == "vacation"
        and a.status == "approved"
        and a.employee_id != team.manager_id
        and ds.employees_by_id.get(a.employee_id, None) is not None
        and ds.employee(a.employee_id).team_id == DEMO_TEAM
        and a.from_date <= window_end
        and a.to_date >= window_start
    }
    if len(away) < MIN_TEAM_VACATIONS:
        yield _problem(DEMO_TEAM, "needs 2 members (not the manager) on vacation in 5 working days")


def check_stock(ds: Dataset) -> Iterator[Problem]:
    """Three laptops in stock for every profile a bundle names."""
    for profile in sorted({b.laptop_profile for b in ds.bundles}):
        stock = sum(
            d.laptop_profile == profile and d.status == "ready_to_deploy" and d.assigned_to is None
            for d in ds.devices
        )
        if stock < MIN_STOCK_PER_PROFILE:
            yield _problem(profile, f"needs {MIN_STOCK_PER_PROFILE} laptops in stock, has {stock}")


def check_free_desks(ds: Dataset) -> Iterator[Problem]:
    """Two desks free in the demo team's office on each working day of the joiner's week."""
    bundle = ds.bundles_by_team.get(DEMO_TEAM)
    if bundle is None:
        return
    desks = {s.id for s in ds.spaces if s.kind == "desk" and s.office_id == bundle.default_office}
    monday = next_monday(ds.anchor.date())
    for offset in range(5):
        day = monday + timedelta(days=offset)
        taken = {b.space_id for b in ds.bookings if b.status == "booked" and b.date == day}
        if len(desks - taken) < MIN_FREE_DESKS:
            yield _problem(
                str(day), f"needs {MIN_FREE_DESKS} free desks in {bundle.default_office}"
            )


def check_minimums(ds: Dataset) -> Iterator[Problem]:
    """Run every AC-4 minimum check."""
    for run in (
        check_states,
        check_manager_and_stand_in,
        check_leaver,
        check_mover,
        check_team_vacations,
        check_stock,
        check_free_desks,
    ):
        yield from run(ds)
