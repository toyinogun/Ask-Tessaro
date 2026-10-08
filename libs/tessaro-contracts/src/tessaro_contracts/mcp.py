"""Project a contract onto the MCP tool shape, as plain dicts (no MCP SDK import)."""

from typing import Any

from tessaro_contracts.contract import ToolContract

McpDict = dict[str, Any]
"""An MCP wire object. Any: JSON values are arbitrarily nested."""


def to_mcp_tool(contract: ToolContract) -> McpDict:
    """The `tools/list` entry for a contract, with Tessaro metadata under `_meta`.

    Beyond version, scope and owner, `_meta` also carries identity, authorization,
    never_returns and write, so the committed snapshot sees every contract field the
    compatibility rule (AC-19) judges.
    """
    write = contract.write
    return {
        "name": contract.name,
        "description": contract.description,
        "inputSchema": contract.input_model.model_json_schema(mode="validation"),
        "outputSchema": contract.output_model.model_json_schema(mode="serialization"),
        "_meta": {
            "tessaro/version": contract.version,
            "tessaro/scope": contract.scope.value,
            "tessaro/owner": contract.owner,
            "tessaro/identity": contract.identity.value,
            "tessaro/authorization": contract.authorization,
            "tessaro/never_returns": list(contract.never_returns),
            "tessaro/write": None
            if write is None
            else {
                "idempotency_key_param": write.idempotency_key_param,
                "undo_tool": write.undo_tool,
            },
        },
    }
