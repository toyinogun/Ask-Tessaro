"""The bootstrap use case against the in memory Zulip server and fake `ZulipAdmin` (conftest)."""

from typing import Any

import pytest

from tessaro_seed.zulip_bootstrap.bootstrap import AdminFactory, bootstrap, render
from tessaro_seed.zulip_bootstrap.realm import (
    GROUP_RULES,
    OWNER_EMAIL,
    USER_DEFAULTS,
    BootstrapError,
)

# Any: the conftest's FakeServer (test modules cannot import conftest under importlib mode).
Server = Any
KEY = "owner-api-key"


async def test_a_fresh_server_gets_every_step_in_order(
    zulip_server: Server, owner_admin: AdminFactory
) -> None:
    server = zulip_server
    result = await bootstrap(server, owner_admin)
    assert server.calls == ["realm", "defaults", "owner", "role can_create_users", "state"]
    assert server.defaults == USER_DEFAULTS
    assert result.admin_email == OWNER_EMAIL
    assert result.admin_api_key == KEY
    assert set(server.chat.realm_settings) == {
        "authentication_methods",
        "invite_required",
        *GROUP_RULES,
    }
    assert all(step.changed for step in result.steps)


async def test_a_second_run_changes_nothing_and_reads_the_same_key(
    zulip_server: Server, owner_admin: AdminFactory
) -> None:
    server = zulip_server
    await bootstrap(server, owner_admin)
    writes = len(server.chat.writes)
    server.calls.clear()
    result = await bootstrap(server, owner_admin)
    assert server.calls == ["realm", "defaults", "owner", "state"]
    assert len(server.chat.writes) == writes
    assert not any(step.changed for step in result.steps)
    assert result.admin_api_key == KEY


async def test_a_demoted_owner_is_made_owner_again(
    zulip_server: Server, owner_admin: AdminFactory
) -> None:
    server = zulip_server
    await bootstrap(server, owner_admin)
    assert server.owner is not None
    server.owner = server.owner.model_copy(update={"role": "member"})
    server.calls.clear()
    result = await bootstrap(server, owner_admin)
    assert "role owner" in server.calls
    assert f"owner {OWNER_EMAIL}: changed" in render(result)


async def test_a_server_that_is_not_ready_stops_before_any_step(
    zulip_server: Server, owner_admin: AdminFactory
) -> None:
    server = zulip_server
    server.ready_ = False
    with pytest.raises(BootstrapError, match="not ready"):
        await bootstrap(server, owner_admin)
    assert server.calls == []


async def test_render_lists_each_step_without_the_key(
    zulip_server: Server, owner_admin: AdminFactory
) -> None:
    server = zulip_server
    result = await bootstrap(server, owner_admin)
    text = render(result)
    assert "realm Tessaro: created" in text
    assert "realm rules: changed" in text
    assert KEY not in text
