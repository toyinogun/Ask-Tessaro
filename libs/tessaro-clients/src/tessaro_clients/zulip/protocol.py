"""`ZulipAdmin`: what the seed and the identity tools need from Zulip, as the realm owner."""

from collections.abc import Iterable
from typing import Protocol

from tessaro_clients.zulip.models import Channel, ChatUser, NewChatUser


class ZulipAdmin(Protocol):
    """Users, channels and subscriptions. Every method raises ApiError or Unreachable on failure.

    Built with the owner's credentials it is the admin view; built with the bot's credentials,
    ``list_users`` is the user list as the bot sees it (AC-16).
    """

    async def realm_exists(self) -> bool:
        """True when the site's root domain holds a realm (before `just zulip-bootstrap`, False)."""
        ...

    async def list_users(self) -> tuple[ChatUser, ...]:
        """Every user, deactivated ones included, sorted by user_id."""
        ...

    async def create_user(self, user: NewChatUser) -> int:
        """Create a user and return its user_id (needs the `can_create_users` right)."""
        ...

    async def update_user(self, user_id: int, *, full_name: str) -> None:
        """Change a user's full name."""
        ...

    async def deactivate_user(self, user_id: int) -> None:
        """Deactivate a user, ending their sessions."""
        ...

    async def reactivate_user(self, user_id: int) -> None:
        """Reactivate a deactivated user."""
        ...

    async def list_channels(self) -> tuple[Channel, ...]:
        """Every channel the caller can see, sorted by name."""
        ...

    async def create_channel(self, name: str, description: str) -> None:
        """Create a public channel with this description."""
        ...

    async def channel_subscribers(self, stream_id: int) -> frozenset[int]:
        """The user_ids subscribed to a channel."""
        ...

    async def subscribe(self, channel: str, user_ids: Iterable[int]) -> None:
        """Subscribe these users to the channel."""
        ...

    async def unsubscribe(self, channel: str, user_ids: Iterable[int]) -> None:
        """Unsubscribe these users from the channel."""
        ...
