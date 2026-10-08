"""Generated files never drift (AC-18) and the version rule holds (AC-19)."""

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field

from tessaro_contracts.contract import IdentityMode, WriteSpec
from tessaro_contracts.export import (
    SCHEMAS_DIR,
    TOOLS_DATA,
    export,
    generated_files,
    main,
    render_json,
    repo_root,
)
from tessaro_contracts.mcp import to_mcp_tool
from tessaro_contracts.people.get_my_leave import GET_MY_LEAVE, GetMyLeaveOutput
from tessaro_contracts.registry import ALL_CONTRACTS, build_registry
from tessaro_contracts.schema_rules import Change, classify, compatibility_error
from tessaro_contracts.scopes import Scope
from tessaro_contracts.testing import assert_contract_ok

ROOT = repo_root(Path(__file__).parent)
CLOSED = ConfigDict(frozen=True, extra="forbid")


# AC-18: drift


@pytest.mark.parametrize("relative", sorted(generated_files(ALL_CONTRACTS), key=str))
def test_committed_generated_files_match_the_registry(relative: Path) -> None:
    committed = ROOT / relative
    assert committed.exists(), f"{relative} is missing; run `just contracts`"
    expected = generated_files(ALL_CONTRACTS)[relative]
    assert committed.read_text(encoding="utf-8") == expected, (
        f"{relative} is stale; run `just contracts`"
    )


def test_tools_data_shape() -> None:
    data = json.loads(generated_files(ALL_CONTRACTS)[TOOLS_DATA])
    assert data == {
        "tools": {"get_my_leave": {"scope": "hr:read", "version": "1.0", "owner": "people-team"}}
    }


def test_render_json_format() -> None:
    assert render_json({"b": 1, "a": [1]}) == '{\n  "a": [\n    1\n  ],\n  "b": 1\n}\n'


def test_repo_root_needs_uv_lock(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        repo_root(tmp_path)


def test_export_writes_into_a_fresh_root(tmp_path: Path) -> None:
    assert export(tmp_path, ALL_CONTRACTS) == []
    for relative, text in generated_files(ALL_CONTRACTS).items():
        assert (tmp_path / relative).read_text(encoding="utf-8") == text


def test_export_refuses_a_breaking_change_and_writes_nothing(tmp_path: Path) -> None:
    assert export(tmp_path, ALL_CONTRACTS) == []
    snapshot = tmp_path / SCHEMAS_DIR / "get_my_leave.json"
    before = snapshot.read_text(encoding="utf-8")
    (tmp_path / TOOLS_DATA).unlink()

    errors = export(tmp_path, build_registry([replace(GET_MY_LEAVE, scope=Scope.HR_READ_ANY)]))

    assert len(errors) == 1
    assert "get_my_leave_v2" in errors[0]
    assert snapshot.read_text(encoding="utf-8") == before
    assert not (tmp_path / TOOLS_DATA).exists()


def test_main_against_a_temp_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(tmp_path)]) == 0
    assert "wrote 1 snapshot" in capsys.readouterr().out


def test_main_reports_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    snapshot = tmp_path / SCHEMAS_DIR / "get_my_leave.json"
    snapshot.parent.mkdir(parents=True)
    projection = to_mcp_tool(GET_MY_LEAVE)
    projection["_meta"]["tessaro/version"] = "0.9"
    snapshot.write_text(render_json(projection), encoding="utf-8")
    assert main(["--root", str(tmp_path)]) == 1
    assert "version changed without a contract change" in capsys.readouterr().err


# AC-19: every released contract against its committed snapshot


@pytest.mark.parametrize("name", sorted(ALL_CONTRACTS))
def test_released_contracts_keep_the_version_rule(name: str) -> None:
    assert_contract_ok(ALL_CONTRACTS[name], ROOT / SCHEMAS_DIR)


def test_a_contract_without_a_snapshot_passes(tmp_path: Path) -> None:
    assert_contract_ok(GET_MY_LEAVE, tmp_path)


def test_assert_contract_ok_raises_on_a_rule_break(tmp_path: Path) -> None:
    (tmp_path / "get_my_leave.json").write_text(
        render_json(to_mcp_tool(GET_MY_LEAVE)), encoding="utf-8"
    )
    with pytest.raises(AssertionError, match="without a version change"):
        assert_contract_ok(replace(GET_MY_LEAVE, description="Changed."), tmp_path)


# AC-19: the rule itself, on projections


def snapshot() -> dict[str, Any]:
    return to_mcp_tool(GET_MY_LEAVE)


def bump(projection: dict[str, Any], version: str) -> dict[str, Any]:
    changed = copy.deepcopy(projection)
    changed["_meta"]["tessaro/version"] = version
    return changed


