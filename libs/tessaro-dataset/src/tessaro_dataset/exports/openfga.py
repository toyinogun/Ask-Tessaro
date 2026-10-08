"""OpenFGA: tuples for owners, teams, managers, HR advisors, stand ins and IT approvers.

No `lifecycle_case` tuples: the workflows write those.
"""

from datetime import datetime

from tessaro_dataset.dataset import Dataset
from tessaro_dataset.exports.base import ExportRecord
from tessaro_dataset.models import StandIn
from tessaro_dataset.registry import FGA_ORG

STAND_IN_CONDITION = "within_window"


class WindowContext(ExportRecord):
    """The `within_window` condition context: RFC 3339 timestamps."""

    valid_from: str
    valid_until: str


class FgaCondition(ExportRecord):
    """A named condition on a tuple."""

    name: str
    context: WindowContext


class FgaTuple(ExportRecord):
    """One relationship tuple in fga CLI tuple file shape."""

    user: str
    relation: str
    object: str
    condition: FgaCondition | None = None


class OpenFgaExport(ExportRecord):
    """Every seeded tuple, sorted by object, relation and user."""

    tuples: tuple[FgaTuple, ...]


def rfc3339(value: datetime) -> str:
    """A timestamp with its offset, to the second."""
    return value.isoformat(timespec="seconds")


def stand_in_tuple(user_id: str, team_id: str, start: datetime, end: datetime) -> FgaTuple:
    """A stand in tuple carrying its time window."""
    return FgaTuple(
        user=f"user:{user_id}",
        relation="stand_in",
        object=f"team:{team_id}",
        condition=FgaCondition(
            name=STAND_IN_CONDITION,
            context=WindowContext(valid_from=rfc3339(start), valid_until=rfc3339(end)),
        ),
    )


def _stand_in(s: StandIn) -> FgaTuple:
    return stand_in_tuple(s.user_id, s.team_id, s.valid_from, s.valid_until)


def export_openfga(dataset: Dataset, include_demo_inputs: bool = False) -> OpenFgaExport:
    """Owner, employee team, member, manager, HR advisor, stand in and org IT approver tuples."""
    tuples: list[FgaTuple] = []
    for e in dataset.seed_employees(include_demo_inputs=include_demo_inputs):
        tuples.append(FgaTuple(user=f"user:{e.id}", relation="owner", object=f"employee:{e.id}"))
        if e.it_approver:
            tuples.append(
                FgaTuple(user=f"user:{e.id}", relation="it_approver", object=f"org:{FGA_ORG}")
            )
        if e.team_id:
            tuples.append(
                FgaTuple(user=f"team:{e.team_id}", relation="team", object=f"employee:{e.id}")
            )
            tuples.append(
                FgaTuple(user=f"user:{e.id}", relation="member", object=f"team:{e.team_id}")
            )
    for t in dataset.teams:
        tuples.append(
            FgaTuple(user=f"user:{t.manager_id}", relation="manager", object=f"team:{t.id}")
        )
        tuples.extend(
            FgaTuple(user=f"user:{a}", relation="hr_advisor", object=f"team:{t.id}")
            for a in t.hr_advisor_ids
        )
    tuples.extend(_stand_in(s) for s in dataset.standins)
    return OpenFgaExport(tuples=tuple(sorted(tuples, key=lambda t: (t.object, t.relation, t.user))))
