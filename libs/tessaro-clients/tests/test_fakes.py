"""The in memory fakes behave like the systems they stand in for, seeded from the dataset."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tessaro_clients.authentik import FakeAuthentikDirectory, NewUser, UserChange
from tessaro_clients.errors import ApiError
from tessaro_clients.zulip import FakeZulipAdmin, NewChatUser
from tessaro_dataset.exports.authentik import export_authentik
from tessaro_dataset.exports.zulip import export_zulip
from tessaro_dataset.loader import load_dataset

# Stands in for the random password the seed sends; any string will do.
RANDOM = "r4nd0m"
ANCHOR = datetime(2026, 10, 7, 10, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))
DATASET = load_dataset(anchor=ANCHOR)


class TestFakeAuthentik:
    async def test_from_export_holds_the_groups_and_optionally_the_people(self) -> None:
        export = export_authentik(DATASET)
        empty = FakeAuthentikDirectory.from_export(export)
        seeded = FakeAuthentikDirectory.from_export(export, users=True)
        assert {g.name for g in await empty.list_groups()} == {g.name for g in export.groups}
        assert await empty.list_users() == ()
        users = await seeded.list_users()
        assert {u.employee_id for u in users} == {u.employee_id for u in export.users}

    async def test_writes_change_state_and_are_logged(self) -> None:
        fake = FakeAuthentikDirectory.with_groups(["staff"])
        user = await fake.create_user(NewUser(username="a", name="A", email="a@x"))
        await fake.add_to_group("g-staff", user.pk)
        assert (await fake.get_user_by_email("a@x")) == fake.users[user.pk]
        assert fake.users[user.pk].groups == ("staff",)
        await fake.remove_from_group("g-staff", user.pk)
        await fake.update_user(user.pk, UserChange(is_active=False))
        await fake.set_password(user.pk, "pw")
        assert fake.users[user.pk].groups == ()
        assert fake.users[user.pk].is_active is False
        assert fake.passwords[user.pk] == "pw"
        assert [w.split()[0] for w in fake.writes] == [
            "create_user",
            "add_to_group",
            "remove_from_group",
            "update_user",
            "set_password",
        ]

    async def test_a_taken_username_is_refused(self) -> None:
        fake = FakeAuthentikDirectory()
        await fake.create_user(NewUser(username="a", name="A", email="a@x"))
        with pytest.raises(ApiError, match="taken"):
            await fake.create_user(NewUser(username="a", name="B", email="b@x"))

    async def test_unknown_records_are_404(self) -> None:
        fake = FakeAuthentikDirectory.with_groups(["staff"])
        with pytest.raises(ApiError, match="404"):
            await fake.add_to_group("g-nope", 1)
        with pytest.raises(ApiError, match="404"):
            await fake.add_to_group("g-staff", 99)

    async def test_a_broken_method_fails_with_500(self) -> None:
        fake = FakeAuthentikDirectory(broken=frozenset({"list_users"}))
        with pytest.raises(ApiError, match="500"):
            await fake.list_users()


class TestFakeZulip:
    async def test_from_export_with_people_holds_users_channels_and_subscriptions(self) -> None:
        export = export_zulip(DATASET)
        chat = FakeZulipAdmin.from_export(export, people=True)
        assert {u.real_email for u in await chat.list_users()} == {u.email for u in export.users}
        assert {c.name for c in await chat.list_channels()} == {c.name for c in export.channels}
        sub = export.subscriptions[0]
        assert sub.email in chat.subscribed(sub.channel)

    async def test_without_people_it_is_an_empty_realm(self) -> None:
        chat = FakeZulipAdmin.from_export(export_zulip(DATASET))
        assert await chat.realm_exists() is True
        assert await chat.list_users() == ()

    async def test_writes_change_state(self) -> None:
        chat = FakeZulipAdmin()
        user_id = await chat.create_user(NewChatUser(email="a@x", full_name="A", password=RANDOM))
        await chat.create_channel("c", "d")
        (channel,) = await chat.list_channels()
        await chat.subscribe("c", [user_id])
        assert await chat.channel_subscribers(channel.stream_id) == {user_id}
        await chat.unsubscribe("c", [user_id])
        await chat.update_user(user_id, full_name="B")
        await chat.deactivate_user(user_id)
        assert chat.users[user_id].is_active is False
        await chat.reactivate_user(user_id)
        assert chat.users[user_id].full_name == "B"
        assert chat.subscribed("c") == frozenset()
        assert len(chat.writes) == 7

    async def test_a_used_email_and_an_unknown_channel_are_refused(self) -> None:
        chat = FakeZulipAdmin()
        await chat.create_user(NewChatUser(email="a@x", full_name="A", password=RANDOM))
        with pytest.raises(ApiError, match="in use"):
            await chat.create_user(NewChatUser(email="a@x", full_name="A", password=RANDOM))
        with pytest.raises(ApiError, match="no channel"):
            await chat.subscribe("nope", [1])
        with pytest.raises(ApiError, match="404"):
            await chat.update_user(999, full_name="x")

    async def test_before_bootstrap_every_call_but_the_realm_check_fails(self) -> None:
        chat = FakeZulipAdmin(realm=False)
        assert await chat.realm_exists() is False
        with pytest.raises(ApiError, match="401"):
            await chat.list_users()

    async def test_a_realm_that_hides_emails_shows_placeholders(self) -> None:
        chat = FakeZulipAdmin(hide_emails=True)
        user_id = chat.add_user("a@tessaro.example", "A")
        (user,) = await chat.list_users()
        assert user.email == f"user{user_id}@chat.example"
        assert user.delivery_email is None

    async def test_a_broken_method_fails_with_500(self) -> None:
        chat = FakeZulipAdmin(broken=frozenset({"list_channels"}))
        with pytest.raises(ApiError, match="500"):
            await chat.list_channels()
