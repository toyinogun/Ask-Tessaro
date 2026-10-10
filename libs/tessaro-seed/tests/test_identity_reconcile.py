"""`tessaro-seed identity` against the fakes: AC-12 end to end, without the network."""

import re

import pytest

from tessaro_clients.authentik import EMPLOYEE_ID, DirectoryUser, FakeAuthentikDirectory
from tessaro_clients.errors import ApiError
from tessaro_clients.zulip import FakeZulipAdmin
from tessaro_seed.identity.reconcile import IdentityInput, ReconcileError, reconcile_identity

PERSONA = "TES-01003"


def fresh(data: IdentityInput) -> tuple[FakeAuthentikDirectory, FakeZulipAdmin]:
    """Authentik with only the blueprint groups, Zulip with only an empty realm."""
    groups = data.managed_groups | {"authentik Admins"}
    return FakeAuthentikDirectory.with_groups(groups), FakeZulipAdmin()


def by_employee(directory: FakeAuthentikDirectory, employee_id: str) -> DirectoryUser:
    return next(u for u in directory.users.values() if u.employee_id == employee_id)


async def test_a_first_run_creates_everyone_with_groups_password_and_channels(
    data: IdentityInput,
) -> None:
    directory, chat = fresh(data)
    result = await reconcile_identity(directory, chat, data, new_password=lambda: "random")
    people = data.authentik.users
    assert result.authentik.created == len(people)
    assert result.zulip_users.created == len(data.zulip.users)
    assert result.zulip_channels.created == len(data.zulip.channels)
    for person in people:
        user = by_employee(directory, person.employee_id)
        assert (user.username, user.name, user.email) == (
            person.username,
            person.name,
            person.email,
        )
        assert set(user.groups) == set(person.groups)
        assert user.is_active
        assert directory.passwords[user.pk] == "demo-pass"
    for sub in data.zulip.subscriptions:
        assert sub.email in chat.subscribed(sub.channel)
    assert set(chat.passwords.values()) == {"random"}


async def test_demo_input_joiners_are_not_seeded(data: IdentityInput, dataset: object) -> None:
    from tessaro_dataset import Dataset

    assert isinstance(dataset, Dataset)
    joiners = {e.id for e in dataset.employees if not e.is_seed}
    assert joiners
    directory, chat = fresh(data)
    await reconcile_identity(directory, chat, data)
    assert not joiners & {u.employee_id for u in directory.users.values()}


async def test_a_second_run_writes_nothing_and_reports_no_changes(data: IdentityInput) -> None:
    directory, chat = fresh(data)
    await reconcile_identity(directory, chat, data)
    writes = (len(directory.writes), len(chat.writes))
    again = await reconcile_identity(directory, chat, data)
    assert (len(directory.writes), len(chat.writes)) == writes
    assert again.authentik.created == again.authentik.updated == 0
    assert again.zulip_users.created == again.zulip_users.updated == 0
    assert again.zulip_channels.created == 0
    assert again.authentik.unchanged == len(data.authentik.users)


async def test_drift_is_put_back_and_counted_as_updated(data: IdentityInput) -> None:
    directory, chat = fresh(data)
    await reconcile_identity(directory, chat, data)
    persona = by_employee(directory, PERSONA)
    directory.users[persona.pk] = persona.model_copy(
        update={
            "name": "Wrong",
            "is_active": False,
            "groups": (*(g for g in persona.groups if g != "staff"), "it-agents"),
        }
    )
    email = persona.email
    zulip_id = next(i for i, u in chat.users.items() if u.real_email == email)
    stray = next(c.name for c in data.zulip.channels if email not in chat.subscribed(c.name))
    await chat.subscribe(stray, [zulip_id])
    await chat.deactivate_user(zulip_id)
    await chat.update_user(zulip_id, full_name="Wrong")
    result = await reconcile_identity(directory, chat, data)
    assert email not in chat.subscribed(stray)
    fixed = by_employee(directory, PERSONA)
    assert (fixed.name, fixed.is_active, fixed.groups) == (persona.name, True, persona.groups)
    assert chat.users[zulip_id].is_active
    assert chat.users[zulip_id].full_name != "Wrong"
    assert result.authentik.updated == 1
    assert result.zulip_users.updated == 1


