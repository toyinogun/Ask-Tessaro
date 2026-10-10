"""What `just zulip-bootstrap` brings the Zulip realm to (spec 0008 AC-11), as plain values.

The realm, its user defaults and its owner are fixed here; `realm_changes` turns the realm's
current rules into the `PATCH /realm` form values that reach the target, and nothing else.
"""

import json

from pydantic import BaseModel, ConfigDict

REALM_NAME = "Tessaro"
# The root domain: `chat.tessaro.toyintest.org` itself holds the realm.
STRING_ID = ""
OWNER_EMAIL = "tessaro-admin@tessaro.example"
OWNER_NAME = "Tessaro Admin"
OWNER_ROLE = "owner"
CREATE_USERS = "can_create_users"
OIDC = "OpenID Connect"

# Zulip's `UserProfile.EMAIL_ADDRESS_VISIBILITY_EVERYONE`.
EMAIL_VISIBILITY_EVERYONE = 1

# Realm user defaults, set before any user exists: real emails visible (the adapter matches
# `sender_email`), and no push or email notification of any kind (no SMTP, no bouncer).
USER_DEFAULTS: dict[str, int | bool] = {
    "email_address_visibility": EMAIL_VISIBILITY_EVERYONE,
    "enable_digest_emails": False,
    "enable_followed_topic_email_notifications": False,
    "enable_followed_topic_push_notifications": False,
    "enable_login_emails": False,
    "enable_marketing_emails": False,
    "enable_offline_email_notifications": False,
    "enable_offline_push_notifications": False,
    "enable_online_push_notifications": False,
    "enable_stream_email_notifications": False,
    "enable_stream_push_notifications": False,
}

# Realm permission settings and the system group each must name: invitations off, and only
# administrators create channels.
GROUP_RULES: dict[str, str] = {
    "can_invite_users_group": "role:nobody",
    "create_multiuse_invite_group": "role:nobody",
    "can_create_public_channel_group": "role:administrators",
    "can_create_private_channel_group": "role:administrators",
}


class BootstrapError(Exception):
    """A bootstrap step failed or Zulip is not in a state the bootstrap can work from."""


class RealmState(BaseModel):
    """The realm rules as Zulip holds them; a group setting is None when no named group holds it."""

    model_config = ConfigDict(frozen=True)

    name: str
    invite_required: bool
    authentication_methods: dict[str, bool]
    groups: dict[str, str | None]
    system_groups: dict[str, int]


class OwnerRecord(BaseModel):
    """The realm owner after step 3: whether this run created it, its role and its API key."""

    model_config = ConfigDict(frozen=True)

    created: bool
    role: str
    can_create_users: bool
    api_key: str


def _auth_methods(current: dict[str, bool]) -> dict[str, bool]:
    if OIDC not in current:
        raise BootstrapError(f"the server has no {OIDC} backend; check ZULIP_AUTH_BACKENDS")
    return {name: name == OIDC for name in current}


def _group_id(state: RealmState, group: str) -> int:
    if group not in state.system_groups:
        raise BootstrapError(f"the realm has no system group {group}")
    return state.system_groups[group]


def realm_changes(state: RealmState) -> dict[str, str]:
    """The `PATCH /realm` form values that bring ``state`` to the target; empty when it is there."""
    changes: dict[str, str] = {}
    if state.name != REALM_NAME:
        changes["name"] = REALM_NAME
    methods = _auth_methods(state.authentication_methods)
    if methods != state.authentication_methods:
        changes["authentication_methods"] = json.dumps(methods)
    if not state.invite_required:
        changes["invite_required"] = "true"
    for setting, group in GROUP_RULES.items():
        group_id = _group_id(state, group)
        if state.groups.get(setting) != group:
            changes[setting] = json.dumps({"new": group_id})
    return changes
