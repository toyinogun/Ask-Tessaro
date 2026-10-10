"""Plan the writes that bring Authentik and Zulip to the dataset (pure; no I/O).

The seed owns only the dataset's seed employees: Authentik users whose `attributes.employee_id`
is one of theirs, Zulip users whose email is one of theirs, memberships of the dataset's groups,
and subscriptions to the dataset's channels. Everything else (admins, service accounts, bots,
joiners a workflow created) never appears in a plan.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from tessaro_clients.authentik import EMPLOYEE_ID, DirectoryUser, UserChange
from tessaro_clients.zulip import Channel, ChatUser
from tessaro_dataset.exports.authentik import AuthentikExport, AuthentikUser
from tessaro_dataset.exports.zulip import ZulipExport


class PlanError(Exception):
    """The current state is ambiguous, so no safe plan exists."""


# --- Authentik ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateUser:
    """Create a seed employee, set the demo password and add their groups."""

    person: AuthentikUser

    @property
    def subject(self) -> str:
        """The email the action is about."""
        return self.person.email


@dataclass(frozen=True)
class UpdateUser:
    """Change the fields of an existing seed employee that differ from the dataset."""

    pk: int
    subject: str
    change: UserChange


@dataclass(frozen=True)
class SetPassword:
    """Set the demo password again (only with `--reset-passwords`)."""

    pk: int
    subject: str


@dataclass(frozen=True)
class JoinGroup:
    """Add an existing seed employee to a dataset group."""

    pk: int
    subject: str
    group: str


@dataclass(frozen=True)
class LeaveGroup:
    """Remove an existing seed employee from a dataset group the dataset does not give them."""

    pk: int
    subject: str
    group: str


AuthentikAction = CreateUser | UpdateUser | SetPassword | JoinGroup | LeaveGroup


def missing_groups(desired: AuthentikExport, existing: Iterable[str]) -> tuple[str, ...]:
    """Dataset groups that do not exist in Authentik yet, sorted."""
    needed = {g.name for g in desired.groups} | {g for u in desired.users for g in u.groups}
    return tuple(sorted(needed - set(existing)))


def _owned(current: Iterable[DirectoryUser], ids: set[str]) -> dict[str, DirectoryUser]:
    owned: dict[str, DirectoryUser] = {}
    for user in current:
        employee_id = user.employee_id
        if employee_id not in ids:
            continue
        if employee_id in owned:
            raise PlanError(
                f"{EMPLOYEE_ID} {employee_id} is on two Authentik users "
                f"({owned[employee_id].username}, {user.username}); remove one by hand"
            )
        owned[employee_id] = user
    return owned


def _change(person: AuthentikUser, user: DirectoryUser) -> UserChange | None:
    fields = {
        "username": person.username,
        "name": person.name,
        "email": person.email,
        "is_active": person.is_active,
    }
    differ = {k: v for k, v in fields.items() if getattr(user, k) != v}
    return UserChange.model_validate(differ) if differ else None


def plan_authentik(
    desired: AuthentikExport,
    current: Iterable[DirectoryUser],
    managed_groups: frozenset[str],
    *,
    reset_passwords: bool = False,
) -> tuple[AuthentikAction, ...]:
    """The writes that make every seed employee match the dataset, in dataset order.

    ``managed_groups`` are the dataset's group names: memberships outside them are left alone.
    Raises PlanError when two users carry the same seed `employee_id`.
    """
    owned = _owned(current, {p.employee_id for p in desired.users})
    actions: list[AuthentikAction] = []
    for person in desired.users:
        user = owned.get(person.employee_id)
        if user is None:
            actions.append(CreateUser(person))
            continue
        change = _change(person, user)
        if change is not None:
            actions.append(UpdateUser(user.pk, person.email, change))
        if reset_passwords:
            actions.append(SetPassword(user.pk, person.email))
        want, have = set(person.groups), set(user.groups) & managed_groups
        actions += [JoinGroup(user.pk, person.email, g) for g in sorted(want - have)]
        actions += [LeaveGroup(user.pk, person.email, g) for g in sorted(have - want)]
    return tuple(actions)


# --- Zulip -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateChannel:
    """Create a dataset channel that does not exist yet."""

    name: str
    description: str


@dataclass(frozen=True)
class CreateChatUser:
    """Create a seed employee's Zulip account (with a random, unusable password)."""

    subject: str
    full_name: str


@dataclass(frozen=True)
class RenameChatUser:
    """Set a seed employee's full name (their mention handle) to the dataset's."""

    user_id: int
    subject: str
    full_name: str


@dataclass(frozen=True)
class ReactivateChatUser:
    """Reactivate a seed employee's account (a demo reset after the leaver workflow)."""

    user_id: int
    subject: str


@dataclass(frozen=True)
class Subscribe:
    """Subscribe seed employees to a dataset channel."""

    channel: str
    subjects: tuple[str, ...]


@dataclass(frozen=True)
class Unsubscribe:
    """Unsubscribe seed employees from a dataset channel the dataset does not give them."""

    channel: str
    subjects: tuple[str, ...]


ZulipAction = (
    CreateChannel | CreateChatUser | RenameChatUser | ReactivateChatUser | Subscribe | Unsubscribe
)


def _by_email(users: Iterable[ChatUser], emails: set[str]) -> dict[str, ChatUser]:
    found: dict[str, ChatUser] = {}
    for user in users:
        if user.real_email in emails and not user.is_bot:
            if user.real_email in found:
                raise PlanError(f"two Zulip users share {user.real_email}; remove one by hand")
            found[user.real_email] = user
    return found


def _subscriptions(desired: ZulipExport) -> dict[str, set[str]]:
    wanted: dict[str, set[str]] = defaultdict(set)
    for sub in desired.subscriptions:
        wanted[sub.channel].add(sub.email)
    return wanted


def plan_zulip(
    desired: ZulipExport,
    users: Iterable[ChatUser],
    channels: Iterable[Channel],
    subscribers: Mapping[str, frozenset[int]],
) -> tuple[ZulipAction, ...]:
    """Channels first, then accounts, then subscriptions, for the seed employees only.

    ``subscribers`` maps an existing channel's name to its subscribers' user_ids. Raises PlanError
    when two Zulip users share a seed employee's email.
    """
    emails = {u.email for u in desired.users}
    owned = _by_email(users, emails)
    existing = {c.name for c in channels}
    actions: list[ZulipAction] = [
        CreateChannel(c.name, c.description) for c in desired.channels if c.name not in existing
    ]
    for person in desired.users:
        user = owned.get(person.email)
        if user is None:
            actions.append(CreateChatUser(person.email, person.full_name))
            continue
        if user.full_name != person.full_name:
            actions.append(RenameChatUser(user.user_id, person.email, person.full_name))
        if not user.is_active:
            actions.append(ReactivateChatUser(user.user_id, person.email))
    email_of = {u.user_id: email for email, u in owned.items()}
    wanted = _subscriptions(desired)
    for channel in desired.channels:
        ids = subscribers.get(channel.name, frozenset())
        have = {email_of[i] for i in ids if i in email_of}
        want = wanted.get(channel.name, set())
        if want - have:
            actions.append(Subscribe(channel.name, tuple(sorted(want - have))))
        if have - want:
            actions.append(Unsubscribe(channel.name, tuple(sorted(have - want))))
    return tuple(actions)