async def test_records_the_seed_does_not_own_are_never_touched(data: IdentityInput) -> None:
    directory, chat = fresh(data)
    await reconcile_identity(directory, chat, data)
    admin = directory.add_user("tessaro-admin", groups=("authentik Admins",))
    joiner = directory.add_user("joiner", employee_id="TES-09999", groups=("staff",))
    bot_id = chat.add_user("tessaro-bot@chat.example", "Tessaro bot", is_bot=True)
    stranger = chat.add_user("someone@tessaro.example", "Someone")
    channel = data.zulip.channels[0].name
    other = chat.add_channel("not-in-dataset")
    await chat.subscribe(channel, [stranger, bot_id])
    chat.subscribers[other].add(stranger)
    before_a = (directory.users[admin], directory.users[joiner])
    directory.writes.clear()
    chat.writes.clear()
    await reconcile_identity(directory, chat, data)
    assert (directory.users[admin], directory.users[joiner]) == before_a
    assert directory.writes == []
    assert chat.writes == []
    assert {"someone@tessaro.example", "tessaro-bot@chat.example"} <= chat.subscribed(channel)


async def test_a_missing_group_stops_before_any_write_naming_every_group(
    data: IdentityInput,
) -> None:
    directory, chat = fresh(data)
    del directory.groups["g-staff"], directory.groups["g-managers"]
    with pytest.raises(ReconcileError, match="managers, staff"):
        await reconcile_identity(directory, chat, data)
    assert directory.writes == chat.writes == []


async def test_a_missing_realm_stops_before_any_write(data: IdentityInput) -> None:
    directory, _ = fresh(data)
    chat = FakeZulipAdmin(realm=False)
    with pytest.raises(ReconcileError, match="just zulip-bootstrap"):
        await reconcile_identity(directory, chat, data)
    assert directory.writes == []


async def test_a_dry_run_plans_but_writes_nothing(data: IdentityInput) -> None:
    directory, chat = fresh(data)
    result = await reconcile_identity(directory, chat, data, dry_run=True)
    assert result.authentik.created == len(data.authentik.users)
    assert directory.writes == chat.writes == []


async def test_reset_passwords_sets_the_password_again(data: IdentityInput) -> None:
    directory, chat = fresh(data)
    await reconcile_identity(directory, chat, data)
    directory.passwords.clear()
    result = await reconcile_identity(directory, chat, data, reset_passwords=True)
    assert set(directory.passwords.values()) == {"demo-pass"}
    assert result.authentik.updated == len(data.authentik.users)


async def test_a_failed_write_names_the_record(data: IdentityInput) -> None:
    directory, chat = fresh(data)
    directory.broken = frozenset({"create_user"})
    first = data.authentik.users[0].email
    with pytest.raises(ReconcileError, match=rf"authentik: create user {re.escape(first)}: .*500"):
        await reconcile_identity(directory, chat, data)


async def test_a_failed_zulip_write_names_the_record(data: IdentityInput) -> None:
    directory, chat = fresh(data)
    chat.broken = frozenset({"subscribe"})
    with pytest.raises(ReconcileError, match=r"zulip: subscribe .* to "):
        await reconcile_identity(directory, chat, data)


async def test_a_failed_read_is_reported(data: IdentityInput) -> None:
    directory, chat = fresh(data)
    directory.broken = frozenset({"list_users"})
    with pytest.raises(ReconcileError, match="reading the current state failed"):
        await reconcile_identity(directory, chat, data)


async def test_a_failed_read_before_writing_is_reported(data: IdentityInput) -> None:
    directory, chat = fresh(data)
    chat.broken = frozenset({"list_users"})
    with pytest.raises(ReconcileError, match="reading"):
        await reconcile_identity(directory, chat, data)


async def test_a_failed_read_while_applying_is_reported(
    data: IdentityInput, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, chat = fresh(data)
    calls = {"n": 0}
    real = directory.list_groups

    async def flaky() -> tuple[object, ...]:
        calls["n"] += 1
        if calls["n"] > 1:
            raise ApiError("authentik", "list_groups", 503)
        return await real()

    monkeypatch.setattr(directory, "list_groups", flaky)
    with pytest.raises(ReconcileError, match="reading before a write failed"):
        await reconcile_identity(directory, chat, data)


async def test_two_users_with_one_employee_id_stop_the_seed(data: IdentityInput) -> None:
    directory, chat = fresh(data)
    directory.add_user("a", employee_id=PERSONA)
    directory.add_user("b", employee_id=PERSONA)
    with pytest.raises(ReconcileError, match=f"{EMPLOYEE_ID} {PERSONA} is on two"):
        await reconcile_identity(directory, chat, data)
