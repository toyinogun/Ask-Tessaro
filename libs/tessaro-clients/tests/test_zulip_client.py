"""HttpZulipAdmin against a mock Zulip `/api/v1/`."""

import base64
import json
from collections.abc import Callable
from urllib.parse import parse_qs

import httpx
import pytest

from tessaro_clients.errors import ApiError
from tessaro_clients.zulip import HttpZulipAdmin, NewChatUser, zulip_http

# Stands in for the random password the seed sends; any string will do.
RANDOM = "r4nd0m"

Handler = Callable[[httpx.Request], httpx.Response]


def ok(**body: object) -> httpx.Response:
    return httpx.Response(200, json={"result": "success", "msg": "", **body})


def admin(handler: Handler) -> HttpZulipAdmin:
    transport = httpx.MockTransport(handler)
    return HttpZulipAdmin(zulip_http("https://chat.example/", "a@x", "key", transport=transport))


def form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


async def test_calls_use_basic_auth_under_api_v1() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/users"
        assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"a@x:key").decode()
        member = {"user_id": 7, "email": "e@x", "full_name": "E", "is_active": False}
        bot = {**member, "user_id": 3, "delivery_email": "b@x", "is_bot": True, "is_active": True}
        return ok(members=[member, bot])

    users = await admin(handler).list_users()
    assert [u.user_id for u in users] == [3, 7]
    assert users[0].real_email == "b@x"
    assert users[1].real_email == "e@x"


async def test_realm_exists_reads_server_settings_without_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        return ok(realm_name="Tessaro")

    assert await admin(handler).realm_exists() is True


async def test_no_realm_name_means_no_realm() -> None:
    assert await admin(lambda r: ok(zulip_version="12.3")).realm_exists() is False


async def test_create_user_returns_the_new_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert form(request) == {"email": "n@x", "full_name": "N", "password": RANDOM}
        return ok(user_id=42)

    new = NewChatUser(email="n@x", full_name="N", password=RANDOM)
    assert await admin(handler).create_user(new) == 42


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PATCH", "/api/v1/users/5"),
        ("DELETE", "/api/v1/users/5"),
        ("POST", "/api/v1/users/5/reactivate"),
    ],
)
async def test_user_writes_hit_their_endpoint(method: str, path: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert (request.method, request.url.path) == (method, path)
        if method == "PATCH":
            assert form(request) == {"full_name": "New"}
        return ok()

    client = admin(handler)
    if method == "PATCH":
        await client.update_user(5, full_name="New")
    elif method == "DELETE":
        await client.deactivate_user(5)
    else:
        await client.reactivate_user(5)


async def test_channels_are_sorted() -> None:
    streams = [{"stream_id": 2, "name": "zz"}, {"stream_id": 1, "name": "aa", "description": "d"}]
    channels = await admin(lambda r: ok(streams=streams)).list_channels()
    assert [(c.name, c.description) for c in channels] == [("aa", "d"), ("zz", "")]


async def test_create_channel_subscribes_the_caller_with_a_description() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/users/me/subscriptions"
        assert json.loads(form(request)["subscriptions"]) == [{"name": "c", "description": "d"}]
        return ok()

    await admin(handler).create_channel("c", "d")


async def test_subscribers_are_read() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/streams/9/members"
        return ok(subscribers=[3, 1])

    assert await admin(handler).channel_subscribers(9) == frozenset({1, 3})


async def test_subscribe_sends_principals() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = form(request)
        assert json.loads(body["subscriptions"]) == [{"name": "c"}]
        assert json.loads(body["principals"]) == [1, 2]
        return ok()

    await admin(handler).subscribe("c", [2, 1])


async def test_unsubscribe_sends_principals_as_query() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert json.loads(request.url.params["subscriptions"]) == ["c"]
        assert json.loads(request.url.params["principals"]) == [4]
        return ok()

    await admin(handler).unsubscribe("c", [4])


async def test_an_answer_that_is_not_success_is_an_api_error() -> None:
    with pytest.raises(ApiError, match="not a success"):
        await admin(lambda r: httpx.Response(200, json={"result": "error"})).list_users()


async def test_an_error_status_carries_zulips_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"result": "error", "msg": "Email is already in use."})

    with pytest.raises(ApiError, match="already in use"):
        await admin(handler).create_user(NewChatUser(email="n@x", full_name="N", password=RANDOM))


async def test_update_realm_patches_the_realm_with_form_values() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert (request.method, request.url.path) == ("PATCH", "/api/v1/realm")
        assert form(request) == {"invite_required": "true", "name": "Tessaro"}
        return ok()

    await admin(handler).update_realm({"invite_required": "true", "name": "Tessaro"})
