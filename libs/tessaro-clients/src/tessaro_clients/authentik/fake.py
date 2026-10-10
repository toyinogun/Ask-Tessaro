"""In memory `AuthentikDirectory` for unit tests, seeded from the dataset's Authentik export.

It holds state like the real system does, so a test can run the seed twice and look at what the
second run wrote. Every write is appended to `writes`; `broken` names methods that fail with a
500, the way a real outage would surface.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from tessaro_clients.authentik.models import (
    EMPLOYEE_ID,
    DirectoryGroup,
    DirectoryUser,
    NewUser,
    UserChange,
)
from tessaro_clients.errors import ApiError
from tessaro_dataset.exports.authentik import AuthentikExport

SYSTEM = "authentik"


@dataclass
class FakeAuthentikDirectory:
    """Users and groups in dicts; mutable on purpose, because it stands in for a remote system."""

    users: dict[int, DirectoryUser] = field(default_factory=dict)
    groups: dict[str, DirectoryGroup] = field(default_factory=dict)
    passwords: dict[int, str] = field(default_factory=dict)
    writes: list[str] = field(default_factory=list)
    broken: frozenset[str] = frozenset()

    @classmethod
    def with_groups(cls, names: Iterable[str]) -> "FakeAuthentikDirectory":
        """A directory holding only these groups, the state the blueprints leave behind."""
        groups = {f"g-{name}": DirectoryGroup(pk=f"g-{name}", name=name) for name in names}
        return cls(groups=groups)

    @classmethod
    def from_export(
        cls, export: AuthentikExport, *, users: bool = False
    ) -> "FakeAuthentikDirectory":
        """The export's groups, and with ``users`` its people too (an already seeded system)."""
        directory = cls.with_groups(g.name for g in export.groups)
        if users:
            for pk, user in enumerate(export.users, start=1):
                directory.users[pk] = DirectoryUser(
                    pk=pk,
                    username=user.username,
                    name=user.name,
                    email=user.email,
                    is_active=user.is_active,
                    attributes={EMPLOYEE_ID: user.employee_id},
                    groups=user.groups,
                )
        return directory

    def add_user(
        self,
        username: str,
        *,
        employee_id: str | None = None,
        groups: Iterable[str] = (),
        is_active: bool = True,
    ) -> int:
        """Put a user in directly (setup, not a write) and return its pk."""
        pk = max(self.users, default=0) + 1
        self.users[pk] = DirectoryUser(
            pk=pk,
            username=username,
            name=username,
            email=f"{username}@tessaro.example",
            is_active=is_active,
            attributes={EMPLOYEE_ID: employee_id} if employee_id else {},
            groups=tuple(sorted(groups)),
        )
        return pk

    def _check(self, method: str) -> None:
        if method in self.broken:
            raise ApiError(SYSTEM, method, 500, "broken in the fake")

    def _write(self, method: str, detail: str) -> None:
        self._check(method)
        self.writes.append(f"{method} {detail}")

    def _group(self, group_pk: str) -> DirectoryGroup:
        if group_pk not in self.groups:
            raise ApiError(SYSTEM, "group", 404, group_pk)
        return self.groups[group_pk]

    def _user(self, pk: int) -> DirectoryUser:
        if pk not in self.users:
            raise ApiError(SYSTEM, "user", 404, str(pk))
        return self.users[pk]

    async def list_users(self) -> tuple[DirectoryUser, ...]:
        """Every user, sorted by pk."""
        self._check("list_users")
        return tuple(self.users[pk] for pk in sorted(self.users))

    async def get_user_by_email(self, email: str) -> DirectoryUser | None:
        """The user with this email, or None."""
        self._check("get_user_by_email")
        return next((u for u in self.users.values() if u.email == email), None)

    async def list_groups(self) -> tuple[DirectoryGroup, ...]:
        """Every group, sorted by name."""
        self._check("list_groups")
        return tuple(sorted(self.groups.values(), key=lambda g: g.name))

    async def create_user(self, user: NewUser) -> DirectoryUser:
        """Create a user; a taken username is a 400 like the real API."""
        self._write("create_user", user.username)
        if any(u.username == user.username for u in self.users.values()):
            raise ApiError(SYSTEM, "create_user", 400, f"username {user.username} is taken")
        pk = max(self.users, default=0) + 1
        self.users[pk] = DirectoryUser(pk=pk, **user.model_dump())
        return self.users[pk]

    async def update_user(self, pk: int, change: UserChange) -> DirectoryUser:
        """Apply the fields that are set."""
        self._write("update_user", str(pk))
        updated = self._user(pk).model_copy(update=change.model_dump(exclude_none=True))
        self.users[pk] = updated
        return updated

    async def set_password(self, pk: int, password: str) -> None:
        """Remember the password so a test can check it."""
        self._write("set_password", str(pk))
        self._user(pk)
        self.passwords[pk] = password

    async def add_to_group(self, group_pk: str, user_pk: int) -> None:
        """Add the group's name to the user's groups."""
        self._write("add_to_group", f"{group_pk} {user_pk}")
        name = self._group(group_pk).name
        user = self._user(user_pk)
        self.users[user_pk] = user.model_copy(
            update={"groups": tuple(sorted({*user.groups, name}))}
        )

    async def remove_from_group(self, group_pk: str, user_pk: int) -> None:
        """Drop the group's name from the user's groups."""
        self._write("remove_from_group", f"{group_pk} {user_pk}")
        name = self._group(group_pk).name
        user = self._user(user_pk)
        self.users[user_pk] = user.model_copy(
            update={"groups": tuple(g for g in user.groups if g != name)}
        )
