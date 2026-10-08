"""Cross record checks over a parsed dataset; every check yields problems, none stops early."""

from collections import Counter
from collections.abc import Callable, Hashable, Iterable, Iterator

from tessaro_dataset.balances import BALANCE_LEAVE_TYPE, leave_balance
from tessaro_dataset.dataset import Dataset
from tessaro_dataset.dates import add_working_days, is_working_day
from tessaro_dataset.derive import email
from tessaro_dataset.errors import Problem
from tessaro_dataset.facts import CLAIM_PAYMENT_MIN_WORKING_DAYS, check_facts
from tessaro_dataset.minimums import check_minimums
from tessaro_dataset.models import TRAPS
from tessaro_dataset.registry import DEMO_CAST, LAPTOP_PROFILES, known_groups

Check = Callable[[Dataset], Iterator[Problem]]


def _duplicates[T](
    file: str, items: Iterable[T], key: Callable[[T], Hashable], what: str
) -> Iterator[Problem]:
    counts = Counter(key(item) for item in items)
    for value, count in sorted(counts.items(), key=lambda kv: str(kv[0])):
        if count > 1:
            yield Problem(file, str(value), f"duplicate {what} ({count} records)")


def check_unique(ds: Dataset) -> Iterator[Problem]:
    """Every ID, email, serial and allocation key is unique."""
    yield from _duplicates("company.yaml", ds.offices, lambda r: r.id, "office id")
    yield from _duplicates("company.yaml", ds.spaces, lambda r: r.id, "space id")
    yield from _duplicates("company.yaml", ds.spaces, lambda r: (r.office_id, r.name), "name")
    yield from _duplicates("company.yaml", ds.teams, lambda r: r.id, "team id")
    yield from _duplicates("employees.yaml", ds.employees, lambda r: r.id, "employee id")
    yield from _duplicates("employees.yaml", ds.employees, email, "email")
    yield from _duplicates("standins.yaml", ds.standins, lambda r: r.id, "stand in id")
    yield from _duplicates(
        "leave.yaml", ds.allocations, lambda r: f"{r.employee_id}/{r.year}", "allocation"
    )
    yield from _duplicates("leave.yaml", ds.applications, lambda r: r.id, "application id")
    yield from _duplicates("claims.yaml", ds.claims, lambda r: r.id, "claim id")
    yield from _duplicates("devices.yaml", ds.devices, lambda r: r.asset_tag, "asset tag")
    yield from _duplicates("devices.yaml", ds.devices, lambda r: r.serial, "serial")
    yield from _duplicates("tickets.yaml", ds.tickets, lambda r: r.id, "ticket id")
    yield from _duplicates("bookings.yaml", ds.bookings, lambda r: r.id, "booking id")
    yield from _duplicates("channels.yaml", ds.channels, lambda r: r.name, "channel")
    yield from _duplicates("bundles", ds.bundles, lambda r: r.team, "bundle team")


def _employee_refs(ds: Dataset) -> Iterator[tuple[str, str, str, str]]:
    """Every (file, record, field, employee ID) reference outside employees.yaml."""
    for t in ds.teams:
        yield "company.yaml", t.id, "manager_id", t.manager_id
        for advisor in t.hr_advisor_ids:
            yield "company.yaml", t.id, "hr_advisor_ids", advisor
    for s in ds.standins:
        yield "standins.yaml", s.id, "user_id", s.user_id
    for a in ds.allocations:
        yield "leave.yaml", f"{a.employee_id}/{a.year}", "employee_id", a.employee_id
    for app in ds.applications:
        yield "leave.yaml", app.id, "employee_id", app.employee_id
    for c in ds.claims:
        yield "claims.yaml", c.id, "employee_id", c.employee_id
        yield "claims.yaml", c.id, "approver_id", c.approver_id
    for d in ds.devices:
        if d.assigned_to:
            yield "devices.yaml", d.asset_tag, "assigned_to", d.assigned_to
    for tk in ds.tickets:
        yield "tickets.yaml", tk.id, "customer_id", tk.customer_id
        if tk.owner_id:
            yield "tickets.yaml", tk.id, "owner_id", tk.owner_id
        for art in tk.articles:
            yield "tickets.yaml", tk.id, f"articles.{art.seq}.author_id", art.author_id
    for b in ds.bookings:
        yield "bookings.yaml", b.id, "employee_id", b.employee_id
    for ch in ds.channels:
        for member in ch.extra_member_ids:
            yield "channels.yaml", ch.name, "extra_member_ids", member


