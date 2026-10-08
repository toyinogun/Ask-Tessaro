"""Snipe-IT: users and laptops; a laptop with no assignee is stock."""

from tessaro_dataset.dataset import Dataset
from tessaro_dataset.derive import email
from tessaro_dataset.exports.base import ExportRecord


class SnipeUser(ExportRecord):
    """A Snipe-IT user."""

    employee_num: str
    username: str
    first_name: str
    last_name: str
    email: str


class SnipeAsset(ExportRecord):
    """A laptop and who holds it."""

    asset_tag: str
    model: str
    laptop_profile: str
    serial: str
    status: str
    assigned_to: str | None


class SnipeItExport(ExportRecord):
    """Everything the Snipe-IT seed job writes."""

    users: tuple[SnipeUser, ...]
    assets: tuple[SnipeAsset, ...]


def export_snipeit(dataset: Dataset, include_demo_inputs: bool = False) -> SnipeItExport:
    """Users and assets, sorted by key."""
    people = dataset.seed_employees(include_demo_inputs=include_demo_inputs)
    return SnipeItExport(
        users=tuple(
            SnipeUser(
                employee_num=e.id,
                username=email(e),
                first_name=e.first_name,
                last_name=" ".join(p for p in (e.tussenvoegsel, e.last_name) if p),
                email=email(e),
            )
            for e in sorted(people, key=lambda e: e.id)
        ),
        assets=tuple(
            SnipeAsset(
                asset_tag=d.asset_tag,
                model=d.model,
                laptop_profile=d.laptop_profile,
                serial=d.serial,
                status=d.status,
                assigned_to=d.assigned_to,
            )
            for d in sorted(dataset.devices, key=lambda d: d.asset_tag)
        ),
    )
