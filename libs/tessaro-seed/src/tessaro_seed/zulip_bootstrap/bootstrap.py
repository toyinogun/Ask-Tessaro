"""The bootstrap use case: realm, user defaults, owner, then realm rules (spec 0008 AC-11).

Steps 1 to 3 run inside the server (`ZulipServer`); step 4 goes through Zulip's API as the owner.
Every step reads before it writes, so a second run changes nothing and returns the same key.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from tessaro_clients.zulip import ZulipAdmin
from tessaro_seed.zulip_bootstrap.realm import (
    CREATE_USERS,
    OWNER_EMAIL,
    OWNER_NAME,
    OWNER_ROLE,
    REALM_NAME,
    STRING_ID,
    USER_DEFAULTS,
    BootstrapError,
    realm_changes,
)
from tessaro_seed.zulip_bootstrap.server import ZulipServer

# Opens a `ZulipAdmin` as the given email and API key (the owner, once step 3 has run).
AdminFactory = Callable[[str, str], AbstractAsyncContextManager[ZulipAdmin]]


CREATED = "created"
CHANGED = "changed"
UNCHANGED = "unchanged"


@dataclass(frozen=True)
class Step:
    """One bootstrap step and what this run did to it: created, changed or unchanged."""

    name: str
    outcome: str

    @property
    def changed(self) -> bool:
        """True unless the step was already in place."""
        return self.outcome != UNCHANGED


def _outcome(*, created: bool = False, changed: bool = False) -> str:
    return CREATED if created else CHANGED if changed else UNCHANGED


@dataclass(frozen=True)
class BootstrapResult:
    """The steps in order, and the owner credentials the command writes into `.env`."""

    steps: tuple[Step, ...]
    admin_email: str
    admin_api_key: str


async def _owner(server: ZulipServer, realm_id: int) -> tuple[str, str]:
    owner = await server.ensure_owner(realm_id, OWNER_EMAIL, OWNER_NAME)
    changed = False
    if owner.role != OWNER_ROLE:
        await server.change_role(realm_id, OWNER_EMAIL, OWNER_ROLE)
        changed = True
    if not owner.can_create_users:
        await server.change_role(realm_id, OWNER_EMAIL, CREATE_USERS)
        changed = True
    return owner.api_key, _outcome(created=owner.created, changed=changed)


async def bootstrap(server: ZulipServer, admin: AdminFactory) -> BootstrapResult:
    """Bring Zulip to the AC-11 state (steps 1 to 4); raise BootstrapError on the first failure."""
    if not await server.ready():
        raise BootstrapError("the Zulip server pod is not ready")
    realm_id, created = await server.ensure_realm(REALM_NAME, STRING_ID)
    defaults_changed = await server.ensure_user_defaults(realm_id, USER_DEFAULTS)
    api_key, owner_outcome = await _owner(server, realm_id)
    changes = realm_changes(await server.realm_state(realm_id))
    if changes:
        async with admin(OWNER_EMAIL, api_key) as owner:
            await owner.update_realm(changes)
    steps = (
        Step(f"realm {REALM_NAME}", _outcome(created=created)),
        Step("realm user defaults", _outcome(changed=defaults_changed)),
        Step(f"owner {OWNER_EMAIL}", owner_outcome),
        Step("realm rules", _outcome(changed=bool(changes))),
    )
    return BootstrapResult(steps=steps, admin_email=OWNER_EMAIL, admin_api_key=api_key)


def render(result: BootstrapResult) -> str:
    """One line per step; never the API key."""
    return "\n".join(f"{step.name}: {step.outcome}" for step in result.steps)
