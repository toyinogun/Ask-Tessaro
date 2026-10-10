"""The `tessaro-seed identity` use case: check, plan, then apply, through the client protocols.

Both preconditions (every dataset group exists in Authentik, the Zulip realm exists) are checked
before anything is written in either system. An API failure while applying stops the run and
names the record it was writing.
"""

import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from tessaro_clients.authentik import AuthentikDirectory, NewUser
from tessaro_clients.errors import ClientError
from tessaro_clients.zulip import NewChatUser, ZulipAdmin
from tessaro_dataset.exports.authentik import AuthentikExport
from tessaro_dataset.exports.zulip import ZulipExport
from tessaro_seed.identity.plan import (
    AuthentikAction,
    CreateChannel,
    CreateChatUser,
    CreateUser,
    JoinGroup,
    LeaveGroup,
    PlanError,
    ReactivateChatUser,
    RenameChatUser,
    SetPassword,
    Subscribe,
    Unsubscribe,
    UpdateUser,
    ZulipAction,
    missing_groups,
    plan_authentik,
    plan_zulip,
)


class ReconcileError(Exception):
    """The seed stopped; the message says why and what to do."""


@dataclass(frozen=True)
class IdentityInput:
    """What the seed reconciles to: the dataset's seed employees and the groups it manages."""

    authentik: AuthentikExport
    zulip: ZulipExport
    managed_groups: frozenset[str]
    demo_password: str


@dataclass(frozen=True)
class Counts:
    """Records per system: created, updated (any other write) and unchanged."""

    created: int
    updated: int
    unchanged: int


@dataclass(frozen=True)
class IdentityReport:
    """What a run did (or, in a dry run, would do)."""

    authentik_actions: tuple[AuthentikAction, ...]
    zulip_actions: tuple[ZulipAction, ...]
    authentik: Counts
    zulip_users: Counts
    zulip_channels: Counts


def _counts(subjects: Iterable[str], created: set[str], touched: set[str]) -> Counts:
    everyone = set(subjects)
    return Counts(
        created=len(created & everyone),
        updated=len((touched - created) & everyone),
        unchanged=len(everyone - created - touched),
    )


def _zulip_touched(actions: Iterable[ZulipAction]) -> set[str]:
    touched: set[str] = set()
    for action in actions:
        if isinstance(action, RenameChatUser | ReactivateChatUser):
            touched.add(action.subject)
        elif isinstance(action, Subscribe | Unsubscribe):
            touched.update(action.subjects)
    return touched


def report(
    data: IdentityInput, authentik: tuple[AuthentikAction, ...], zulip: tuple[ZulipAction, ...]
) -> IdentityReport:
    """Count the planned actions per record."""
    created_a = {a.subject for a in authentik if isinstance(a, CreateUser)}
    created_z = {a.subject for a in zulip if isinstance(a, CreateChatUser)}
    channels = {a.name for a in zulip if isinstance(a, CreateChannel)}
    return IdentityReport(
        authentik_actions=authentik,
        zulip_actions=zulip,
        authentik=_counts(
            (u.email for u in data.authentik.users), created_a, {a.subject for a in authentik}
        ),
        zulip_users=_counts((u.email for u in data.zulip.users), created_z, _zulip_touched(zulip)),
        zulip_channels=_counts((c.name for c in data.zulip.channels), channels, set()),
    )


async def _check(directory: AuthentikDirectory, chat: ZulipAdmin, data: IdentityInput) -> None:
    if not await chat.realm_exists():
        raise ReconcileError("the Zulip realm does not exist yet; run `just zulip-bootstrap` first")
    groups = await directory.list_groups()
    missing = missing_groups(data.authentik, (g.name for g in groups))
    if missing:
        raise ReconcileError(
            f"groups missing in Authentik: {', '.join(missing)}; "
            "check the blueprints (`just blueprints`, then sync authentik)"
        )


def describe(action: AuthentikAction | ZulipAction) -> str:
    """A short line naming what an action writes and the record it is about."""
    match action:
        case CreateUser() | CreateChatUser():
            return f"create user {action.subject}"
        case UpdateUser(subject=s, change=c):
            return f"update {s}: {', '.join(sorted(c.model_dump(exclude_none=True)))}"
        case SetPassword(subject=s):
            return f"set the demo password of {s}"
        case JoinGroup(subject=s, group=g):
            return f"add {s} to {g}"
        case LeaveGroup(subject=s, group=g):
            return f"remove {s} from {g}"
        case CreateChannel(name=n):
            return f"create channel {n}"
        case RenameChatUser(subject=s, full_name=n):
            return f"rename {s} to {n}"
        case ReactivateChatUser(subject=s):
            return f"reactivate {s}"
        case Subscribe(channel=c, subjects=subjects):
            return f"subscribe {', '.join(subjects)} to {c}"
        case Unsubscribe(channel=c, subjects=subjects):
            return f"unsubscribe {', '.join(subjects)} from {c}"


