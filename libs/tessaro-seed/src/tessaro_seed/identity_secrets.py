"""`just identity-secrets`: the env files `just seal` reads, plus the local values in `.env` (AC-8).

Each value lives in one or more places (a file and a variable name). The first place is its
primary copy. A run keeps every value that already exists, copies it to the places that lack it,
and generates only a value that exists nowhere, so a rerun never rotates anything. Copies that
disagree stop the run before any file is written.
"""

import argparse
import os
import secrets
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tessaro_seed.envfile import read_env, set_env

ENV_FILE = ".env"
AUTHENTIK_FILE = ".secrets/identity/authentik.env"
ZULIP_FILE = ".secrets/chat/zulip.env"
ADAPTER_FILE = ".secrets/assistant/zulip-adapter.env"

AUTHENTIK_URL = "https://auth.tessaro.toyintest.org"
AUTHENTIK_INTERNAL_URL = "http://authentik-server.identity.svc.cluster.local"
ZULIP_SITE = "https://chat.tessaro.toyintest.org"

HEADER = "# Written by `just identity-secrets` (spec 0008). Git ignored; never commit.\n"

Place = tuple[str, str]


def _random() -> str:
    return secrets.token_hex(32)


@dataclass(frozen=True)
class SecretValue:
    """One value and every (file, variable) place it is written to; the first is primary."""

    places: tuple[Place, ...]
    make: Callable[[], str] = _random


def _fixed(value: str) -> Callable[[], str]:
    return lambda: value


VALUES: tuple[SecretValue, ...] = (
    SecretValue(((AUTHENTIK_FILE, "AUTHENTIK_SECRET_KEY"),)),
    SecretValue(((AUTHENTIK_FILE, "AUTHENTIK_BOOTSTRAP_PASSWORD"),)),
    SecretValue(
        ((AUTHENTIK_FILE, "AUTHENTIK_BOOTSTRAP_TOKEN"), (ENV_FILE, "AUTHENTIK_BOOTSTRAP_TOKEN"))
    ),
    SecretValue(((AUTHENTIK_FILE, "TESSARO_ADMIN_PASSWORD"),)),
    SecretValue(((AUTHENTIK_FILE, "TESSARO_SEED_TOKEN"), (ENV_FILE, "AUTHENTIK_SEED_TOKEN"))),
    SecretValue(
        (
            (AUTHENTIK_FILE, "ZULIP_ADAPTER_AUTHENTIK_TOKEN"),
            (ENV_FILE, "ZULIP_ADAPTER_AUTHENTIK_TOKEN"),
            (ADAPTER_FILE, "AUTHENTIK_API_TOKEN"),
        )
    ),
    SecretValue(
        ((AUTHENTIK_FILE, "ZULIP_OIDC_CLIENT_SECRET"), (ZULIP_FILE, "ZULIP_OIDC_CLIENT_SECRET"))
    ),
    SecretValue(((ZULIP_FILE, "ZULIP_SECRET_KEY"),)),
    SecretValue(((ZULIP_FILE, "REDIS_PASSWORD"),)),
    SecretValue(((ZULIP_FILE, "RABBITMQ_PASSWORD"),)),
    SecretValue(((ENV_FILE, "TESSARO_DEMO_PASSWORD"),), lambda: secrets.token_urlsafe(18)),
    SecretValue(((ENV_FILE, "AUTHENTIK_URL"),), _fixed(AUTHENTIK_URL)),
    SecretValue(((ENV_FILE, "ZULIP_SITE"),), _fixed(ZULIP_SITE)),
    SecretValue(((ADAPTER_FILE, "AUTHENTIK_URL"),), _fixed(AUTHENTIK_INTERNAL_URL)),
)


class SecretsConflict(Exception):
    """Two copies of one value disagree; the engineer decides which one is right."""


def _read_all(root: Path) -> dict[str, dict[str, str]]:
    files = {rel for value in VALUES for rel, _ in value.places}
    return {
        rel: read_env((root / rel).read_text(encoding="utf-8")) if (root / rel).exists() else {}
        for rel in files
    }


def _plan(current: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    writes: dict[str, dict[str, str]] = {}
    for value in VALUES:
        found = {(rel, name): current[rel].get(name, "") for rel, name in value.places}
        existing = {v for v in found.values() if v}
        if len(existing) > 1:
            primary = value.places[0][1]
            where = ", ".join(f"{rel} {name}" for (rel, name), v in found.items() if v)
            raise SecretsConflict(f"{primary}: the copies in {where} disagree; make them equal")
        chosen = existing.pop() if existing else value.make()
        for (rel, name), v in found.items():
            if not v:
                writes.setdefault(rel, {})[name] = chosen
    return writes


def _write(path: Path, values: dict[str, str]) -> None:
    if path.name != ENV_FILE:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.parent.chmod(0o700)
    text = path.read_text(encoding="utf-8") if path.exists() else HEADER
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(set_env(text, values))


def ensure(root: Path) -> list[str]:
    """Fill every missing value under ``root``; return ``"<file>: <name>"`` for each one written.

    Raises SecretsConflict, before writing anything, when copies of one value disagree.
    """
    writes = _plan(_read_all(root))
    for rel, values in sorted(writes.items()):
        _write(root / rel, values)
    return [f"{rel}: {name}" for rel, values in sorted(writes.items()) for name in values]


def git_ignored(path: Path) -> bool:
    """True when git ignores ``path`` in the repo that holds it."""
    # Fixed command; the path is ours. A non zero exit means "not ignored" (or no repo).
    result = subprocess.run(  # noqa: S603
        ["git", "check-ignore", "-q", str(path)],  # noqa: S607
        cwd=next(parent for parent in path.parents if parent.exists()),
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def main(argv: Sequence[str] | None = None, ignored: Callable[[Path], bool] = git_ignored) -> int:
    """Write the missing identity secrets under ``--root``; exit 1 on an unsafe or broken state."""
    parser = argparse.ArgumentParser(prog="tessaro-seed identity-secrets", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repo root")
    args = parser.parse_args(argv)
    root: Path = args.root
    if not (root / ENV_FILE).exists():
        print(f"{root / ENV_FILE} is missing; run `just init` first", file=sys.stderr)
        return 1
    secret_files = sorted({rel for v in VALUES for rel, _ in v.places} - {ENV_FILE})
    exposed = [rel for rel in secret_files if not ignored(root / rel)]
    if exposed:
        print(
            f"refusing: {', '.join(exposed)} not git ignored; add .secrets/ to .gitignore",
            file=sys.stderr,
        )
        return 1
    try:
        written = ensure(root)
    except SecretsConflict as error:
        print(f"refusing: {error}", file=sys.stderr)
        return 1
    print("\n".join(f"wrote {line}" for line in written) if written else "unchanged")
    return 0
