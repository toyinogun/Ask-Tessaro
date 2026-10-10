"""`KubectlZulipServer`: the `ZulipServer` steps as `kubectl exec` into the Zulip pod.

Each step is a short Python snippet fed to `manage.py shell` on stdin, so no value lands on a
command line; the snippet prints one `TESSARO_RESULT <json>` line, which is all this reads back.
Every call pins the kube context the command checked first.
"""

import asyncio
import json
import shlex
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from tessaro_seed.zulip_bootstrap.realm import (
    GROUP_RULES,
    BootstrapError,
    OwnerRecord,
    RealmState,
)

MARKER = "TESSARO_RESULT "
NAMESPACE = "chat"
# The chart's StatefulSet runs one replica (spec 0008 AC-17).
POD = "zulip-0"
MANAGE = "/home/zulip/deployments/current/manage.py"
TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True)
class Completed:
    """A finished command: exit code and both output streams."""

    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], str | None], Awaitable[Completed]]


async def run_process(
    args: Sequence[str], stdin: str | None, *, seconds: float = TIMEOUT_SECONDS
) -> Completed:
    """Run a command, feeding ``stdin``; BootstrapError when it is missing or runs too long."""
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise BootstrapError(f"{args[0]} not found") from error
    try:
        out, err = await asyncio.wait_for(
            process.communicate(stdin.encode() if stdin is not None else None), seconds
        )
    except TimeoutError as error:
        process.kill()
        await process.wait()
        raise BootstrapError(f"{args[0]} timed out after {seconds:.0f}s") from error
    return Completed(process.returncode or 0, out.decode(), err.decode())


async def current_context(run: Runner = run_process) -> str:
    """kubectl's current context, or an empty string when none is set."""
    done = await run(["kubectl", "config", "current-context"], None)
    return done.stdout.strip() if done.returncode == 0 else ""


_PRELUDE = """\
import json
P = json.loads({params})
def emit(value):
    print({marker} + json.dumps(value))
"""

_REALM = """
from zerver.models import Realm
from zerver.actions.create_realm import do_create_realm
realm = Realm.objects.filter(string_id=P["string_id"]).first()
created = realm is None
if realm is None:
    realm = do_create_realm(string_id=P["string_id"], name=P["name"])
emit({"realm_id": realm.id, "created": created})
"""

_DEFAULTS = """
from zerver.models import RealmUserDefault
from zerver.actions.realm_settings import do_set_realm_user_default_setting
defaults = RealmUserDefault.objects.get(realm_id=P["realm_id"])
changed = False
for name, value in P["defaults"].items():
    if getattr(defaults, name) != value:
        do_set_realm_user_default_setting(defaults, name, value, acting_user=None)
        changed = True
emit({"changed": changed})
"""

_OWNER = """
from zerver.models import Realm, UserProfile
from zerver.actions.create_user import do_create_user
realm = Realm.objects.get(id=P["realm_id"])
user = UserProfile.objects.filter(
    realm=realm, delivery_email__iexact=P["email"], is_bot=False
).first()
created = user is None
if user is None:
    user = do_create_user(
        P["email"], None, realm, P["full_name"],
        role=UserProfile.ROLE_REALM_OWNER, acting_user=None,
    )
names = {
    UserProfile.ROLE_REALM_OWNER: "owner",
    UserProfile.ROLE_REALM_ADMINISTRATOR: "admin",
    UserProfile.ROLE_MODERATOR: "moderator",
    UserProfile.ROLE_MEMBER: "member",
    UserProfile.ROLE_GUEST: "guest",
}
emit({
    "created": created,
    "role": names.get(user.role, str(user.role)),
    "can_create_users": user.can_create_users,
    "api_key": user.api_key,
})
"""

_STATE = """
from zerver.models import NamedUserGroup, Realm
realm = Realm.objects.get(id=P["realm_id"])
def group_name(setting):
    named = NamedUserGroup.objects.filter(id=getattr(realm, setting + "_id")).first()
    return named.name if named else None
system = NamedUserGroup.objects.filter(realm_for_sharding=realm, is_system_group=True)
emit({
    "name": realm.name,
    "invite_required": realm.invite_required,
    "authentication_methods": realm.authentication_methods_dict(),
    "groups": {setting: group_name(setting) for setting in P["settings"]},
    "system_groups": {group.name: group.id for group in system},
})
"""


