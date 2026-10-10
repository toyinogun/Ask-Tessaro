"""`KubectlZulipServer`: the kubectl calls it makes and how it reads their answers."""

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from tessaro_seed.zulip_bootstrap.kubectl import (
    MARKER,
    Completed,
    KubectlZulipServer,
    current_context,
    run_process,
)
from tessaro_seed.zulip_bootstrap.realm import GROUP_RULES, USER_DEFAULTS, BootstrapError

CONTEXT = "k3s-test"


@dataclass
class FakeRunner:
    """Answers each call with the next canned result and keeps the args and stdin it got."""

    answers: list[Completed]
    calls: list[tuple[list[str], str | None]] = field(default_factory=list)

    async def __call__(self, args: Sequence[str], stdin: str | None) -> Completed:
        self.calls.append((list(args), stdin))
        return self.answers.pop(0)


def emitted(value: object, noise: str = "85 objects imported automatically\n") -> Completed:
    return Completed(0, f"{noise}{MARKER}{json.dumps(value)}\n", "")


def server(*answers: Completed) -> tuple[KubectlZulipServer, FakeRunner]:
    runner = FakeRunner(list(answers))
    return KubectlZulipServer(CONTEXT, run=runner), runner


@pytest.mark.parametrize(("out", "ready"), [("true", True), ("false", False), ("", False)])
async def test_ready_reads_the_pod_container_status(out: str, ready: bool) -> None:
    zulip, runner = server(Completed(0, out, ""))
    assert await zulip.ready() is ready
    args, _ = runner.calls[0]
    assert args[:3] == ["kubectl", "--context", CONTEXT]
    assert args[3:8] == ["-n", "chat", "get", "pod", "zulip-0"]


async def test_a_missing_pod_is_not_ready() -> None:
    zulip, _ = server(Completed(1, "", 'pods "zulip-0" not found'))
    assert await zulip.ready() is False


async def test_ensure_realm_runs_the_shell_in_the_pod_as_zulip() -> None:
    zulip, runner = server(emitted({"realm_id": 3, "created": True}))
    assert await zulip.ensure_realm("Tessaro", "") == (3, True)
    args, stdin = runner.calls[0]
    assert args[:9] == [
        "kubectl",
        "--context",
        CONTEXT,
        "-n",
        "chat",
        "exec",
        "-i",
        "zulip-0",
        "--",
    ]
    assert args[9:12] == ["su", "zulip", "-s"]
    assert args[-1].endswith("manage.py shell")
    assert stdin is not None
    assert "do_create_realm" in stdin
    assert json.dumps({"name": "Tessaro", "string_id": ""}) in stdin


async def test_ensure_user_defaults_sends_every_default() -> None:
    zulip, runner = server(emitted({"changed": False}))
    assert await zulip.ensure_user_defaults(3, USER_DEFAULTS) is False
    _, stdin = runner.calls[0]
    assert stdin is not None
    assert "do_set_realm_user_default_setting" in stdin
    assert '"email_address_visibility": 1' in stdin


async def test_ensure_owner_returns_the_record_with_its_key() -> None:
    record = {"created": True, "role": "owner", "can_create_users": False, "api_key": "k"}
    zulip, runner = server(emitted(record))
    owner = await zulip.ensure_owner(3, "a@x", "A")
    assert (owner.created, owner.role, owner.api_key) == (True, "owner", "k")
    _, stdin = runner.calls[0]
    assert stdin is not None
    assert "ROLE_REALM_OWNER" in stdin


async def test_change_role_calls_the_management_command_with_the_realm_id() -> None:
    zulip, runner = server(Completed(0, "", ""))
    await zulip.change_role(3, "a@x", "can_create_users")
    args, stdin = runner.calls[0]
    assert stdin is None
    assert args[-1].endswith("manage.py change_user_role a@x can_create_users -r 3")


async def test_realm_state_asks_for_each_rule_setting() -> None:
    state = {
        "name": "Tessaro",
        "invite_required": True,
        "authentication_methods": {"OpenID Connect": True},
        "groups": dict(GROUP_RULES),
        "system_groups": {"role:nobody": 1},
    }
    zulip, runner = server(emitted(state))
    assert (await zulip.realm_state(3)).invite_required is True
    _, stdin = runner.calls[0]
    assert stdin is not None
    assert all(setting in stdin for setting in GROUP_RULES)


async def test_a_failed_shell_names_the_step_and_the_last_error_line() -> None:
    zulip, _ = server(Completed(1, "", "Traceback\nValueError: boom\n"))
    with pytest.raises(BootstrapError, match=r"realm.*ValueError: boom"):
        await zulip.ensure_realm("Tessaro", "")


async def test_a_shell_without_a_result_line_is_an_error() -> None:
    zulip, _ = server(Completed(0, "nothing here\n", ""))
    with pytest.raises(BootstrapError, match="no result"):
        await zulip.ensure_realm("Tessaro", "")


async def test_a_failed_role_change_is_an_error() -> None:
    zulip, _ = server(Completed(1, "", "CommandError: no such user"))
    with pytest.raises(BootstrapError, match="no such user"):
        await zulip.change_role(3, "a@x", "owner")


async def test_current_context_reads_kubectl_config() -> None:
    runner = FakeRunner([Completed(0, "k3s-test\n", "")])
    assert await current_context(runner) == "k3s-test"
    assert runner.calls[0][0] == ["kubectl", "config", "current-context"]


async def test_no_current_context_is_empty() -> None:
    assert await current_context(FakeRunner([Completed(1, "", "error")])) == ""


async def test_run_process_feeds_stdin_and_captures_both_streams() -> None:
    code = "import sys; print(sys.stdin.read().upper()); print('e', file=sys.stderr)"
    done = await run_process([sys.executable, "-c", code], "hi")
    assert (done.returncode, done.stdout.strip(), done.stderr.strip()) == (0, "HI", "e")


async def test_run_process_stops_a_command_that_runs_too_long() -> None:
    with pytest.raises(BootstrapError, match="timed out"):
        await run_process([sys.executable, "-c", "import time; time.sleep(5)"], None, seconds=0.2)


async def test_run_process_reports_a_missing_program() -> None:
    with pytest.raises(BootstrapError, match="not found"):
        await run_process(["tessaro-no-such-program"], None)


async def test_an_owner_answer_of_the_wrong_shape_is_an_error() -> None:
    zulip, _ = server(emitted({"surprise": True}))
    with pytest.raises(BootstrapError, match="unexpected shape"):
        await zulip.ensure_owner(3, "a@x", "A")


async def test_a_realm_state_of_the_wrong_shape_is_an_error() -> None:
    zulip, _ = server(emitted({"surprise": True}))
    with pytest.raises(BootstrapError, match="unexpected shape"):
        await zulip.realm_state(3)