async def _write_authentik(
    directory: AuthentikDirectory, action: AuthentikAction, group_pk: dict[str, str], password: str
) -> None:
    match action:
        case CreateUser(person=p):
            user = await directory.create_user(
                NewUser(
                    username=p.username,
                    name=p.name,
                    email=p.email,
                    is_active=p.is_active,
                    attributes={"employee_id": p.employee_id},
                )
            )
            await directory.set_password(user.pk, password)
            for group in p.groups:
                await directory.add_to_group(group_pk[group], user.pk)
        case UpdateUser(pk=pk, change=change):
            await directory.update_user(pk, change)
        case SetPassword(pk=pk):
            await directory.set_password(pk, password)
        case JoinGroup(pk=pk, group=group):
            await directory.add_to_group(group_pk[group], pk)
        case LeaveGroup(pk=pk, group=group):
            await directory.remove_from_group(group_pk[group], pk)


async def _write_zulip(
    chat: ZulipAdmin, action: ZulipAction, ids: dict[str, int], new_password: Callable[[], str]
) -> None:
    match action:
        case CreateChannel(name=name, description=description):
            await chat.create_channel(name, description)
        case CreateChatUser(subject=email, full_name=full_name):
            ids[email] = await chat.create_user(
                NewChatUser(email=email, full_name=full_name, password=new_password())
            )
        case RenameChatUser(user_id=user_id, full_name=full_name):
            await chat.update_user(user_id, full_name=full_name)
        case ReactivateChatUser(user_id=user_id):
            await chat.reactivate_user(user_id)
        case Subscribe(channel=channel, subjects=subjects):
            await chat.subscribe(channel, [ids[email] for email in subjects])
        case Unsubscribe(channel=channel, subjects=subjects):
            await chat.unsubscribe(channel, [ids[email] for email in subjects])


async def _apply(
    directory: AuthentikDirectory,
    chat: ZulipAdmin,
    data: IdentityInput,
    planned: IdentityReport,
    new_password: Callable[[], str],
) -> None:
    group_pk = {g.name: g.pk for g in await directory.list_groups()}
    for action in planned.authentik_actions:
        try:
            await _write_authentik(directory, action, group_pk, data.demo_password)
        except ClientError as error:
            raise ReconcileError(f"authentik: {describe(action)}: {error}") from error
    ids = {u.real_email: u.user_id for u in await chat.list_users() if not u.is_bot}
    for zulip_action in planned.zulip_actions:
        try:
            await _write_zulip(chat, zulip_action, ids, new_password)
        except ClientError as error:
            raise ReconcileError(f"zulip: {describe(zulip_action)}: {error}") from error


async def reconcile_identity(
    directory: AuthentikDirectory,
    chat: ZulipAdmin,
    data: IdentityInput,
    *,
    dry_run: bool = False,
    reset_passwords: bool = False,
    new_password: Callable[[], str] = lambda: secrets.token_urlsafe(32),
) -> IdentityReport:
    """Bring both systems to the dataset and report per record what changed.

    Raises ReconcileError when a precondition fails (before any write), when the current state
    is ambiguous, or when a write fails (naming the record).
    """
    try:
        await _check(directory, chat, data)
        authentik = plan_authentik(
            data.authentik,
            await directory.list_users(),
            data.managed_groups,
            reset_passwords=reset_passwords,
        )
        channels = await chat.list_channels()
        subscribers = {c.name: await chat.channel_subscribers(c.stream_id) for c in channels}
        zulip = plan_zulip(data.zulip, await chat.list_users(), channels, subscribers)
    except ClientError as error:
        raise ReconcileError(f"reading the current state failed: {error}") from error
    except PlanError as error:
        raise ReconcileError(str(error)) from error
    planned = report(data, authentik, zulip)
    if not dry_run:
        try:
            await _apply(directory, chat, data, planned, new_password)
        except ClientError as error:
            raise ReconcileError(f"reading before a write failed: {error}") from error
    return planned
