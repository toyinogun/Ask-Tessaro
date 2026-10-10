"""Zulip records as the admin protocol sees them: users and channels."""

from pydantic import BaseModel, ConfigDict


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ChatUser(_Record):
    """A user as the caller sees it.

    ``email`` is the public field: the real address only when the realm shows emails to everyone
    (else ``user<id>@...``), and the value Zulip puts in an outgoing webhook's ``sender_email``.
    ``delivery_email`` is the real address, present only when the caller may see it (admins).
    """

    user_id: int
    email: str
    delivery_email: str | None = None
    full_name: str
    is_active: bool
    is_bot: bool = False

    @property
    def real_email(self) -> str:
        """The real address: ``delivery_email`` when visible, else ``email``."""
        return self.delivery_email or self.email


class Channel(_Record):
    """A channel (a Zulip stream)."""

    stream_id: int
    name: str
    description: str = ""


class NewChatUser(_Record):
    """A user to create; the password is random and never stored (email login is off)."""

    email: str
    full_name: str
    password: str
