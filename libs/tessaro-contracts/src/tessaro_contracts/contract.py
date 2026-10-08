"""The tool contract: one typed, versioned definition per tool (spec 0003 AC-13)."""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from pydantic import BaseModel

from tessaro_contracts.schema_rules import (
    all_names,
    is_frozen_and_closed,
    nested_models,
    normalized_name,
)
from tessaro_contracts.scopes import Scope

_NAME: Final = re.compile(r"[a-z][a-z0-9_]*", re.ASCII)
_VERSION: Final = re.compile(r"[1-9]\d*\.\d+", re.ASCII)

SELF_FORBIDDEN_INPUTS: Final = frozenset(
    {"employeeid", "employee", "userid", "user", "email", "sub", "subject", "personid"}
)
"""Normalized input names a self scoped tool may never accept: identity comes from the token."""


class ContractError(Exception):
    """A contract or registry breaks a rule. Raised at import, so a bad tool never loads."""


class IdentityMode(StrEnum):
    """Where a tool takes the person it acts on from."""

    SELF = "self"
    """The token only; no person field is accepted."""
    SUBJECT = "subject"
    """The input names a target person; the tool checks OpenFGA for the caller against them."""
    NONE = "none"
    """The tool returns no per person data (for example handbook search)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WriteSpec:
    """What a write tool needs: its idempotency key input and an optional undo tool."""

    idempotency_key_param: str
    undo_tool: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolContract:
    """A tool's name, version, owner, scope, identity rule, schemas and redaction list.

    Construction runs every AC-13 check and raises ContractError on the first failure.
    """

    name: str
    version: str
    owner: str
    scope: Scope
    identity: IdentityMode
    authorization: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    never_returns: tuple[str, ...] = ()
    write: WriteSpec | None = field(default=None)

    def __post_init__(self) -> None:
        validate_contract(self)

    @property
    def major(self) -> int:
        """The major part of the version."""
        return int(self.version.split(".")[0])

    @property
    def minor(self) -> int:
        """The minor part of the version."""
        return int(self.version.split(".")[1])


def validate_contract(contract: ToolContract) -> None:
    """Run every AC-13 check on a contract; raises ContractError naming the first failure."""
    _check_identity_fields(contract)
    _check_models(contract)
    _check_write(contract)
    _check_self_inputs(contract)
    _check_never_returns(contract)


def _check_identity_fields(contract: ToolContract) -> None:
    name = contract.name
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise ContractError(f"tool name {name!r} must match [a-z][a-z0-9_]*")
    if not isinstance(contract.version, str) or _VERSION.fullmatch(contract.version) is None:
        raise ContractError(f"{name}: version {contract.version!r} must look like 1.0")
    if not isinstance(contract.scope, Scope):
        raise ContractError(f"{name}: scope {contract.scope!r} is not a Scope member")
    if not isinstance(contract.identity, IdentityMode):
        raise ContractError(f"{name}: identity {contract.identity!r} is not an IdentityMode")
    for label in ("description", "authorization"):
        value = getattr(contract, label)
        if not isinstance(value, str) or not value.strip():
            raise ContractError(f"{name}: {label} must not be empty")


def _check_models(contract: ToolContract) -> None:
    for label in ("input_model", "output_model"):
        model = getattr(contract, label)
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            raise ContractError(f"{contract.name}: {label} must be a pydantic model")
        for nested in nested_models(model):
            if not is_frozen_and_closed(nested):
                raise ContractError(
                    f"{contract.name}: {nested.__name__} must be frozen with extra='forbid'"
                )


def _check_write(contract: ToolContract) -> None:
    write = contract.write
    if contract.scope.is_write and write is None:
        raise ContractError(f"{contract.name}: a write scope needs a WriteSpec")
    if not contract.scope.is_write and write is not None:
        raise ContractError(f"{contract.name}: only write scopes take a WriteSpec")
    if write is None:
        return
    key_field = contract.input_model.model_fields.get(write.idempotency_key_param)
    if key_field is None or not key_field.is_required() or key_field.annotation is not str:
        raise ContractError(
            f"{contract.name}: idempotency key {write.idempotency_key_param!r} "
            "must be a required str input field"
        )


def _check_self_inputs(contract: ToolContract) -> None:
    if contract.identity is not IdentityMode.SELF:
        return
    for name in all_names(contract.input_model):
        if normalized_name(name) in SELF_FORBIDDEN_INPUTS:
            raise ContractError(
                f"{contract.name}: a self tool takes identity from the token, "
                f"not the input field {name!r}"
            )


def _check_never_returns(contract: ToolContract) -> None:
    leaked = sorted(set(contract.never_returns) & all_names(contract.output_model))
    if leaked:
        raise ContractError(f"{contract.name}: output must never return {', '.join(leaked)}")
