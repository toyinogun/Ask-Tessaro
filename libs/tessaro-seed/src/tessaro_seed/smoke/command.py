"""`tessaro-seed smoke identity`: the edge of `just identity-smoke` (spec 0008 AC-14).

Prints one PASS or FAIL line per check and exits 0 only when every check passed. Exit codes:
0 all passed, 1 a check failed or the smoke could not start, 2 bad usage.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from tessaro_dataset import DatasetError, load_dataset
from tessaro_dataset.loader import DatasetPaths
from tessaro_seed.settings import MissingSettings, SeedSettings
from tessaro_seed.smoke.browser import PlaywrightSignIn
from tessaro_seed.smoke.identity import CheckResult, persona_of, smoke_identity

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

NEEDED = ("zulip_site", "tessaro_demo_password")


def render(results: Sequence[CheckResult]) -> str:
    """One `PASS name: detail` or `FAIL name: detail` line per check."""
    return "\n".join(f"{'PASS' if r.passed else 'FAIL'} {r.name}: {r.detail}" for r in results)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the named smoke (only `identity` so far) against the live systems."""
    parser = argparse.ArgumentParser(prog="tessaro-seed smoke", description=__doc__)
    parser.add_argument("smoke", choices=["identity"])
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repo root")
    args = parser.parse_args(argv)
    try:
        settings = SeedSettings()
        settings.require(*NEEDED)
        persona = persona_of(load_dataset(DatasetPaths.under(args.root)))
        results = asyncio.run(
            smoke_identity(
                PlaywrightSignIn(),
                str(settings.zulip_site),
                persona,
                settings.secret("tessaro_demo_password"),
            )
        )
    except MissingSettings as error:
        print(
            f"{error}; `just identity-secrets` and `just zulip-bootstrap` write them",
            file=sys.stderr,
        )
        return EXIT_FAILED
    except (ValidationError, DatasetError) as error:
        print(f"identity smoke could not start: {error}", file=sys.stderr)
        return EXIT_FAILED
    print(render(results))
    return EXIT_OK if all(r.passed for r in results) else EXIT_FAILED