def check_employee_refs(ds: Dataset) -> Iterator[Problem]:
    """References to employees resolve, and seed records never point at a demo input joiner."""
    for file, record, field, employee_id in _employee_refs(ds):
        target = ds.employees_by_id.get(employee_id)
        if target is None:
            yield Problem(file, record, f"{field} names unknown employee {employee_id}")
        elif not target.is_seed:
            yield Problem(file, record, f"{field} names demo input joiner {employee_id}")


def check_other_refs(ds: Dataset) -> Iterator[Problem]:
    """References to offices, teams, spaces and devices resolve."""
    offices = {o.id for o in ds.offices}
    spaces = {s.id for s in ds.spaces}
    devices = {d.asset_tag for d in ds.devices}
    for s in ds.spaces:
        if s.office_id not in offices:
            yield Problem("company.yaml", s.id, f"office_id names unknown office {s.office_id}")
    for e in ds.employees:
        if e.team_id is not None and e.team_id not in ds.teams_by_id:
            yield Problem("employees.yaml", e.id, f"team_id names unknown team {e.team_id}")
        if e.office_id not in offices:
            yield Problem("employees.yaml", e.id, f"office_id names unknown office {e.office_id}")
        if e.pending_move and e.pending_move.to_team_id not in ds.teams_by_id:
            yield Problem("employees.yaml", e.id, "pending_move names an unknown team")
    for st in ds.standins:
        if st.team_id not in ds.teams_by_id:
            yield Problem("standins.yaml", st.id, f"team_id names unknown team {st.team_id}")
    for tk in ds.tickets:
        if tk.asset_tag and tk.asset_tag not in devices:
            yield Problem("tickets.yaml", tk.id, f"asset_tag names unknown device {tk.asset_tag}")
    for b in ds.bookings:
        if b.space_id not in spaces:
            yield Problem("bookings.yaml", b.id, f"space_id names unknown space {b.space_id}")


def check_people(ds: Dataset) -> Iterator[Problem]:
    """One CEO outside the teams, managers inside their team, joiners match their load."""
    ceos = [e for e in ds.employees if e.is_ceo]
    if len(ceos) != 1:
        yield Problem("employees.yaml", "-", f"expected exactly one CEO, found {len(ceos)}")
    for e in ds.employees:
        if e.is_ceo != (e.team_id is None):
            yield Problem("employees.yaml", e.id, "the CEO, and only the CEO, has no team_id")
        joiner = e.joining_date > ds.anchor.date()
        if joiner != (e.load == "demo_input"):
            yield Problem(
                "employees.yaml",
                e.id,
                "load is demo_input exactly when joining_date is after the anchor",
            )
    for t in ds.teams:
        manager = ds.employees_by_id.get(t.manager_id)
        if manager is not None and manager.team_id != t.id:
            yield Problem("company.yaml", t.id, f"manager {t.manager_id} is not in the team")
    if not any(e.it_approver for e in ds.employees):
        yield Problem("employees.yaml", "-", "no employee has it_approver set")
    yield from _lifecycle_counts(ds)


