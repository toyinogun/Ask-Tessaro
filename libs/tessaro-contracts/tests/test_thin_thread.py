"""Tracer bullet: `get_my_leave` exists in the contract format and projects to an MCP tool."""

from tessaro_contracts.contract import IdentityMode
from tessaro_contracts.mcp import to_mcp_tool
from tessaro_contracts.people.get_my_leave import GET_MY_LEAVE, GetMyLeaveInput
from tessaro_contracts.scopes import Scope


def test_get_my_leave_contract_fields() -> None:
    assert GET_MY_LEAVE.name == "get_my_leave"
    assert GET_MY_LEAVE.version == "1.0"
    assert GET_MY_LEAVE.owner == "people-team"
    assert GET_MY_LEAVE.scope is Scope.HR_READ
    assert GET_MY_LEAVE.identity is IdentityMode.SELF
    assert GET_MY_LEAVE.authorization == "OpenFGA check can_view_own_data on employee:<sub>"
    assert GET_MY_LEAVE.write is None
    assert GetMyLeaveInput.model_fields == {}
    assert GET_MY_LEAVE.never_returns == (
        "reason",
        "absence_reason",
        "medical_note",
        "notes",
        "description",
        "salary",
    )


def test_get_my_leave_projects_to_an_mcp_tool() -> None:
    tool = to_mcp_tool(GET_MY_LEAVE)

    assert tool["name"] == "get_my_leave"
    assert tool["description"] == GET_MY_LEAVE.description
    assert tool["inputSchema"]["type"] == "object"
    assert tool["inputSchema"].get("properties", {}) == {}
    output = tool["outputSchema"]
    assert set(output["properties"]) == {"balances", "upcoming", "truncated"}
    assert output["properties"]["balances"]["maxItems"] == 1
    assert output["properties"]["upcoming"]["maxItems"] == 50
    meta = tool["_meta"]
    assert meta["tessaro/version"] == "1.0"
    assert meta["tessaro/scope"] == "hr:read"
    assert meta["tessaro/owner"] == "people-team"
