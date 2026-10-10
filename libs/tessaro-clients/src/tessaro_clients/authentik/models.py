"""Authentik records as the directory protocol sees them: users, groups and the writes on them."""

from pydantic import BaseModel, ConfigDict, JsonValue

EMPLOYEE_ID = "employee_id"


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DirectoryUser(_Record):
    """A user with its attributes and the names of the groups it is a direct member of."""

    pk: int
    username: str
    name: str
    email: str
    is_active: bool
    type: str = "internal"
    attributes: dict[str, JsonValue] = {}
    groups: tuple[str, ...] = ()

    @property
    def employee_id(self) -> str | None:
        """`attributes.employee_id` when it is a string, else None (admins, service accounts)."""
        value = self.attributes.get(EMPLOYEE_ID)
        return value if isinstance(value, str) else None


class DirectoryGroup(_Record):
    """A group, keyed by its UUID primary key; its name is unique too."""

    pk: str
    name: str
    attributes: dict[str, JsonValue] = {}


class NewUser(_Record):
    """An internal user to create, without groups or a password (set separately)."""

    username: str
    name: str
    email: str
    is_active: bool = True
    attributes: dict[str, JsonValue] = {}


class UserChange(_Record):
    """A partial update: only the fields that are not None are sent."""

    username: str | None = None
    name: str | None = None
    email: str | None = None
    is_active: bool | None = None
    attributes: dict[str, JsonValue] | None = None
