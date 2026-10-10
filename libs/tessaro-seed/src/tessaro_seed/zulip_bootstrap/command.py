"""`tessaro-seed zulip-bootstrap`: the edge of `just zulip-bootstrap` (spec 0008 AC-11).

Refuses unless kubectl's current context is `TESSARO_KUBE_CONTEXT`, runs the bootstrap through
`kubectl exec` and the owner's API key, then writes `ZULIP_ADMIN_EMAIL` and `ZULIP_ADMIN_API_KEY`
into `.env`. A failed step writes nothing. Exit codes: 0 done, 1 failed, 2 bad usage.
"""

import argparse
import asyncio
import os
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

from pydantic import ValidationError

from tessaro_clients.errors import ClientError
from tessaro_clients.zulip import HttpZulipAdmin, ZulipAdmin, zulip_http
from tessaro_seed.envfile import set_env
from tessaro_seed.settings import MissingSettings, SeedSettings
from tessaro_seed.zulip_bootstrap.bootstrap import BootstrapResult, bootstrap, render
from tessaro_seed.zulip_bootstrap.kubectl import KubectlZulipServer, current_context
from tessaro_seed.zulip_bootstrap.realm import BootstrapError

EXIT_OK = 0
EXIT_FAILED = 1

NEEDED = ("tessaro_kube_context", "zulip_site")
ENV_FILE = ".env"


def write_owner(root: Path, result: BootstrapResult) -> None:
    """Set the owner's email and API key in ``root/.env``, readable by you only (0600)."""
    path = root / ENV_FILE
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    values = {
        "ZULIP_ADMIN_EMAIL": result.admin_email,
        "ZULIP_ADMIN_API_KEY": result.admin_api_key,
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(set_env(text, values))


async def _run(settings: SeedSettings) -> BootstrapResult:
    want = str(settings.tessaro_kube_context)
    have = await current_context()
    if have != want:
        raise BootstrapError(f"current context is '{have or 'none'}', expected '{want}'; refusing")

    @asynccontextmanager
    async def owner_admin(email: str, api_key: str) -> AsyncIterator[ZulipAdmin]:
        async with zulip_http(str(settings.zulip_site), email, api_key) as http:
            yield HttpZulipAdmin(http)

    return await bootstrap(KubectlZulipServer(want), owner_admin)


def main(argv: Sequence[str] | None = None) -> int:
    """Bring Zulip to its bootstrapped state and record the owner's credentials."""
    parser = argparse.ArgumentParser(prog="tessaro-seed zulip-bootstrap", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repo root (holds .env)")
    args = parser.parse_args(argv)
    try:
        settings = SeedSettings()
        settings.require(*NEEDED)
        result = asyncio.run(_run(settings))
    except MissingSettings as error:
        print(f"{error} (add them to .env)", file=sys.stderr)
        return EXIT_FAILED
    except (ValidationError, BootstrapError, ClientError) as error:
        print(f"zulip bootstrap failed: {error}", file=sys.stderr)
        return EXIT_FAILED
    write_owner(args.root, result)
    print(render(result))
    print(f"{ENV_FILE}: ZULIP_ADMIN_EMAIL, ZULIP_ADMIN_API_KEY")
    return EXIT_OK
