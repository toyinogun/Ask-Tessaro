"""Zammad: users (agents carry their queue), the four queue groups, tickets with articles.

Articles are exported verbatim, including the prompt injection trap, so the safety suite
can prove the agent treats ticket text as data.
"""

from datetime import datetime

from tessaro_dataset.dataset import Dataset
from tessaro_dataset.derive import email
from tessaro_dataset.exports.base import ExportRecord
from tessaro_dataset.models import Employee, Ticket


class ZammadUser(ExportRecord):
    """A Zammad user; agents list the queue groups they work in."""

    login: str
    email: str
    firstname: str
    lastname: str
    employee_id: str
    roles: tuple[str, ...]
    agent_groups: tuple[str, ...]


class ZammadGroup(ExportRecord):
    """A ticket queue."""

    name: str
    team_id: str


class ZammadArticle(ExportRecord):
    """One message on a ticket."""

    seq: int
    author: str
    created_at: datetime
    body: str
    internal: bool


class ZammadTicket(ExportRecord):
    """A ticket with its articles and the time of its latest visible update."""

    number: str
    group: str
    title: str
    customer: str
    owner: str | None
    state: str
    priority: str
    asset_tag: str | None
    created_at: datetime
    pending_until: datetime | None
    latest_update: datetime
    articles: tuple[ZammadArticle, ...]


class ZammadExport(ExportRecord):
    """Everything the Zammad seed job writes."""

    users: tuple[ZammadUser, ...]
    groups: tuple[ZammadGroup, ...]
    tickets: tuple[ZammadTicket, ...]


def _agent_groups(dataset: Dataset, employee: Employee) -> tuple[str, ...]:
    if employee.it_agent:
        return ("it",)
    team = dataset.teams_by_id.get(employee.team_id or "")
    if team is not None and team.ticket_queue and team.ticket_queue != "it":
        return (team.ticket_queue,)
    return ()


def _user(dataset: Dataset, employee: Employee) -> ZammadUser:
    groups = _agent_groups(dataset, employee)
    address = email(employee)
    return ZammadUser(
        login=address,
        email=address,
        firstname=employee.first_name,
        lastname=" ".join(p for p in (employee.tussenvoegsel, employee.last_name) if p),
        employee_id=employee.id,
        roles=("Agent", "Customer") if groups else ("Customer",),
        agent_groups=groups,
    )


def _ticket(ticket: Ticket) -> ZammadTicket:
    visible = [a for a in ticket.articles if not a.internal]
    return ZammadTicket(
        number=ticket.id,
        group=ticket.queue,
        title=ticket.title,
        customer=ticket.customer_id,
        owner=ticket.owner_id,
        state=ticket.state,
        priority=ticket.priority,
        asset_tag=ticket.asset_tag,
        created_at=ticket.created_at,
        pending_until=ticket.pending_until,
        latest_update=max((a.at for a in visible), default=ticket.created_at),
        articles=tuple(
            ZammadArticle(
                seq=a.seq, author=a.author_id, created_at=a.at, body=a.body, internal=a.internal
            )
            for a in ticket.articles
        ),
    )


def export_zammad(dataset: Dataset, include_demo_inputs: bool = False) -> ZammadExport:
    """Users, queue groups and tickets, each sorted by key."""
    people = dataset.seed_employees(include_demo_inputs=include_demo_inputs)
    return ZammadExport(
        users=tuple(_user(dataset, e) for e in sorted(people, key=lambda e: e.id)),
        groups=tuple(
            ZammadGroup(name=t.ticket_queue, team_id=t.id)
            for t in sorted(dataset.teams, key=lambda t: t.ticket_queue or "")
            if t.ticket_queue
        ),
        tickets=tuple(_ticket(t) for t in sorted(dataset.tickets, key=lambda t: t.id)),
    )
