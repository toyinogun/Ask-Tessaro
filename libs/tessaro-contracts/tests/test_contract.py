"""Contract checks (AC-13), the registry (AC-14) and the first contract (AC-17)."""

from dataclasses import replace
from typing import Annotated, Any

import pytest
from pydantic import BaseModel, ConfigDict, Field

from tessaro_contracts.contract import ContractError, IdentityMode, ToolContract, WriteSpec
from tessaro_contracts.people.get_my_leave import (
    GET_MY_LEAVE,
    GetMyLeaveOutput,
    LeaveBalance,
    UpcomingLeave,
)
from tessaro_contracts.registry import ALL_CONTRACTS, build_registry, contract_by_name
from tessaro_contracts.scopes import Scope
from tessaro_contracts.testing import assert_contract_ok

CLOSED = ConfigDict(frozen=True, extra="forbid")


class Empty(BaseModel):
    model_config = CLOSED


class Note(BaseModel):
    model_config = CLOSED
    text: str


class WriteInput(BaseModel):
    model_config = CLOSED
    idempotency_key: str
    ticket_id: str


class Done(BaseModel):
    model_config = CLOSED
    ok: bool


def contract(**changes: Any) -> ToolContract:
    fields: dict[str, Any] = {
        "name": "get_note",
        "version": "1.0",
        "owner": "it-team",
        "scope": Scope.IT_READ,
        "identity": IdentityMode.SELF,
        "authorization": "OpenFGA check can_view on note:<id>",
        "description": "Read your note.",
        "input_model": Empty,
        "output_model": Note,
        "never_returns": (),
        "write": None,
    }
    fields.update(changes)
    return ToolContract(**fields)


def write_contract(**changes: Any) -> ToolContract:
    base: dict[str, Any] = {
        "name": "close_ticket",
        "scope": Scope.IT_WRITE,
        "identity": IdentityMode.SUBJECT,
        "input_model": WriteInput,
        "output_model": Done,
        "write": WriteSpec(idempotency_key_param="idempotency_key"),
    }
    base.update(changes)
    return contract(**base)


def test_a_valid_contract_builds() -> None:
    assert contract().major == 1
    assert contract(version="12.7").minor == 7
    assert write_contract().write == WriteSpec(idempotency_key_param="idempotency_key")


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "GetNote"},
        {"name": "1note"},
        {"name": "get-note"},
        {"name": "get_note\n"},
        {"version": "0.1"},
        {"version": "1"},
        {"version": "v1.0"},
        {"version": "1.0.0"},
        {"version": "01.0"},
        {"scope": "it:read"},
        {"identity": "self"},
        {"description": ""},
        {"description": "   "},
        {"authorization": ""},
        {"input_model": dict},
        {"output_model": "Note"},
    ],
)
def test_field_rules(changes: dict[str, Any]) -> None:
    with pytest.raises(ContractError):
        contract(**changes)


class Open(BaseModel):
    model_config = ConfigDict(frozen=True)
    text: str


class Thawed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


class HoldsOpen(BaseModel):
    model_config = CLOSED
    items: tuple[Open, ...]


class HoldsOptional(BaseModel):
    model_config = CLOSED
    maybe: Thawed | None = None


class HoldsMap(BaseModel):
    model_config = CLOSED
    by_id: dict[str, list[Open]]


type OpenAlias = list[Open]


class HoldsAlias(BaseModel):
    model_config = CLOSED
    items: OpenAlias


class HoldsAnnotated(BaseModel):
    model_config = CLOSED
    items: list[Annotated[Open, Field(description="x")]]


@pytest.mark.parametrize(
    "model", [Open, Thawed, HoldsOpen, HoldsOptional, HoldsMap, HoldsAlias, HoldsAnnotated]
)
def test_every_nested_model_must_be_frozen_and_closed(model: type[BaseModel]) -> None:
    with pytest.raises(ContractError, match="frozen"):
        contract(output_model=model)
    with pytest.raises(ContractError, match="frozen"):
        contract(identity=IdentityMode.NONE, input_model=model)


def test_write_rules() -> None:
    with pytest.raises(ContractError, match="needs a WriteSpec"):
        write_contract(write=None)
    with pytest.raises(ContractError, match="only write scopes"):
        contract(write=WriteSpec(idempotency_key_param="idempotency_key"))


class OptionalKey(BaseModel):
    model_config = CLOSED
    idempotency_key: str | None = None


class IntKey(BaseModel):
    model_config = CLOSED
    idempotency_key: int


@pytest.mark.parametrize(
    "changes",
    [
        {"write": WriteSpec(idempotency_key_param="missing")},
        {"input_model": OptionalKey},
        {"input_model": IntKey},
    ],
)
def test_idempotency_key_must_be_a_required_str(changes: dict[str, Any]) -> None:
    with pytest.raises(ContractError, match="idempotency key"):
        write_contract(**changes)


def _input_with(field_name: str, alias: str | None = None) -> type[BaseModel]:
    namespace: dict[str, Any] = {
        "model_config": CLOSED,
        "__annotations__": {field_name: str},
    }
    if alias is not None:
        namespace[field_name] = Field(alias=alias)
    return type("DynamicInput", (BaseModel,), namespace)


