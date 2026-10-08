"""Zulip: users, channels and the derived channel subscriptions."""

from tessaro_dataset.dataset import Dataset
from tessaro_dataset.derive import display_name, email, zulip_channels
from tessaro_dataset.exports.base import ExportRecord


class ZulipUser(ExportRecord):
    """A Zulip user; the full name is also their mention handle."""

    email: str
    full_name: str
    employee_id: str


class ZulipChannel(ExportRecord):
    """A channel."""

    name: str
    description: str


class ZulipSubscription(ExportRecord):
    """One person subscribed to one channel."""

    channel: str
    email: str


class ZulipExport(ExportRecord):
    """Everything the Zulip seed job writes."""

    users: tuple[ZulipUser, ...]
    channels: tuple[ZulipChannel, ...]
    subscriptions: tuple[ZulipSubscription, ...]


def export_zulip(dataset: Dataset, include_demo_inputs: bool = False) -> ZulipExport:
    """Users, channels and subscriptions, sorted by key."""
    people = sorted(dataset.seed_employees(include_demo_inputs=include_demo_inputs), key=email)
    return ZulipExport(
        users=tuple(
            ZulipUser(email=email(e), full_name=display_name(e), employee_id=e.id) for e in people
        ),
        channels=tuple(
            ZulipChannel(name=c.name, description=c.description)
            for c in sorted(dataset.channels, key=lambda c: c.name)
        ),
        subscriptions=tuple(
            sorted(
                (
                    ZulipSubscription(channel=ch, email=email(e))
                    for e in people
                    for ch in zulip_channels(dataset, e)
                ),
                key=lambda s: (s.channel, s.email),
            )
        ),
    )
