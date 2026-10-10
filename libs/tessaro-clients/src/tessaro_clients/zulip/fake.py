"""In memory `ZulipAdmin` for unit tests, seeded from the dataset's Zulip export.

Holds state like the real system, appends every write to `writes`, and fails a method named in
`broken` with a 500. ``realm`` False models a server before `just zulip-bootstrap`.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from tessaro_clients.errors import ApiError
from tessaro_clients.zulip.models import Channel, ChatUser, NewChatUser
from tessaro_dataset.exports.zulip import ZulipExport

SYSTEM = "zulip"


@dataclass
class FakeZulipAdmin:
    """Users, channels and subscriptions in dicts; mutable on purpose (it stands in for Zulip)."""

    realm: bool = True
    users: dict[int, ChatUser] = field(default_factory=dict)
    channels: dict[int, Channel] = field(default_factory=dict)
    subscribers: dict[int, set[int]] = field(default_factory=dict)
    passwords: dict[int, str] = field(default_factory=dict)
    writes: list[str] = field(default_factory=list)
    broken: frozenset[str] = frozenset()
    hide_emails: bool = False

    @classmethod
    def from_export(cls, export: ZulipExport, *, people: bool = False) -> "FakeZulipAdmin":
        """A realm; with ``people`` the export's users, channels and subscriptions are in it."""
        chat = cls()
        if people:
            for user in export.users:
                chat.add_user(user.email, user.full_name)
            for channel in export.channels:
                chat.add_channel(channel.name, channel.description)
            ids = {u.real_email: u.user_id for u in chat.users.values()}
            names = {c.name: c.stream_id for c in chat.channels.values()}
            for sub in export.subscriptions:
                chat.subscribers[names[sub.channel]].add(ids[sub.email])
        return chat

    def add_user(self, email: str, full_name: str, *, is_bot: bool = False) -> int:
        """Put a user in directly (setup, not a write)."""
        user_id = max(self.users, default=100) + 1
        self.users[user_id] = ChatUser(
            user_id=user_id,
            email=email,
            delivery_email=email,
            full_name=full_name,
            is_active=True,
            is_bot=is_bot,
        )
        return user_id

    def add_channel(self, name: str, description: str = "") -> int:
        """Put a channel in directly (setup, not a write)."""
        stream_id = max(self.channels, default=0) + 1
        self.channels[stream_id] = Channel(stream_id=stream_id, name=name, description=description)
        self.subscribers[stream_id] = set()
        return stream_id

    def subscribed(self, channel: str) -> frozenset[str]:
        """Real emails of the channel's subscribers (for assertions)."""
        stream_id = self._channel(channel).stream_id
        return frozenset(self.users[i].real_email for i in self.subscribers[stream_id])

    def _check(self, method: str) -> None:
        if method in self.broken:
            raise ApiError(SYSTEM, method, 500, "broken in the fake")
        if not self.realm and method != "realm_exists":
            raise ApiError(SYSTEM, method, 401, "no realm on this domain")

    def _write(self, method: str, detail: str) -> None:
        self._check(method)
        self.writes.append(f"{method} {detail}")

    def _user(self, user_id: int) -> ChatUser:
        if user_id not in self.users:
            raise ApiError(SYSTEM, "user", 404, str(user_id))
        return self.users[user_id]

    def _channel(self, name: str) -> Channel:
        found = next((c for c in self.channels.values() if c.name == name), None)
        if found is None:
            raise ApiError(SYSTEM, "channel", 400, f"no channel {name}")
        return found

    async def realm_exists(self) -> bool:
        """Whether the realm was created."""
        self._check("realm_exists")
        return self.realm

    async def list_users(self) -> tuple[ChatUser, ...]:
        """Every user; with ``hide_emails`` the view of a realm that hides addresses."""
        self._check("list_users")
        users = (self.users[i] for i in sorted(self.users))
        if self.hide_emails:
            return tuple(
                u.model_copy(
                    update={"email": f"user{u.user_id}@chat.example", "delivery_email": None}
                )
                for u in users
            )
        return tuple(users)

    async def create_user(self, user: NewChatUser) -> int:
        """Create a user; a taken email is a 400 like the real API."""
        self._write("create_user", user.email)
        if any(u.real_email == user.email for u in self.users.values()):
            raise ApiError(SYSTEM, "create_user", 400, f"email {user.email} is in use")
        user_id = self.add_user(user.email, user.full_name)
        self.passwords[user_id] = user.password
        return user_id

    async def update_user(self, user_id: int, *, full_name: str) -> None:
        """Rename a user."""
        self._write("update_user", str(user_id))
        self.users[user_id] = self._user(user_id).model_copy(update={"full_name": full_name})

    async def deactivate_user(self, user_id: int) -> None:
        """Mark a user inactive."""
        self._write("deactivate_user", str(user_id))
        self.users[user_id] = self._user(user_id).model_copy(update={"is_active": False})

    async def reactivate_user(self, user_id: int) -> None:
        """Mark a user active."""
        self._write("reactivate_user", str(user_id))
        self.users[user_id] = self._user(user_id).model_copy(update={"is_active": True})

    async def list_channels(self) -> tuple[Channel, ...]:
        """Every channel, sorted by name."""
        self._check("list_channels")
        return tuple(sorted(self.channels.values(), key=lambda c: c.name))

    async def create_channel(self, name: str, description: str) -> None:
        """Create a channel."""
        self._write("create_channel", name)
        self.add_channel(name, description)

    async def channel_subscribers(self, stream_id: int) -> frozenset[int]:
        """Subscriber ids of a channel."""
        self._check("channel_subscribers")
        return frozenset(self.subscribers[stream_id])

    async def subscribe(self, channel: str, user_ids: Iterable[int]) -> None:
        """Add subscribers."""
        ids = sorted(user_ids)
        self._write("subscribe", f"{channel} {ids}")
        self.subscribers[self._channel(channel).stream_id].update(ids)

    async def unsubscribe(self, channel: str, user_ids: Iterable[int]) -> None:
        """Remove subscribers."""
        ids = sorted(user_ids)
        self._write("unsubscribe", f"{channel} {ids}")
        self.subscribers[self._channel(channel).stream_id].difference_update(ids)