@pytest.mark.parametrize(
    ("name", "alias"),
    [
        ("employee_id", None),
        ("employee", None),
        ("user_id", None),
        ("user", None),
        ("email", None),
        ("sub", None),
        ("subject", None),
        ("person_id", None),
        ("target", "employeeId"),
        ("target", "EMPLOYEE_ID"),
        ("target", "Person_Id"),
    ],
)
def test_self_tools_refuse_identity_inputs(name: str, alias: str | None) -> None:
    model = _input_with(name, alias)
    with pytest.raises(ContractError, match="self tool"):
        contract(input_model=model)
    assert contract(identity=IdentityMode.SUBJECT, input_model=model)


class NestedTarget(BaseModel):
    model_config = CLOSED
    user: str


class WrapsTarget(BaseModel):
    model_config = CLOSED
    filters: NestedTarget


def test_self_tools_refuse_nested_identity_inputs() -> None:
    with pytest.raises(ContractError, match="'user'"):
        contract(input_model=WrapsTarget)


def test_identity_check_ignores_schema_text() -> None:
    class Documented(BaseModel):
        """Look up the user's email by employee id."""

        model_config = ConfigDict(frozen=True, extra="forbid", title="user")
        topic: str = Field(description="employee email subject", title="email")

    assert contract(input_model=Documented)


class Inner(BaseModel):
    model_config = CLOSED
    reason: str


class Outer(BaseModel):
    model_config = CLOSED
    entries: tuple[Inner, ...]


class AliasedOut(BaseModel):
    model_config = CLOSED
    why: str = Field(serialization_alias="reason")


def test_never_returns_finds_nested_and_aliased_names() -> None:
    with pytest.raises(ContractError, match="never return reason"):
        contract(output_model=Outer, never_returns=("reason",))
    with pytest.raises(ContractError, match="never return reason"):
        contract(output_model=AliasedOut, never_returns=("reason",))


def test_never_returns_ignores_schema_keywords() -> None:
    class Described(BaseModel):
        """A description that mentions the reason."""

        model_config = ConfigDict(frozen=True, extra="forbid", title="reason")
        text: str = Field(default="reason", description="no reason given", title="salary")

    assert contract(output_model=Described, never_returns=("reason", "salary", "description"))


def test_never_returns_is_exact() -> None:
    class Reasonable(BaseModel):
        model_config = CLOSED
        reasonable: bool
        Reason: str

    assert contract(output_model=Reasonable, never_returns=("reason",))


# AC-17


def test_get_my_leave_passes_every_check() -> None:
    assert_contract_ok(GET_MY_LEAVE)


def test_get_my_leave_output_shape() -> None:
    out = GetMyLeaveOutput(
        balances=(
            LeaveBalance(
                leave_type="vacation",
                year=2026,
                entitled_days=25,
                taken_days=10,
                pending_days=3,
                remaining_days=15,
            ),
        ),
        upcoming=(
            UpcomingLeave(
                application_id="HR-LAP-2026-00012",
                leave_type="sick",
                from_date="2026-10-12",  # type: ignore[arg-type]
                to_date="2026-10-13",  # type: ignore[arg-type]
                status="approved",
            ),
        ),
        truncated=False,
    )
    assert out.model_dump(mode="json")["upcoming"][0]["from_date"] == "2026-10-12"
    with pytest.raises(ValueError, match="at most 1 item"):
        GetMyLeaveOutput(balances=out.balances * 2, upcoming=(), truncated=False)
    with pytest.raises(ValueError, match="at most 50 items"):
        GetMyLeaveOutput(balances=(), upcoming=out.upcoming * 51, truncated=True)
    with pytest.raises(ValueError, match="frozen"):
        out.truncated = True


# AC-14


def test_registry_holds_every_contract() -> None:
    assert dict(ALL_CONTRACTS) == {"get_my_leave": GET_MY_LEAVE}
    assert len(ALL_CONTRACTS) == 1
    assert contract_by_name("get_my_leave") is GET_MY_LEAVE
    with pytest.raises(KeyError):
        contract_by_name("get_your_leave")
    with pytest.raises(TypeError):
        ALL_CONTRACTS.contracts["x"] = GET_MY_LEAVE  # type: ignore[index]


def test_registry_rejects_duplicate_names() -> None:
    with pytest.raises(ContractError, match="duplicate"):
        build_registry([GET_MY_LEAVE, replace(GET_MY_LEAVE, version="1.1")])


def test_registry_checks_undo_tools() -> None:
    reopen = write_contract(name="reopen_ticket")
    close = write_contract(
        write=WriteSpec(idempotency_key_param="idempotency_key", undo_tool="reopen_ticket")
    )
    assert set(build_registry([close, reopen])) == {"close_ticket", "reopen_ticket"}
    with pytest.raises(ContractError, match="undo_tool"):
        build_registry([close])
    with pytest.raises(ContractError, match="undo_tool"):
        build_registry([close, contract(name="reopen_ticket")])