def test_no_change_same_version_passes() -> None:
    assert compatibility_error(snapshot(), snapshot()) is None
    assert classify(snapshot(), snapshot()).change is Change.NONE


@pytest.mark.parametrize("version", ["1.1", "2.0", "0.9"])
def test_no_change_with_another_version_fails(version: str) -> None:
    error = compatibility_error(snapshot(), bump(snapshot(), version))
    assert error == "get_my_leave: version changed without a contract change"


class WithoutTaken(BaseModel):
    """Leave without taken days."""

    model_config = CLOSED
    leave_type: str
    year: int


class TakenRemovedOutput(BaseModel):
    model_config = CLOSED
    balances: tuple[WithoutTaken, ...] = Field(max_length=1)


@pytest.mark.parametrize("version", ["1.0", "1.1", "2.0"])
def test_removing_taken_days_is_breaking_whatever_the_version(version: str) -> None:
    old = snapshot()
    new = to_mcp_tool(replace(GET_MY_LEAVE, version=version, output_model=TakenRemovedOutput))
    error = compatibility_error(old, new)
    assert error is not None
    assert "publish it as a new tool get_my_leave_v2" in error


@pytest.mark.parametrize("version", ["1.1", "2.0"])
def test_dropping_only_taken_days_is_breaking(version: str) -> None:
    new = bump(snapshot(), version)
    balance = new["outputSchema"]["$defs"]["LeaveBalance"]
    del balance["properties"]["taken_days"]
    balance["required"].remove("taken_days")
    verdict = classify(snapshot(), new)
    assert verdict.change is Change.BREAKING
    assert "outputSchema.$defs.LeaveBalance.properties.taken_days" in verdict.reasons


def _projection_with_output(model: type[BaseModel], version: str) -> dict[str, Any]:
    return to_mcp_tool(replace(GET_MY_LEAVE, version=version, output_model=model))


class OutputPlusNote(GetMyLeaveOutput):
    note: str | None = None


def test_new_optional_output_field_with_minor_bump_passes() -> None:
    new = _projection_with_output(OutputPlusNote, "1.1")
    assert classify(snapshot(), new).change is Change.ADDITIVE
    assert compatibility_error(snapshot(), new) is None


class OutputPlusRequired(GetMyLeaveOutput):
    year_total: int


def test_new_required_output_field_is_additive() -> None:
    assert (
        compatibility_error(snapshot(), _projection_with_output(OutputPlusRequired, "1.1")) is None
    )


@pytest.mark.parametrize(
    ("version", "message"),
    [
        ("1.0", "without a version change"),
        ("2.0", "keeps the major version"),
        ("2.1", "keeps the major version"),
    ],
)
def test_additive_change_needs_a_minor_bump_only(version: str, message: str) -> None:
    error = compatibility_error(snapshot(), _projection_with_output(OutputPlusNote, version))
    assert error is not None
    assert message in error


def test_minor_must_go_up() -> None:
    old = bump(snapshot(), "1.5")
    new = _projection_with_output(OutputPlusNote, "1.4")
    assert "raises the minor" in (compatibility_error(old, new) or "")


@pytest.mark.parametrize(
    "changes",
    [
        {"scope": Scope.HR_READ_ANY},
        {"identity": IdentityMode.NONE},
        {"owner": "it-team"},
    ],
)
def test_contract_field_changes_are_breaking(changes: dict[str, Any]) -> None:
    new = to_mcp_tool(replace(GET_MY_LEAVE, version="1.1", **changes))
    assert classify(snapshot(), new).change is Change.BREAKING


def test_write_change_is_breaking() -> None:
    old = snapshot()
    new = bump(snapshot(), "1.1")
    new["_meta"]["tessaro/write"] = {"idempotency_key_param": "key", "undo_tool": None}
    assert classify(old, new).change is Change.BREAKING
    assert WriteSpec(idempotency_key_param="key").undo_tool is None


@pytest.mark.parametrize(
    "changes",
    [
        {"description": "Your leave, worded better."},
        {"authorization": "OpenFGA check can_view_own_data on employee:<sub> (self)"},
        {"never_returns": ("reason", "salary")},
    ],
)
def test_text_changes_are_additive(changes: dict[str, Any]) -> None:
    new = to_mcp_tool(replace(GET_MY_LEAVE, version="1.1", **changes))
    assert classify(snapshot(), new).change is Change.ADDITIVE
    assert compatibility_error(snapshot(), new) is None