def _lifecycle_counts(ds: Dataset) -> Iterator[Problem]:
    counts = {
        "joiners": (sum(e.load == "demo_input" for e in ds.employees), 2),
        "leavers": (sum(e.relieving_date is not None for e in ds.employees), 1),
        "movers": (sum(e.pending_move is not None for e in ds.employees), 1),
    }
    for what, (found, expected) in counts.items():
        if found != expected:
            yield Problem("employees.yaml", "-", f"expected {expected} {what}, found {found}")


def check_standins(ds: Dataset) -> Iterator[Problem]:
    """A stand in is never the team's manager and its window runs forwards."""
    for s in ds.standins:
        team = ds.teams_by_id.get(s.team_id)
        if team is not None and team.manager_id == s.user_id:
            yield Problem("standins.yaml", s.id, "the stand in is the team's manager")
        if s.valid_from >= s.valid_until:
            yield Problem("standins.yaml", s.id, "valid_from must be before valid_until")


def check_leave(ds: Dataset) -> Iterator[Problem]:
    """Leave dates run forwards on working days and no balance goes below zero."""
    for a in ds.applications:
        if a.from_date > a.to_date:
            yield Problem("leave.yaml", a.id, "from_date is after to_date")
        for name, day in (("from_date", a.from_date), ("to_date", a.to_date)):
            if not is_working_day(day):
                yield Problem("leave.yaml", a.id, f"{name} {day} is on a weekend")
    for alloc in ds.allocations:
        balance = leave_balance(
            ds.allocations, ds.applications, alloc.employee_id, BALANCE_LEAVE_TYPE, alloc.year
        )
        if balance.remaining < 0:
            yield Problem(
                "leave.yaml",
                f"{alloc.employee_id}/{alloc.year}",
                f"leave balance is below zero ({balance.remaining})",
            )


def check_claims(ds: Dataset) -> Iterator[Problem]:
    """Each claim has its state's dates, a separate approver and a valid payment date."""
    for c in ds.claims:
        missing = c.missing_fields()
        if missing:
            yield Problem("claims.yaml", c.id, f"state {c.status} needs {', '.join(missing)}")
        if c.approver_id == c.employee_id:
            yield Problem("claims.yaml", c.id, "the approver is the claimant")
        if c.approved_on and c.expected_payment_date:
            earliest = add_working_days(c.approved_on, CLAIM_PAYMENT_MIN_WORKING_DAYS)
            if c.expected_payment_date < earliest:
                yield Problem(
                    "claims.yaml",
                    c.id,
                    f"expected_payment_date must be on or after {earliest}",
                )


def check_devices(ds: Dataset) -> Iterator[Problem]:
    """Device status and assignment agree and every profile is known."""
    for d in ds.devices:
        problem = d.state_problem()
        if problem:
            yield Problem("devices.yaml", d.asset_tag, problem)
        if d.laptop_profile not in LAPTOP_PROFILES:
            yield Problem("devices.yaml", d.asset_tag, f"unknown profile {d.laptop_profile}")


def check_tickets(ds: Dataset) -> Iterator[Problem]:
    """Ticket states, owners and article times are consistent."""
    devices = {d.asset_tag: d for d in ds.devices}
    queue_teams = {t.ticket_queue: t.id for t in ds.teams if t.ticket_queue}
    for tk in ds.tickets:
        if tk.state == "pending_reminder" and tk.pending_until is None:
            yield Problem("tickets.yaml", tk.id, "state pending_reminder needs pending_until")
        device = devices.get(tk.asset_tag or "")
        if device is not None and device.status == "in_repair" and tk.state == "closed":
            yield Problem("tickets.yaml", tk.id, "closed while its device is in_repair")
        owner = ds.employees_by_id.get(tk.owner_id or "")
        if owner is not None:
            allowed = (
                owner.it_agent if tk.queue == "it" else owner.team_id == queue_teams.get(tk.queue)
            )
            if not allowed:
                yield Problem("tickets.yaml", tk.id, f"owner {owner.id} cannot own {tk.queue}")
        previous = tk.created_at
        for art in tk.articles:
            if art.at < previous:
                yield Problem("tickets.yaml", tk.id, f"article {art.seq} goes back in time")
            previous = max(previous, art.at)


