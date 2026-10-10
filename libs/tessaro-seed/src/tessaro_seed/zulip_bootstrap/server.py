"""`ZulipServer`: what the bootstrap needs from inside the Zulip server (its `manage.py`)."""

from typing import Protocol

from tessaro_seed.zulip_bootstrap.realm import OwnerRecord, RealmState


class ZulipServer(Protocol):
    """Steps that only the server can do, each idempotent. Every method raises BootstrapError."""

    async def ready(self) -> bool:
        """True when the server pod is running and ready."""
        ...

    async def ensure_realm(self, name: str, string_id: str) -> tuple[int, bool]:
        """Create the realm when missing; return its id and whether this call created it."""
        ...

    async def ensure_user_defaults(self, realm_id: int, defaults: dict[str, int | bool]) -> bool:
        """Set the realm's user defaults; True when any value changed."""
        ...

    async def ensure_owner(self, realm_id: int, email: str, full_name: str) -> OwnerRecord:
        """Create the owner (no usable password) when missing; return it with its API key."""
        ...

    async def change_role(self, realm_id: int, email: str, role: str) -> None:
        """Run `manage.py change_user_role` (a role, or a right such as `can_create_users`)."""
        ...

    async def realm_state(self, realm_id: int) -> RealmState:
        """The realm's name, auth methods, invitation rule and permission groups."""
        ...
