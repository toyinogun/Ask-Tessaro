"""`tessaro-seed identity [--dry-run] [--reset-passwords]`: the edge of the identity seed.

Loads the dataset at the current time, reads `SeedSettings`, opens the real clients and prints
one line per write and the per system counts. Exit codes: 0 done, 1 failed, 2 bad usage.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from tessaro_clients.authentik import HttpAuthentikDirectory, authentik_http
from tessaro_clients.zulip import HttpZulipAdmin, zulip_http
from tessaro_dataset import Dataset, DatasetError, load_dataset
from tessaro_dataset.exports.authentik import export_authentik
from tessaro_dataset.exports.zulip import export_zulip
from tessaro_dataset.loader import DatasetPaths
from tessaro_seed.identity.reconcile import (
    Counts,
    IdentityInput,
    IdentityReport,
    ReconcileError,
    describe,
    reconcile_identity,
)
from tessaro_seed.settings import MissingSettings, SeedSettings

EXIT_OK = 0
EXIT_FAILED = 1

NEEDED = (
    "authentik_url",
    "authentik_seed_token",
    "zulip_site",
    "zulip_admin_email",
    "zulip_admin_api_key",
    "tessaro_demo_password",
)


def identity_input(dataset: Dataset, demo_password: str) -> IdentityInput:
    """The seed employees (demo input joiners excluded) and every group the blueprints declare."""
    blueprint_groups = export_authentik(dataset, include_demo_inputs=True).groups
    return IdentityInput(
        authentik=export_authentik(dataset),
        zulip=export_zulip(dataset),
        managed_groups=frozenset(g.name for g in blueprint_groups),
        demo_password=demo_password,
    )


def _counts(label: str, counts: Counts) -> str:
    return (
        f"{label}: {counts.created} created, {counts.updated} updated, {counts.unchanged} unchanged"
    )


def render(result: IdentityReport, *, dry_run: bool) -> str:
    """The lines the command prints: each write (or planned write), then the counts."""
    prefix = "would " if dry_run else ""
    lines = [f"authentik: {prefix}{describe(a)}" for a in result.authentik_actions]
    lines += [f"zulip: {prefix}{describe(a)}" for a in result.zulip_actions]
    lines += [
        _counts("authentik users", result.authentik),
        _counts("zulip users", result.zulip_users),
        _counts("zulip channels", result.zulip_channels),
    ]
    return "\n".join(lines)


async def _run(settings: SeedSettings, data: IdentityInput, args: argparse.Namespace) -> str:
    async with (
        authentik_http(str(settings.authentik_url), settings.secret("authentik_seed_token")) as a,
        zulip_http(
            str(settings.zulip_site),
            str(settings.zulip_admin_email),
            settings.secret("zulip_admin_api_key"),
        ) as z,
    ):
        result = await reconcile_identity(
            HttpAuthentikDirectory(a),
            HttpZulipAdmin(z),
            data,
            dry_run=args.dry_run,
            reset_passwords=args.reset_passwords,
        )
    return render(result, dry_run=args.dry_run)


def main(argv: Sequence[str] | None = None) -> int:
    """Reconcile the dataset's people into Authentik and Zulip."""
    parser = argparse.ArgumentParser(prog="tessaro-seed identity", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repo root")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    parser.add_argument(
        "--reset-passwords", action="store_true", help="set the demo password on every person"
    )
    args = parser.parse_args(argv)
    try:
        settings = SeedSettings()
        settings.require(*NEEDED)
        dataset = load_dataset(DatasetPaths.under(args.root))
        data = identity_input(dataset, settings.secret("tessaro_demo_password"))
        print(asyncio.run(_run(settings, data, args)))
    except MissingSettings as error:
        hint = "" if "ZULIP_ADMIN" not in str(error) else " (`just zulip-bootstrap` writes these)"
        print(f"{error}{hint}; `just identity-secrets` writes the rest", file=sys.stderr)
        return EXIT_FAILED
    except (ValidationError, DatasetError, ReconcileError) as error:
        print(f"identity seed failed: {error}", file=sys.stderr)
        return EXIT_FAILED
    return EXIT_OK
