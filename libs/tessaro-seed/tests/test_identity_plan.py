"""The pure planning step and the lines the seed prints for each action."""

import pytest

from tessaro_clients.authentik import UserChange
from tessaro_clients.zulip import Channel, ChatUser
from tessaro_dataset.exports.zulip import ZulipChannel, ZulipExport, ZulipSubscription, ZulipUser
from tessaro_seed.identity.plan import (
    AuthentikAction,
    CreateChannel,
    LeaveGroup,
    PlanError,
    ReactivateChatUser,
    RenameChatUser,
    SetPassword,
    Subscribe,
    Unsubscribe,
    UpdateUser,
    ZulipAction,
    plan_zulip,
)
from tessaro_seed.identity.reconcile import describe

ANA = "ana@tessaro.example"
BOB = "bob@tessaro.example"
DESIRED = ZulipExport(
    users=(
        ZulipUser(email=ANA, full_name="Ana", employee_id="TES-1"),
        ZulipUser(email=BOB, full_name="Bob", employee_id="TES-2"),
    ),
    channels=(ZulipChannel(name="general", description="All of us"),),
    subscriptions=(ZulipSubscription(channel="general", email=ANA),),
)
CHANNELS = (Channel(stream_id=1, name="general"),)


def user(user_id: int, email: str, name: str, *, active: bool = True) -> ChatUser:
    return ChatUser(user_id=user_id, email=email, full_name=name, is_active=active)


def test_a_seed_employee_on_a_channel_they_should_not_be_on_is_unsubscribed() -> None:
    users = (user(1, ANA, "Ana"), user(2, BOB, "Bob"))
    actions = plan_zulip(DESIRED, users, CHANNELS, {"general": frozenset({1, 2})})
    assert actions == (Unsubscribe("general", (BOB,)),)


def test_a_matching_realm_plans_nothing() -> None:
    users = (user(1, ANA, "Ana"), user(2, BOB, "Bob"))
    assert plan_zulip(DESIRED, users, CHANNELS, {"general": frozenset({1})}) == ()


def test_renames_and_reactivations_are_planned_per_person() -> None:
    users = (user(1, ANA, "Old", active=False), user(2, BOB, "Bob"))
    actions = plan_zulip(DESIRED, users, CHANNELS, {"general": frozenset({1})})
    assert actions == (RenameChatUser(1, ANA, "Ana"), ReactivateChatUser(1, ANA))


def test_two_zulip_users_with_one_seed_email_stop_the_plan() -> None:
    users = (user(1, ANA, "Ana"), user(3, ANA, "Ana again"))
    with pytest.raises(PlanError, match=ANA):
        plan_zulip(DESIRED, users, CHANNELS, {})


def test_a_bot_with_a_seed_email_is_ignored() -> None:
    bot = ChatUser(user_id=9, email=ANA, full_name="Bot", is_active=True, is_bot=True)
    actions = plan_zulip(DESIRED, (bot, user(1, ANA, "Ana"), user(2, BOB, "Bob")), CHANNELS, {})
    assert actions == (Subscribe("general", (ANA,)),)


@pytest.mark.parametrize(
    ("action", "line"),
    [
        (
            UpdateUser(1, ANA, UserChange(name="A", is_active=True)),
            f"update {ANA}: is_active, name",
        ),
        (SetPassword(1, ANA), f"set the demo password of {ANA}"),
        (LeaveGroup(1, ANA, "managers"), f"remove {ANA} from managers"),
        (CreateChannel("general", "x"), "create channel general"),
        (RenameChatUser(1, ANA, "Ana"), f"rename {ANA} to Ana"),
        (ReactivateChatUser(1, ANA), f"reactivate {ANA}"),
        (Subscribe("general", (ANA, BOB)), f"subscribe {ANA}, {BOB} to general"),
        (Unsubscribe("general", (BOB,)), f"unsubscribe {BOB} from general"),
    ],
)
def test_describe_names_the_write_and_the_record(
    action: AuthentikAction | ZulipAction, line: str
) -> None:
    assert describe(action) == line
