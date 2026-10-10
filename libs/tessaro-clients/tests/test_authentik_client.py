"""HttpAuthentikDirectory against a mock Authentik `/api/v3/`."""

import json
from collections.abc import Callable

import httpx
import pytest

from tessaro_clients.authentik import HttpAuthentikDirectory, NewUser, UserChange, authentik_http
from tessaro_clients.errors import ApiError

Handler = Callable[[httpx.Request], httpx.Response]


def raw_user(pk: int, *groups: str, employee_id: str | None = "TES-00001") -> dict[str, object]:
    attributes = {"employee_id": employee_id} if employee_id else {}
    return {
        "pk": pk,
        "username": f"u{pk}",
        "name": f"User {pk}",
        "email": f"u{pk}@tessaro.example",
        "is_active": True,
        "type": "internal",
        "attributes": attributes,
        "groups": ["uuid"],
        "groups_obj": [{"pk": f"g-{g}", "name": g} for g in groups],
    }


def page(results: list[object], next_page: int = 0) -> dict[str, object]:
    return {"pagination": {"next": next_page}, "results": results}


def directory(handler: Handler) -> HttpAuthentikDirectory:
    http = authentik_http("https://auth.example/", "tok", transport=httpx.MockTransport(handler))
    return HttpAuthentikDirectory(http)


async def test_list_users_reads_every_page_with_groups_and_the_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.params["page"] == "1":
            return httpx.Response(200, json=page([raw_user(2, "staff", "managers")], next_page=2))
        return httpx.Response(200, json=page([raw_user(1, employee_id=None)]))

    users = await directory(handler).list_users()
    assert [u.pk for u in users] == [1, 2]
    assert users[1].groups == ("managers", "staff")
    assert users[1].employee_id == "TES-00001"
    assert users[0].employee_id is None
    assert seen[0].url.path == "/api/v3/core/users/"
    assert seen[0].url.params["include_groups"] == "true"
    assert seen[0].headers["Authorization"] == "Bearer tok"


async def test_a_page_without_results_is_an_api_error() -> None:
    with pytest.raises(ApiError, match="no results"):
        await directory(lambda r: httpx.Response(200, json={"detail": "x"})).list_users()


async def test_get_user_by_email_filters_and_checks_exactly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["email"] == "u2@tessaro.example"
        return httpx.Response(200, json=page([raw_user(2)]))

    found = await directory(handler).get_user_by_email("u2@tessaro.example")
    assert found is not None
    assert found.pk == 2
    assert await directory(handler).get_user_by_email("u2@tessaro.example") == found


async def test_get_user_by_email_is_none_when_nothing_matches() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page([raw_user(3)]))

    assert await directory(handler).get_user_by_email("nobody@tessaro.example") is None


async def test_list_groups_is_sorted_and_skips_members() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["include_users"] == "false"
        groups = [{"pk": "b", "name": "zeta"}, {"pk": "a", "name": "alpha", "attributes": None}]
        return httpx.Response(200, json=page(groups))

    groups = await directory(handler).list_groups()
    assert [g.name for g in groups] == ["alpha", "zeta"]
    assert groups[0].attributes == {}


async def test_create_user_posts_an_internal_user() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.method == "POST"
        assert body["type"] == "internal"
        assert body["attributes"] == {"employee_id": "TES-00009"}
        return httpx.Response(201, json=raw_user(9, employee_id="TES-00009"))

    new = NewUser(username="u9", name="U", email="u9@x", attributes={"employee_id": "TES-00009"})
    assert (await directory(handler).create_user(new)).pk == 9


async def test_update_user_sends_only_set_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/api/v3/core/users/4/"
        assert json.loads(request.content) == {"is_active": True}
        return httpx.Response(200, json=raw_user(4))

    await directory(handler).update_user(4, UserChange(is_active=True))


@pytest.mark.parametrize(
    ("call", "path", "body"),
    [
        ("set_password", "/api/v3/core/users/4/set_password/", {"password": "pw"}),
        ("add_to_group", "/api/v3/core/groups/g-1/add_user/", {"pk": 4}),
        ("remove_from_group", "/api/v3/core/groups/g-1/remove_user/", {"pk": 4}),
    ],
)
async def test_actions_post_to_their_endpoint(call: str, path: str, body: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == path
        assert json.loads(request.content) == body
        return httpx.Response(204)

    client = directory(handler)
    if call == "set_password":
        await client.set_password(4, "pw")
    elif call == "add_to_group":
        await client.add_to_group("g-1", 4)
    else:
        await client.remove_from_group("g-1", 4)


async def test_a_forbidden_write_surfaces_as_403() -> None:
    client = directory(lambda r: httpx.Response(403, json={"detail": "denied"}))
    with pytest.raises(ApiError) as caught:
        await client.update_user(1, UserChange(name="x"))
    assert caught.value.status == 403


@pytest.mark.parametrize("allowed", [True, False])
async def test_users_can_change_email_reads_the_system_settings(allowed: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert (request.method, request.url.path) == ("GET", "/api/v3/admin/settings/")
        return httpx.Response(200, json={"default_user_change_email": allowed})

    assert await directory(handler).users_can_change_email() is allowed
