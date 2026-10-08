"""Authentik: users with derived groups, and every group a user or bundle needs."""

from tessaro_dataset.dataset import Dataset
from tessaro_dataset.derive import authentik_groups, display_name, email
from tessaro_dataset.exports.base import ExportRecord


class AuthentikUser(ExportRecord):
    """A user and the groups derived for them (AC-9)."""

    username: str
    name: str
    email: str
    employee_id: str
    groups: tuple[str, ...]
    is_active: bool


class AuthentikGroup(ExportRecord):
    """A group; elevated groups need IT approval before anyone joins them."""

    name: str
    elevated: bool


class AuthentikExport(ExportRecord):
    """Everything the Authentik seed job writes."""

    users: tuple[AuthentikUser, ...]
    groups: tuple[AuthentikGroup, ...]


def export_authentik(dataset: Dataset, include_demo_inputs: bool = False) -> AuthentikExport:
    """Users and groups, sorted by name."""
    people = dataset.seed_employees(include_demo_inputs=include_demo_inputs)
    users = tuple(
        AuthentikUser(
            username=email(e).split("@")[0],
            name=display_name(e),
            email=email(e),
            employee_id=e.id,
            groups=authentik_groups(dataset, e),
            is_active=True,
        )
        for e in sorted(people, key=lambda e: e.id)
    )
    elevated = {g.authentik_group for b in dataset.bundles for g in b.elevated}
    names = {g for u in users for g in u.groups} | elevated
    names |= {g for b in dataset.bundles for g in b.authentik_groups}
    return AuthentikExport(
        users=users,
        groups=tuple(AuthentikGroup(name=n, elevated=n in elevated) for n in sorted(names)),
    )
