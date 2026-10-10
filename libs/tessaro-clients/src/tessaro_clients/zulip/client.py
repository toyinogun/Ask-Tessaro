"""`HttpZulipAdmin`: the real client, over Zulip's `/api/v1/` with an email and API key."""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import httpx

from tessaro_clients.errors import ApiError
from tessaro_clients.http import Json, call_json
from tessaro_clients.zulip.models import Channel, ChatUser, NewChatUser

SYSTEM = "zulip"


def zulip_http(
    site: str,
    email: str,
    api_key: str,
    *,
    timeout: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """An AsyncClient for ``<site>/api/v1/`` with HTTP basic auth (email and API key)."""
    return httpx.AsyncClient(
        base_url=f"{site.rstrip('/')}/api/v1/",
        auth=httpx.BasicAuth(email, api_key),
        timeout=timeout,
        transport=transport,
    )


def _user(raw: Json) -> ChatUser:
    return ChatUser(
        user_id=raw["user_id"],
        email=raw["email"],
        delivery_email=raw.get("delivery_email"),
        full_name=raw["full_name"],
        is_active=raw["is_active"],
        is_bot=raw.get("is_bot", False),
    )


@dataclass(frozen=True)
class HttpZulipAdmin:
    """Calls Zulip as the user its client authenticates as; no retries."""

    http: httpx.AsyncClient

    async def _call(
        self,
        method: str,
        path: str,
        *,
        data: Mapping[str, str] | None = None,
        params: Mapping[str, str | int] | None = None,
    ) -> Json:
        body = await call_json(self.http, SYSTEM, method, path, data=data, params=params)
        if not isinstance(body, dict) or body.get("result") != "success":
            raise ApiError(SYSTEM, f"{method} {path}", 200, "the answer is not a success")
        return body

    async def realm_exists(self) -> bool:
        """`server_settings` names the realm only when the root domain holds one."""
        body = await call_json(self.http, SYSTEM, "GET", "server_settings", auth=_NO_AUTH)
        return isinstance(body, dict) and bool(body.get("realm_name"))

    async def list_users(self) -> tuple[ChatUser, ...]:
        """GET /users, sorted by user_id."""
        body = await self._call("GET", "users")
        return tuple(sorted((_user(m) for m in body["members"]), key=lambda u: u.user_id))

    async def create_user(self, user: NewChatUser) -> int:
        """POST /users; Zulip answers with the new user_id."""
        body = await self._call("POST", "users", data=user.model_dump())
        return int(body["user_id"])

    async def update_user(self, user_id: int, *, full_name: str) -> None:
        """PATCH /users/{id} with the new full name."""
        await self._call("PATCH", f"users/{user_id}", data={"full_name": full_name})

    async def deactivate_user(self, user_id: int) -> None:
        """DELETE /users/{id}."""
        await self._call("DELETE", f"users/{user_id}")

    async def reactivate_user(self, user_id: int) -> None:
        """POST /users/{id}/reactivate."""
        await self._call("POST", f"users/{user_id}/reactivate")

    async def list_channels(self) -> tuple[Channel, ...]:
        """GET /streams (public ones and the caller's), sorted by name."""
        body = await self._call("GET", "streams")
        channels = (
            Channel(stream_id=s["stream_id"], name=s["name"], description=s.get("description", ""))
            for s in body["streams"]
        )
        return tuple(sorted(channels, key=lambda c: c.name))

    async def create_channel(self, name: str, description: str) -> None:
        """Subscribing the caller to a missing channel creates it, public, with the description."""
        subscriptions = json.dumps([{"name": name, "description": description}])
        await self._call("POST", "users/me/subscriptions", data={"subscriptions": subscriptions})

    async def channel_subscribers(self, stream_id: int) -> frozenset[int]:
        """GET /streams/{id}/members."""
        body = await self._call("GET", f"streams/{stream_id}/members")
        return frozenset(int(i) for i in body["subscribers"])

    async def subscribe(self, channel: str, user_ids: Iterable[int]) -> None:
        """POST /users/me/subscriptions with the users as principals."""
        data = {
            "subscriptions": json.dumps([{"name": channel}]),
            "principals": json.dumps(sorted(user_ids)),
        }
        await self._call("POST", "users/me/subscriptions", data=data)

    async def unsubscribe(self, channel: str, user_ids: Iterable[int]) -> None:
        """DELETE /users/me/subscriptions with the users as principals."""
        params = {
            "subscriptions": json.dumps([channel]),
            "principals": json.dumps(sorted(user_ids)),
        }
        await self._call("DELETE", "users/me/subscriptions", params=params)


class _NoAuth(httpx.Auth):
    """`server_settings` is public; sending the key there is needless."""


_NO_AUTH = _NoAuth()