def snippet(body: str, params: dict[str, Any]) -> str:
    """The shell input: the prelude binding ``P`` to ``params``, then the step's body."""
    # Any: snippet parameters are plain JSON values of several types.
    prelude = _PRELUDE.format(params=repr(json.dumps(params)), marker=repr(MARKER))
    return prelude + body


def _last_line(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "no output"


@dataclass(frozen=True)
class KubectlZulipServer:
    """`ZulipServer` over `kubectl exec`; ``run`` is swapped for a fake in tests."""

    context: str
    run: Runner = run_process
    namespace: str = NAMESPACE
    pod: str = POD

    def _kubectl(self, *args: str) -> list[str]:
        return ["kubectl", "--context", self.context, "-n", self.namespace, *args]

    def _as_zulip(self, command: str) -> list[str]:
        exec_args = self._kubectl("exec", "-i", self.pod, "--")
        return [*exec_args, "su", "zulip", "-s", "/bin/bash", "-c", command]

    async def _shell(self, step: str, body: str, params: dict[str, Any]) -> Any:
        # Any: the snippet's JSON result; each caller validates its own shape.
        done = await self.run(self._as_zulip(f"{MANAGE} shell"), snippet(body, params))
        if done.returncode != 0:
            raise BootstrapError(f"{step} failed in the Zulip shell: {_last_line(done.stderr)}")
        for line in done.stdout.splitlines():
            if line.startswith(MARKER):
                return json.loads(line.removeprefix(MARKER))
        raise BootstrapError(f"{step}: the Zulip shell printed no result")

    async def ready(self) -> bool:
        """The pod's containers all report ready."""
        query = "jsonpath={.status.containerStatuses[*].ready}"
        done = await self.run(self._kubectl("get", "pod", self.pod, "-o", query), None)
        flags = done.stdout.split()
        return done.returncode == 0 and bool(flags) and all(f == "true" for f in flags)

    async def ensure_realm(self, name: str, string_id: str) -> tuple[int, bool]:
        """Step 1 through `do_create_realm` (the `create_realm` command also adds a user)."""
        result = await self._shell("realm", _REALM, {"name": name, "string_id": string_id})
        return int(result["realm_id"]), bool(result["created"])

    async def ensure_user_defaults(self, realm_id: int, defaults: dict[str, int | bool]) -> bool:
        """Step 2: each differing default through `do_set_realm_user_default_setting`."""
        params = {"realm_id": realm_id, "defaults": defaults}
        result = await self._shell("realm user defaults", _DEFAULTS, params)
        return bool(result["changed"])

    async def ensure_owner(self, realm_id: int, email: str, full_name: str) -> OwnerRecord:
        """Step 3: the owner through `do_create_user`, read back with its API key every run."""
        params = {"realm_id": realm_id, "email": email, "full_name": full_name}
        result = await self._shell("owner", _OWNER, params)
        try:
            return OwnerRecord.model_validate(result)
        except ValidationError as error:
            raise BootstrapError("owner: the Zulip shell answered an unexpected shape") from error

    async def change_role(self, realm_id: int, email: str, role: str) -> None:
        """`manage.py change_user_role <email> <role> -r <realm id>`."""
        command = shlex.join([MANAGE, "change_user_role", email, role, "-r", str(realm_id)])
        done = await self.run(self._as_zulip(command), None)
        if done.returncode != 0:
            raise BootstrapError(f"change_user_role {role} failed: {_last_line(done.stderr)}")

    async def realm_state(self, realm_id: int) -> RealmState:
        """The realm rules step 4 compares against its target."""
        params = {"realm_id": realm_id, "settings": sorted(GROUP_RULES)}
        result = await self._shell("realm rules", _STATE, params)
        try:
            return RealmState.model_validate(result)
        except ValidationError as error:
            raise BootstrapError(
                "realm rules: the Zulip shell answered an unexpected shape"
            ) from error
