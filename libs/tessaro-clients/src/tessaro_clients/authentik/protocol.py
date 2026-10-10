"""`AuthentikDirectory`: what the seed, the adapter and the identity tools need from Authentik."""

from typing import Protocol

from tessaro_clients.authentik.models import DirectoryGroup, DirectoryUser, NewUser, UserChange


class AuthentikDirectory(Protocol):
    """Users and groups in Authentik. Every method raises ApiError or Unreachable on failure."""

    async def list_users(self) -> tuple[DirectoryUser, ...]:
        """Every user (every page), with attributes and group names, sorted by pk."""
        ...

    async def get_user_by_email(self, email: str) -> DirectoryUser | None:
        """The user with exactly this email, or None."""
        ...

    async def list_groups(self) -> tuple[DirectoryGroup, ...]:
        """Every group (every page), sorted by name."""
        ...

    async def create_user(self, user: NewUser) -> DirectoryUser:
        """Create an internal user and return it as stored."""
        ...

    async def update_user(self, pk: int, change: UserChange) -> DirectoryUser:
        """Apply a partial update and return the user as stored."""
        ...

    async def set_password(self, pk: int, password: str) -> None:
        """Set the user's password."""
        ...

    async def add_to_group(self, group_pk: str, user_pk: int) -> None:
        """Make the user a direct member of the group (no change if it already is)."""
        ...

    async def remove_from_group(self, group_pk: str, user_pk: int) -> None:
        """End the user's direct membership of the group (no change if it is not a member)."""
        ...
