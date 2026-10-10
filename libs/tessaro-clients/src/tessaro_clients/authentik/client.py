"""`HttpAuthentikDirectory`: the real client, over Authentik's `/api/v3/` with an API token."""

from dataclasses import dataclass

import httpx

from tessaro_clients.authentik.models import DirectoryGroup, DirectoryUser, NewUser, UserChange
from tessaro_clients.errors import ApiError
from tessaro_clients.http import Json, call_json

SYSTEM = "authentik"
PAGE_SIZE = 100


def authentik_http(
    base_url: str,
    token: str,
    *,
    timeout: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """An AsyncClient for ``<base_url>/api/v3/`` sending the token as a bearer credential."""
    return httpx.AsyncClient(
        base_url=f"{base_url.rstrip('/')}/api/v3/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
        transport=transport,
    )


def _user(raw: Json) -> DirectoryUser:
    return DirectoryUser(
        pk=raw["pk"],
        username=raw["username"],
        name=raw.get("name", ""),
        email=raw.get("email", ""),
        is_active=raw["is_active"],
        type=raw.get("type", "internal"),
        attributes=raw.get("attributes") or {},
        groups=tuple(sorted(g["name"] for g in raw.get("groups_obj") or ())),
    )


def _group(raw: Json) -> DirectoryGroup:
    return DirectoryGroup(pk=raw["pk"], name=raw["name"], attributes=raw.get("attributes") or {})


@dataclass(frozen=True)
class HttpAuthentikDirectory:
    """Calls Authentik with the token its client was built with; no retries."""

    http: httpx.AsyncClient

    async def _call(self, method: str, path: str, **kwargs: Json) -> Json:
        return await call_json(self.http, SYSTEM, method, path, **kwargs)

    async def _pages(self, path: str, params: dict[str, str | int]) -> list[Json]:
        results: list[Json] = []
        page = 1
        while page:
            body = await self._call(
                "GET", path, params={**params, "page": page, "page_size": PAGE_SIZE}
            )
            if not isinstance(body, dict) or "results" not in body:
                raise ApiError(SYSTEM, f"GET {path}", 200, "no results in the page")
            results.extend(body["results"])
            page = int(body.get("pagination", {}).get("next") or 0)
        return results

    async def list_users(self) -> tuple[DirectoryUser, ...]:
        """Every user with group names (``include_groups``), sorted by pk."""
        raw = await self._pages("core/users/", {"include_groups": "true"})
        return tuple(sorted((_user(u) for u in raw), key=lambda u: u.pk))

    async def get_user_by_email(self, email: str) -> DirectoryUser | None:
        """The user whose email is exactly ``email`` (the API filter is exact)."""
        raw = await self._pages("core/users/", {"email": email, "include_groups": "true"})
        return next((_user(u) for u in raw if u.get("email") == email), None)

    async def list_groups(self) -> tuple[DirectoryGroup, ...]:
        """Every group without its member list, sorted by name."""
        raw = await self._pages("core/groups/", {"include_users": "false"})
        return tuple(sorted((_group(g) for g in raw), key=lambda g: g.name))

    async def create_user(self, user: NewUser) -> DirectoryUser:
        """POST an internal user."""
        body = {**user.model_dump(), "type": "internal"}
        return _user(await self._call("POST", "core/users/", json=body))

    async def update_user(self, pk: int, change: UserChange) -> DirectoryUser:
        """PATCH only the fields that are set."""
        body = change.model_dump(exclude_none=True)
        return _user(await self._call("PATCH", f"core/users/{pk}/", json=body))

    async def set_password(self, pk: int, password: str) -> None:
        """POST the new password; Authentik answers 204."""
        await self._call("POST", f"core/users/{pk}/set_password/", json={"password": password})

    async def add_to_group(self, group_pk: str, user_pk: int) -> None:
        """POST the user's pk to the group's add_user action."""
        await self._call("POST", f"core/groups/{group_pk}/add_user/", json={"pk": user_pk})

    async def remove_from_group(self, group_pk: str, user_pk: int) -> None:
        """POST the user's pk to the group's remove_user action."""
        await self._call("POST", f"core/groups/{group_pk}/remove_user/", json={"pk": user_pk})
