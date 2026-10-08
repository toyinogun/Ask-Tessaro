"""Helpers for tool server test suites: check a contract and a result against it."""

import json
from pathlib import Path
from typing import Final

from tessaro_contracts.contract import ToolContract, validate_contract
from tessaro_contracts.mcp import McpDict, to_mcp_tool
from tessaro_contracts.results import ToolResult, to_mcp_result
from tessaro_contracts.schema_rules import compatibility_error

PACKAGE_SCHEMAS: Final = Path(__file__).resolve().parents[2] / "schemas"
"""The committed snapshots beside this package in the workspace."""


def assert_contract_ok(contract: ToolContract, schemas_dir: Path = PACKAGE_SCHEMAS) -> None:
    """Run the AC-13 checks, then the version rule against the committed snapshot if any."""
    validate_contract(contract)
    snapshot = schemas_dir / f"{contract.name}.json"
    if not snapshot.exists():
        return
    error = compatibility_error(
        json.loads(snapshot.read_text(encoding="utf-8")), to_mcp_tool(contract)
    )
    if error is not None:
        raise AssertionError(error)


def assert_result_matches(contract: ToolContract, result: ToolResult) -> McpDict:
    """Assert a result is the contract's output type and serializes; returns the MCP result."""
    if not isinstance(result.output, contract.output_model):
        raise AssertionError(
            f"{contract.name}: output is {type(result.output).__name__}, "
            f"expected {contract.output_model.__name__}"
        )
    if not all(isinstance(record_id, str) and record_id for record_id in result.record_ids):
        raise AssertionError(f"{contract.name}: record_ids must be non empty strings")
    return to_mcp_result(result)
