"""Minting: human tokens for the Zulip adapter, worker tokens for the jml-worker."""

import math
import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

import jwt

from tessaro_auth.claims import (
    AUDIENCE,
    ISSUER_BY_KIND,
    MAX_LIFETIME_SECONDS,
    WORKER_SUB_PREFIX,
    Kind,
    Role,
    is_email,
    is_employee_id,
    is_hex32,
    is_workflow_id,
)
from tessaro_auth.keys import Signer
from tessaro_auth.roles import roles_from_groups

ALGORITHM: Final = "EdDSA"


class MintReason(StrEnum):
    """Why a token was refused."""

    WRONG_SIGNER_KIND = "wrong_signer_kind"
    INACTIVE = "inactive"
    MISSING_EMPLOYEE_ID = "missing_employee_id"
    MALFORMED_EMPLOYEE_ID = "malformed_employee_id"
    MALFORMED_EMAIL = "malformed_email"
    MALFORMED_REQUEST_ID = "malformed_request_id"
    NO_ROLE = "no_role"
    MALFORMED_WORKFLOW_ID = "malformed_workflow_id"
    MALFORMED_ON_BEHALF_OF = "malformed_on_behalf_of"


class MintRefused(Exception):
    """No token was minted. `reason` says why; the message never holds identity data."""

    def __init__(self, reason: MintReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectoryIdentity:
    """A user as the adapter reads them from Authentik."""

    employee_id: str | None
    email: str
    groups: tuple[str, ...]
    is_active: bool


def _time_claims(now: datetime, ttl_seconds: int) -> dict[str, int]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    if not 1 <= ttl_seconds <= MAX_LIFETIME_SECONDS:
        raise ValueError(f"ttl_seconds must be 1 to {MAX_LIFETIME_SECONDS}")
    iat = math.floor(now.timestamp())
    return {"iat": iat, "exp": iat + ttl_seconds}


def _sign(claims: dict[str, object], signer: Signer) -> str:
    return jwt.encode(
        claims, signer.private_key, algorithm=ALGORITHM, headers={"kid": signer.kid, "typ": "JWT"}
    )


def _require_signer(signer: Signer, kind: Kind) -> None:
    if signer.kind is not kind:
        raise MintRefused(MintReason.WRONG_SIGNER_KIND)


def _human_roles(identity: DirectoryIdentity, request_id: str) -> tuple[Role, ...]:
    """Run the AC-3 checks in order and return the roles."""
    if not identity.is_active:
        raise MintRefused(MintReason.INACTIVE)
    if not identity.employee_id:
        raise MintRefused(MintReason.MISSING_EMPLOYEE_ID)
    if not is_employee_id(identity.employee_id):
        raise MintRefused(MintReason.MALFORMED_EMPLOYEE_ID)
    if not is_email(identity.email):
        raise MintRefused(MintReason.MALFORMED_EMAIL)
    if not is_hex32(request_id):
        raise MintRefused(MintReason.MALFORMED_REQUEST_ID)
    roles = roles_from_groups(identity.groups)
    if not roles:
        raise MintRefused(MintReason.NO_ROLE)
    return roles


def issue_human_token(
    identity: DirectoryIdentity,
    request_id: str,
    signer: Signer,
    now: datetime,
    ttl_seconds: int,
) -> str:
    """Mint a human token for an Authentik user; raises MintRefused, never a partial token."""
    _require_signer(signer, Kind.HUMAN)
    roles = _human_roles(identity, request_id)
    claims: dict[str, object] = {
        "iss": ISSUER_BY_KIND[Kind.HUMAN],
        "aud": AUDIENCE,
        "sub": identity.employee_id,
        "email": identity.email,
        "kind": Kind.HUMAN.value,
        "roles": [role.value for role in roles],
        "request_id": request_id,
        "jti": secrets.token_hex(16),
        **_time_claims(now, ttl_seconds),
    }
    return _sign(claims, signer)


def issue_worker_token(
    workflow_id: str,
    on_behalf_of: str | None,
    request_id: str,
    signer: Signer,
    now: datetime,
    ttl_seconds: int,
) -> str:
    """Mint a workflow worker token for one activity, naming the approver when there is one."""
    _require_signer(signer, Kind.WORKFLOW_WORKER)
    if not is_workflow_id(workflow_id):
        raise MintRefused(MintReason.MALFORMED_WORKFLOW_ID)
    if on_behalf_of is not None and not is_employee_id(on_behalf_of):
        raise MintRefused(MintReason.MALFORMED_ON_BEHALF_OF)
    if not is_hex32(request_id):
        raise MintRefused(MintReason.MALFORMED_REQUEST_ID)
    claims: dict[str, object] = {
        "iss": ISSUER_BY_KIND[Kind.WORKFLOW_WORKER],
        "aud": AUDIENCE,
        "sub": WORKER_SUB_PREFIX + workflow_id,
        "kind": Kind.WORKFLOW_WORKER.value,
        "roles": [Role.WORKFLOW_WORKER.value],
        "request_id": request_id,
        "jti": secrets.token_hex(16),
        **_time_claims(now, ttl_seconds),
    }
    if on_behalf_of is not None:
        claims["on_behalf_of"] = on_behalf_of
    return _sign(claims, signer)
