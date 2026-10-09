"""`python -m tessaro_auth.policy_export`: write the OPA role data (`just contracts`).

Writes `policy/role_scopes.json` from `ROLE_SCOPES`, so OPA's `data.role_scopes`
always matches the typed table (spec 0005). A test fails when the committed file drifts.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from tessaro_auth.roles import ROLE_SCOPES
from tessaro_contracts.export import render_json, repo_root

ROLE_SCOPES_DATA: Final = Path("policy/role_scopes.json")


def role_scopes_data() -> dict[str, dict[str, list[str]]]:
    """The OPA `data.role_scopes` document: every role, its scopes sorted."""
    return {
        "role_scopes": {
            role.value: sorted(scope.value for scope in scopes)
            for role, scopes in ROLE_SCOPES.items()
        }
    }


def generated_files() -> dict[Path, str]:
    """Every file this exporter writes, by path relative to the repo root, with its text."""
    return {ROLE_SCOPES_DATA: render_json(role_scopes_data())}


def export(root: Path) -> None:
    """Write the generated files under `root`."""
    for relative, text in generated_files().items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for `just contracts`; exits non zero when a write fails."""
    parser = argparse.ArgumentParser(description="Write the OPA role to scope data.")
    parser.add_argument("--root", type=Path, default=None, help="repo root (default: find uv.lock)")
    args = parser.parse_args(argv)
    root: Path = args.root or repo_root(Path.cwd())
    try:
        export(root)
    except OSError as error:
        sys.stderr.write(f"could not write {ROLE_SCOPES_DATA}: {error}\n")
        return 1
    sys.stdout.write(f"wrote {ROLE_SCOPES_DATA}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
