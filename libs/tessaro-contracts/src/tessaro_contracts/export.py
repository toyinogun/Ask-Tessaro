"""`python -m tessaro_contracts.export`: write snapshots and OPA tool data (`just contracts`).

Writes each contract's MCP projection to `libs/tessaro-contracts/schemas/<name>.json`
and the OPA tool data to `policy/data/tools.json`. Before writing anything it checks
every contract against its committed snapshot with the version rule (AC-19), and
writes nothing when one fails.
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
TOOLS_DATA: Final = Path("policy/data/tools.json")


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


def compatibility_errors(root: Path, contracts: Mapping[str, ToolContract]) -> list[str]:
    """Version rule failures against the committed snapshots under `root`."""
    errors: list[str] = []
    for name, contract in contracts.items():
        snapshot = root / SCHEMAS_DIR / f"{name}.json"
        if not snapshot.exists():
            continue
        old = json.loads(snapshot.read_text(encoding="utf-8"))
        error = compatibility_error(old, to_mcp_tool(contract))
        if error is not None:
            errors.append(error)
    return errors


def export(root: Path, contracts: Mapping[str, ToolContract]) -> list[str]:
    """Write the generated files under `root` unless a contract breaks the version rule.

    Returns the version rule errors; when there are any, nothing was written.
    """
    errors = compatibility_errors(root, contracts)
    if errors:
        return errors
    for relative, text in generated_files(contracts).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return []


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for `just contracts`."""
    parser = argparse.ArgumentParser(description="Write contract snapshots and OPA tool data.")
    parser.add_argument("--root", type=Path, default=None, help="repo root (default: find uv.lock)")
    args = parser.parse_args(argv)
    root: Path = args.root or repo_root(Path.cwd())
    errors = export(root, ALL_CONTRACTS)
    for error in errors:
        sys.stderr.write(f"{error}\n")
    if errors:
        return 1
    sys.stdout.write(f"wrote {len(ALL_CONTRACTS)} snapshot(s) and {TOOLS_DATA}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
