"""The changes made on camera, in demo order, and the IDs that exist only after the demo."""

from typing import Literal

from tessaro_dataset.dataset import Dataset
from tessaro_dataset.derive import reports_to
from tessaro_dataset.exports.base import ExportRecord
from tessaro_dataset.exports.frappe_hr import employee_record
from tessaro_dataset.models import Employee

ActionKind = Literal["create_employee", "set_relieving_date", "move_employee"]


class FieldValue(ExportRecord):
    """One Frappe HR field and the value to set."""

    field: str
    value: str


class DemoAction(ExportRecord):
    """One change to make in Frappe HR during the demo."""

    order: int
    demo_step: int | None
    action: ActionKind
    employee_id: str
    values: tuple[FieldValue, ...]


class DemoActionsExport(ExportRecord):
    """The ordered actions, and every ID the reset must remove."""

    actions: tuple[DemoAction, ...]
    demo_only_ids: tuple[str, ...]


def _values(pairs: dict[str, object]) -> tuple[FieldValue, ...]:
    return tuple(
        FieldValue(field=k, value=str(v)) for k, v in sorted(pairs.items()) if v is not None
    )


def _create(dataset: Dataset, employee: Employee, order: int, step: int) -> DemoAction:
    fields = employee_record(dataset, employee).model_dump(mode="json")
    return DemoAction(
        order=order,
        demo_step=step,
        action="create_employee",
        employee_id=employee.id,
        values=_values(fields),
    )


def _leave(leaver: Employee, order: int) -> DemoAction:
    return DemoAction(
        order=order,
        demo_step=7,
        action="set_relieving_date",
        employee_id=leaver.id,
        values=_values({"relieving_date": leaver.relieving_date}),
    )


def _move(dataset: Dataset, mover: Employee, order: int) -> DemoAction:
    move = mover.pending_move
    if move is None:  # validation guarantees the mover has a pending move
        raise ValueError(f"{mover.id} has no pending move")
    moved = mover.model_copy(update={"team_id": move.to_team_id})
    return DemoAction(
        order=order,
        demo_step=None,
        action="move_employee",
        employee_id=mover.id,
        values=_values(
            {
                "department": move.to_team_id,
                "reports_to": reports_to(dataset, moved),
                "move_date": move.move_date,
            }
        ),
    )


def export_demo_actions(dataset: Dataset, include_demo_inputs: bool = False) -> DemoActionsExport:
    """Create Lisa, create the second joiner, set the leaver's last day, move the mover."""
    actions = (
        _create(dataset, dataset.cast("joiner"), 1, 3),
        _create(dataset, dataset.cast("second_joiner"), 2, 5),
        _leave(dataset.cast("leaver"), 3),
        _move(dataset, dataset.cast("mover"), 4),
    )
    return DemoActionsExport(
        actions=actions,
        demo_only_ids=tuple(sorted(e.id for e in dataset.employees if not e.is_seed)),
    )