def test_schema_title_and_description_text_is_additive() -> None:
    new = bump(snapshot(), "1.1")
    new["outputSchema"]["description"] = "Reworded."
    new["outputSchema"]["$defs"]["LeaveBalance"]["title"] = "Balance"
    verdict = classify(snapshot(), new)
    assert verdict.change is Change.ADDITIVE
    assert verdict.reasons == ("outputSchema (text)",)


def test_a_property_named_title_is_not_text() -> None:
    old = bump(snapshot(), "1.0")
    old["outputSchema"]["properties"]["title"] = {"type": "string"}
    new = bump(snapshot(), "1.1")
    assert classify(old, new).change is Change.BREAKING


def test_new_output_enum_value_is_additive() -> None:
    new = bump(snapshot(), "1.1")
    upcoming = new["outputSchema"]["$defs"]["UpcomingLeave"]["properties"]
    upcoming["status"]["enum"] = ["open", "approved", "cancelled"]
    balance = new["outputSchema"]["$defs"]["LeaveBalance"]["properties"]
    balance["leave_type"] = {"enum": ["vacation", "comp_time"], "type": "string"}
    assert classify(snapshot(), new).change is Change.ADDITIVE


def test_removed_output_enum_value_is_breaking() -> None:
    new = bump(snapshot(), "1.1")
    upcoming = new["outputSchema"]["$defs"]["UpcomingLeave"]["properties"]
    upcoming["status"]["enum"] = ["approved"]
    assert classify(snapshot(), new).change is Change.BREAKING


def test_type_and_constraint_changes_are_breaking() -> None:
    retyped = bump(snapshot(), "1.1")
    retyped["outputSchema"]["properties"]["truncated"]["type"] = "string"
    assert classify(snapshot(), retyped).change is Change.BREAKING
    widened = bump(snapshot(), "1.1")
    widened["outputSchema"]["properties"]["upcoming"]["maxItems"] = 100
    assert classify(snapshot(), widened).change is Change.BREAKING
    unbounded = bump(snapshot(), "1.1")
    del unbounded["outputSchema"]["properties"]["upcoming"]["maxItems"]
    assert classify(snapshot(), unbounded).change is Change.BREAKING


def test_output_field_turning_optional_is_breaking() -> None:
    new = bump(snapshot(), "1.1")
    new["outputSchema"]["required"].remove("truncated")
    assert classify(snapshot(), new).change is Change.BREAKING


class FilterInput(BaseModel):
    model_config = CLOSED
    year: int | None = None


class RequiredFilterInput(BaseModel):
    model_config = CLOSED
    year: int


def _with_input(model: type[BaseModel], version: str = "1.1") -> dict[str, Any]:
    return to_mcp_tool(replace(GET_MY_LEAVE, version=version, input_model=model))


def test_new_optional_input_is_additive() -> None:
    assert classify(snapshot(), _with_input(FilterInput)).change is Change.ADDITIVE


def test_new_required_input_is_breaking() -> None:
    assert classify(snapshot(), _with_input(RequiredFilterInput)).change is Change.BREAKING


def test_input_turning_required_or_dropped_is_breaking() -> None:
    old = _with_input(FilterInput, "1.1")
    assert classify(old, _with_input(RequiredFilterInput, "1.2")).change is Change.BREAKING
    assert classify(old, snapshot()).change is Change.BREAKING


def test_input_enum_widening_is_breaking() -> None:
    old = bump(snapshot(), "1.0")
    old["inputSchema"]["properties"] = {"kind": {"enum": ["a"], "type": "string"}}
    new = bump(old, "1.1")
    new["inputSchema"]["properties"]["kind"]["enum"] = ["a", "b"]
    assert classify(old, new).change is Change.BREAKING


def test_removed_def_and_list_length_changes_are_breaking() -> None:
    old = bump(snapshot(), "1.0")
    old["outputSchema"]["$defs"]["Spare"] = {"type": "string"}
    assert classify(old, bump(snapshot(), "1.1")).change is Change.BREAKING
    union_old = bump(snapshot(), "1.0")
    union_old["outputSchema"]["properties"]["truncated"] = {"anyOf": [{"type": "boolean"}]}
    union_new = bump(snapshot(), "1.1")
    union_new["outputSchema"]["properties"]["truncated"] = {
        "anyOf": [{"type": "boolean"}, {"type": "null"}]
    }
    assert classify(union_old, union_new).change is Change.BREAKING
    same_length = bump(union_old, "1.1")
    assert classify(union_old, same_length).change is Change.NONE


def test_renaming_the_tool_is_breaking() -> None:
    new = bump(snapshot(), "1.1")
    new["name"] = "get_my_holidays"
    assert classify(snapshot(), new).change is Change.BREAKING
