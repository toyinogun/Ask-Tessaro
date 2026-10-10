"""The realm rules `just zulip-bootstrap` converges to (spec 0008 AC-11 step 4)."""

import json

import pytest

from tessaro_seed.zulip_bootstrap.realm import (
    GROUP_RULES,
    REALM_NAME,
    BootstrapError,
    RealmState,
    realm_changes,
)

SYSTEM_GROUPS = {"role:nobody": 1, "role:administrators": 3, "role:members": 5}


def state(**overrides: object) -> RealmState:
    """A realm as Zulip creates it: email and OIDC on, open invitations, members make channels."""
    base: dict[str, object] = {
        "name": REALM_NAME,
        "invite_required": False,
        "authentication_methods": {"Email": True, "OpenID Connect": True},
        "groups": {
            "can_invite_users_group": "role:members",
            "create_multiuse_invite_group": "role:administrators",
            "can_create_public_channel_group": "role:members",
            "can_create_private_channel_group": "role:members",
        },
        "system_groups": SYSTEM_GROUPS,
    }
    return RealmState.model_validate({**base, **overrides})


def converged() -> RealmState:
    return state(
        invite_required=True,
        authentication_methods={"Email": False, "OpenID Connect": True},
        groups=dict(GROUP_RULES),
    )


def test_a_new_realm_gets_oidc_only_no_invitations_and_admin_channels() -> None:
    changes = realm_changes(state())
    assert json.loads(changes.pop("authentication_methods")) == {
        "Email": False,
        "OpenID Connect": True,
    }
    assert changes.pop("invite_required") == "true"
    assert {k: json.loads(v) for k, v in changes.items()} == {
        "can_invite_users_group": {"new": 1},
        "create_multiuse_invite_group": {"new": 1},
        "can_create_public_channel_group": {"new": 3},
        "can_create_private_channel_group": {"new": 3},
    }


def test_a_converged_realm_needs_no_change() -> None:
    assert realm_changes(converged()) == {}


def test_only_the_differing_settings_are_sent() -> None:
    changes = realm_changes(converged().model_copy(update={"name": "Other"}))
    assert changes == {"name": REALM_NAME}


def test_an_unnamed_group_setting_is_replaced() -> None:
    groups = {**GROUP_RULES, "can_invite_users_group": None}
    changes = realm_changes(converged().model_copy(update={"groups": groups}))
    assert changes == {"can_invite_users_group": json.dumps({"new": 1})}


def test_every_other_auth_method_is_turned_off() -> None:
    methods = {"Email": False, "OpenID Connect": True, "GitHub": True}
    changes = realm_changes(converged().model_copy(update={"authentication_methods": methods}))
    assert json.loads(changes["authentication_methods"]) == {
        "Email": False,
        "OpenID Connect": True,
        "GitHub": False,
    }


def test_a_server_without_oidc_is_an_error() -> None:
    with pytest.raises(BootstrapError, match="OpenID Connect"):
        realm_changes(state(authentication_methods={"Email": True}))


def test_a_missing_system_group_is_an_error() -> None:
    with pytest.raises(BootstrapError, match="role:nobody"):
        realm_changes(state(system_groups={"role:administrators": 3}))