def check_bookings(ds: Dataset) -> Iterator[Problem]:
    """Bookings sit on working days, run forwards and never overlap on one space."""
    for b in ds.bookings:
        if not is_working_day(b.date):
            yield Problem("bookings.yaml", b.id, f"date {b.date} is on a weekend")
        if b.start >= b.end:
            yield Problem("bookings.yaml", b.id, "start must be before end")
    booked = sorted(
        (b for b in ds.bookings if b.status == "booked"), key=lambda b: (b.space_id, b.date, b.id)
    )
    for i, first in enumerate(booked):
        for second in booked[i + 1 :]:
            same_slot = (first.space_id, first.date) == (second.space_id, second.date)
            if same_slot and first.start < second.end and second.start < first.end:
                yield Problem("bookings.yaml", second.id, f"overlaps booking {first.id}")


def check_bundles(ds: Dataset) -> Iterator[Problem]:
    """Every team has a bundle and every name in a bundle resolves."""
    groups = known_groups(frozenset(ds.teams_by_id))
    channels = {c.name for c in ds.channels}
    offices = {o.id for o in ds.offices}
    for team in ds.teams:
        if team.id not in ds.bundles_by_team:
            yield Problem("bundles", team.id, "team has no access bundle")
    for b in ds.bundles:
        file = f"bundles/{b.team}.yaml"
        if b.team not in ds.teams_by_id:
            yield Problem(file, b.team, "bundle for an unknown team")
        for g in (*b.authentik_groups, *(e.authentik_group for e in b.elevated)):
            if g not in groups:
                yield Problem(file, b.team, f"unknown Authentik group {g}")
        for ch in b.zulip_channels:
            if ch not in channels:
                yield Problem(file, b.team, f"unknown Zulip channel {ch}")
        if b.default_office not in offices:
            yield Problem(file, b.team, f"unknown office {b.default_office}")
        if b.laptop_profile not in LAPTOP_PROFILES:
            yield Problem(file, b.team, f"unknown laptop profile {b.laptop_profile}")


def check_traps(ds: Dataset) -> Iterator[Problem]:
    """Each trap tag is used by exactly one record."""
    tagged = (
        *(e.traps for e in ds.employees),
        *(a.traps for a in ds.applications),
        *(art.traps for t in ds.tickets for art in t.articles),
    )
    used = Counter(trap for traps in tagged for trap in traps)
    for trap in TRAPS:
        if used[trap] != 1:
            yield Problem("traps", trap, f"trap must be used exactly once, found {used[trap]}")


def check_cast(ds: Dataset) -> Iterator[Problem]:
    """Each demo role is held by its fixed ID and by no one else."""
    for role, employee_id in DEMO_CAST.items():
        holders = [e.id for e in ds.employees if e.demo_role == role]
        if holders != [employee_id]:
            yield Problem(
                "employees.yaml",
                employee_id,
                f"demo role {role} must be held by exactly "
                f"{employee_id}, found {holders or 'none'}",
            )


def check_pages(ds: Dataset) -> Iterator[Problem]:
    """Each handbook page has a known owning team."""
    for page in ds.pages:
        if page.owner_team not in ds.teams_by_id:
            yield Problem(f"handbook/{page.slug}.md", page.slug, "owner_team is unknown")


CHECKS: tuple[Check, ...] = (
    check_unique,
    check_employee_refs,
    check_other_refs,
    check_people,
    check_standins,
    check_leave,
    check_claims,
    check_devices,
    check_tickets,
    check_bookings,
    check_bundles,
    check_traps,
    check_cast,
    check_pages,
    check_minimums,
    check_facts,
)


def check(ds: Dataset) -> list[Problem]:
    """Run every cross record check and return all problems found."""
    return [problem for run in CHECKS for problem in run(ds)]
