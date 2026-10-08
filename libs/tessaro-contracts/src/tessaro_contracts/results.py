"""Tool results and errors, and their MCP wire shape (spec 0003 AC-16)."""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel

from tessaro_contracts.mcp import McpDict


class ToolErrorCode(StrEnum):
    """The only error codes a tool may return."""

    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    INVALID_INPUT = "invalid_input"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class ToolResult:
    """A tool's output and the IDs of the records it read or touched, for the audit line."""

    output: BaseModel
    record_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolError:
    """A failed call: one fixed code and a message safe to show the agent."""

    code: ToolErrorCode
    message: str

    def __post_init__(self) -> None:
        ToolErrorCode(self.code)


def to_mcp_result(result: ToolResult) -> McpDict:
    """The MCP `CallToolResult` for a success; ValidationError when the output is not valid."""
    output = type(result.output).model_validate(result.output.model_dump(by_alias=True))
    return {
        "structuredContent": output.model_dump(mode="json", by_alias=True),
        "content": [{"type": "text", "text": output.model_dump_json(by_alias=True)}],
        "_meta": {"tessaro/record_ids": list(result.record_ids)},
    }


def to_mcp_error(error: ToolError) -> McpDict:
    """The MCP `CallToolResult` for a failure, carrying the error code in `_meta`."""
    return {
        "isError": True,
        "content": [{"type": "text", "text": error.message}],
        "_meta": {"tessaro/error_code": ToolErrorCode(error.code).value},
    }
