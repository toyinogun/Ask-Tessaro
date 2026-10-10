"""Shared fixtures: the real dataset at a pinned anchor, the identity input built from it, and an
in memory Zulip server for the bootstrap."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pytest

from tessaro_clients.zulip import FakeZulipAdmin
from tessaro_dataset import AMSTERDAM, Dataset, load_dataset
from tessaro_dataset.loader import DatasetPaths
from tessaro_seed.identity.command import identity_input
from tessaro_seed.identity.reconcile import IdentityInput
from tessaro_seed.zulip_bootstrap.bootstrap import AdminFactory
from tessaro_seed.zulip_bootstrap.realm import GROUP_RULES, OWNER_EMAIL, OwnerRecord, RealmState

REPO_ROOT = Path(__file__).resolve().parents[3]
# The demo password the tests seed with (a stand in, not a secret).
DEMO = "demo-pass"
WEDNESDAY_10 = datetime(2026, 10, 7, 10, 0, tzinfo=AMSTERDAM)


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    """The real dataset with the anchor pinned to Wednesday 7 October 2026, 10:00."""
    return load_dataset(DatasetPaths.under(REPO_ROOT), anchor=WEDNESDAY_10)


@pytest.fixture(scope="session")
def data(dataset: Dataset) -> IdentityInput:
    """What the seed reconciles to, with a fixed demo password."""
    return identity_input(dataset, DEMO)


SYSTEM_GROUPS = {"role:nobody": 1, "role:administrators": 3, "role:members": 5}
NAMES = {v: k for k, v in SYSTEM_GROUPS.items()}
# The owner API key the fake server hands out (a stand in, not a secret).
OWNER_KEY = "owner-api-key"


@dataclass
class FakeServer:
    """A Zulip server's realm, defaults and owner in plain fields; `calls` logs every step.

    Realm rules live in ``chat`` (the fake `ZulipAdmin` the owner's key opens), so a rule the
    bootstrap PATCHes shows up in the next `realm_state`.
    """

    ready_: bool = True
    realm_id: int | None = None
    defaults: dict[str, int | bool] = field(default_factory=dict)
    owner: OwnerRecord | None = None
    chat: FakeZulipAdmin = field(default_factory=FakeZulipAdmin)
    calls: list[str] = field(default_factory=list)

    async def ready(self) -> bool:
        return self.ready_

    async def ensure_realm(self, name: str, string_id: str) -> tuple[int, bool]:
        self.calls.append("realm")
        created = self.realm_id is None
        self.realm_id = self.realm_id or 7
        return self.realm_id, created

    async def ensure_user_defaults(self, realm_id: int, defaults: dict[str, int | bool]) -> bool:
        self.calls.append("defaults")
        assert self.owner is None or self.defaults == defaults, "defaults come before any user"
        changed = self.defaults != defaults
        self.defaults = dict(defaults)
        return changed

    async def ensure_owner(self, realm_id: int, email: str, full_name: str) -> OwnerRecord:
        self.calls.append("owner")
        if self.owner is None:
            self.owner = OwnerRecord(
                created=True, role="owner", can_create_users=False, api_key=OWNER_KEY
            )
            return self.owner
        return self.owner.model_copy(update={"created": False})

    async def change_role(self, realm_id: int, email: str, role: str) -> None:
        self.calls.append(f"role {role}")
        assert self.owner is not None
        if role == "can_create_users":
            self.owner = self.owner.model_copy(update={"can_create_users": True})
        else:
            self.owner = self.owner.model_copy(update={"role": role})

    async def realm_state(self, realm_id: int) -> RealmState:
        self.calls.append("state")
        rules = self.chat.realm_settings
        groups: dict[str, str | None] = {
            k: NAMES[json.loads(rules[k])["new"]] if k in rules else "role:members"
            for k in GROUP_RULES
        }
        oidc_only = "authentication_methods" in rules
        return RealmState(
            name="Tessaro",
            invite_required="invite_required" in rules,
            authentication_methods={"Email": not oidc_only, "OpenID Connect": True},
            groups=groups,
            system_groups=SYSTEM_GROUPS,
        )


def admin_for(server: FakeServer) -> AdminFactory:
    """Opens the server's fake `ZulipAdmin`, checking the owner's email and key."""

    @asynccontextmanager
    async def open_admin(email: str, api_key: str) -> AsyncIterator[FakeZulipAdmin]:
        assert (email, api_key) == (OWNER_EMAIL, OWNER_KEY)
        yield server.chat

    return open_admin


@pytest.fixture
def zulip_server() -> FakeServer:
    """A Zulip server with no realm yet."""
    return FakeServer()


@pytest.fixture
def owner_admin(zulip_server: FakeServer) -> AdminFactory:
    """Opens ``zulip_server``'s fake `ZulipAdmin` as the owner."""
    return admin_for(zulip_server)
