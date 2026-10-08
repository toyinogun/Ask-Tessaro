"""MCP results and errors (AC-16) and the `testing.py` helpers."""

import json

import pytest
from pydantic import ValidationError

from tessaro_contracts.people.get_my_leave import GET_MY_LEAVE, GetMyLeaveOutput, LeaveBalance
from tessaro_contracts.results import (
    ToolError,
    ToolErrorCode,
    ToolResult,
    to_mcp_error,
    to_mcp_result,
)
from tessaro_contracts.testing import assert_result_matches

BALANCE = LeaveBalance(
    leave_type="vacation",
    year=2026,
    entitled_days=25,
    taken_days=10,
    pending_days=3,
    remaining_days=15,
)
OUTPUT = GetMyLeaveOutput(balances=(BALANCE,), upcoming=(), truncated=False)


def test_result_shape() -> None:
    result = to_mcp_result(ToolResult(OUTPUT, ("HR-ALLOC-1", "HR-LAP-2")))
    assert result["structuredContent"] == OUTPUT.model_dump(mode="json")
    assert result["content"] == [{"type": "text", "text": OUTPUT.model_dump_json()}]
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    assert result["_meta"] == {"tessaro/record_ids": ["HR-ALLOC-1", "HR-LAP-2"]}
    assert "isError" not in result


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_result_revalidates_an_unchecked_output() -> None:
    sneaky = GetMyLeaveOutput.model_construct(balances=(), upcoming=(), truncated="maybe")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        to_mcp_result(ToolResult(sneaky))


@pytest.mark.parametrize("code", list(ToolErrorCode))
def test_error_shape(code: ToolErrorCode) -> None:
    assert to_mcp_error(ToolError(code, "Frappe HR did not answer.")) == {
        "isError": True,
        "content": [{"type": "text", "text": "Frappe HR did not answer."}],
        "_meta": {"tessaro/error_code": code.value},
    }


def test_error_codes_are_fixed() -> None:
    assert {c.value for c in ToolErrorCode} == {
        "unauthenticated",
        "forbidden",
        "not_found",
        "invalid_input",
        "upstream_unavailable",
        "internal",
    }
    with pytest.raises(ValueError, match="teapot"):
        ToolError("teapot", "no")  # type: ignore[arg-type]


def test_assert_result_matches() -> None:
    assert assert_result_matches(GET_MY_LEAVE, ToolResult(OUTPUT, ("HR-1",)))["structuredContent"]
    with pytest.raises(AssertionError, match="expected GetMyLeaveOutput"):
        assert_result_matches(GET_MY_LEAVE, ToolResult(BALANCE))
    with pytest.raises(AssertionError, match="record_ids"):
        assert_result_matches(GET_MY_LEAVE, ToolResult(OUTPUT, ("",)))
