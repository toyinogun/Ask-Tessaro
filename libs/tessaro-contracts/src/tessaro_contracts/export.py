"""`python -m tessaro_contracts.export`: write snapshots and OPA tool data (`just contracts`).

Writes each contract's MCP projection to `libs/tessaro-contracts/schemas/<name>.json`
and the OPA tool data to `policy/tools.json`. Before writing anything it checks
every contract against its committed snapshot with the version rule (AC-19), and
writes nothing when one fails. A snapshot with no contract is a removed or renamed
released tool, which fails too.

`--check-against <dir>` writes nothing: it checks the registry against the snapshots
in `<dir>` (CI passes the base branch's `schemas/`), so a hand edited or deleted
snapshot in the change itself cannot hide a breaking change.
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from tessaro_contracts.contract import ToolContract
from tessaro_contracts.mcp import McpDict, to_mcp_tool
from tessaro_contracts.registry import ALL_CONTRACTS
from tessaro_contracts.schema_rules import compatibility_error

SCHEMAS_DIR: Final = Path("libs/tessaro-contracts/schemas")
TOOLS_DATA: Final = Path("policy/tools.json")


def repo_root(start: Path) -> Path:
    """The nearest directory at or above `start` holding `uv.lock`."""
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / "uv.lock").exists():
            return candidate
    raise FileNotFoundError(f"no uv.lock above {start}")


def render_json(value: object) -> str:
    """Sorted keys, two space indent, trailing newline: the committed file format."""
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def tools_data(contracts: Mapping[str, ToolContract]) -> McpDict:
    """The OPA `data.tools` document, generated from the contracts only."""
    return {
        "tools": {
            name: {"scope": c.scope.value, "version": c.version, "owner": c.owner}
            for name, c in contracts.items()
        }
    }


def generated_files(contracts: Mapping[str, ToolContract]) -> dict[Path, str]:
    """Every generated file, by path relative to the repo root, with its exact text."""
    files = {
        SCHEMAS_DIR / f"{name}.json": render_json(to_mcp_tool(contract))
        for name, contract in contracts.items()
    }
    files[TOOLS_DATA] = render_json(tools_data(contracts))
    return files


def removed_contract_errors(schemas_dir: Path, contracts: Mapping[str, ToolContract]) -> list[str]:
    """One error per snapshot in `schemas_dir` whose tool is no longer in the registry."""
    if not schemas_dir.is_dir():
        return []
    return [
        f"{snapshot.stem}: a released tool cannot be removed or renamed; "
        f"keep it, and publish a new tool such as {snapshot.stem}_v2 beside it"
        for snapshot in sorted(schemas_dir.glob("*.json"))
        if snapshot.stem not in contracts
    ]


def compatibility_errors(schemas_dir: Path, contracts: Mapping[str, ToolContract]) -> list[str]:
    """Version rule failures against the snapshots in `schemas_dir`, then removed tools."""
    errors: list[str] = []
    for name, contract in contracts.items():
        snapshot = schemas_dir / f"{name}.json"
        if not snapshot.exists():
            continue
        old = json.loads(snapshot.read_text(encoding="utf-8"))
        error = compatibility_error(old, to_mcp_tool(contract))
        if error is not None:
            errors.append(error)
    return errors + removed_contract_errors(schemas_dir, contracts)


def export(root: Path, contracts: Mapping[str, ToolContract]) -> list[str]:
    """Write the generated files under `root` unless a contract breaks the version rule.

    Returns the version rule errors; when there are any, nothing was written.
    """
    errors = compatibility_errors(root / SCHEMAS_DIR, contracts)
    if errors:
        return errors
    for relative, text in generated_files(contracts).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return []


def check_against(base_dir: Path) -> tuple[list[str], str]:
    """The registry against base snapshots, writing nothing: (errors, success message)."""
    if not base_dir.is_dir():
        return [], f"no base snapshots at {base_dir}, nothing released yet"
    return compatibility_errors(base_dir, ALL_CONTRACTS), "contracts match the base snapshots"


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for `just contracts` and `just contracts-check`."""
    parser = argparse.ArgumentParser(description="Write contract snapshots and OPA tool data.")
    parser.add_argument("--root", type=Path, default=None, help="repo root (default: find uv.lock)")
    parser.add_argument(
        "--check-against",
        type=Path,
        default=None,
        help="check against the snapshots in this folder and write nothing",
    )
    args = parser.parse_args(argv)
    if args.check_against is not None:
        errors, done = check_against(args.check_against)
    else:
        root: Path = args.root or repo_root(Path.cwd())
        errors = export(root, ALL_CONTRACTS)
        done = f"wrote {len(ALL_CONTRACTS)} snapshot(s) and {TOOLS_DATA}"
    for error in errors:
        sys.stderr.write(f"{error}\n")
    if errors:
        return 1
    sys.stdout.write(f"{done}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
