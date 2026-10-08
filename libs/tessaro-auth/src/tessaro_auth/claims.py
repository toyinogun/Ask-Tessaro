"""Claim vocabulary: roles, kinds, issuers, the ID patterns and the verified Principals."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Final

AUDIENCE: Final = "tessaro-tools"
ISSUER_ADAPTER: Final = "tessaro-adapter"
ISSUER_WORKER: Final = "tessaro-jml-worker"

MAX_LIFETIME_SECONDS: Final = 600
"""No token may claim a lifetime longer than this (`exp - iat`)."""

CLOCK_LEEWAY_SECONDS: Final = 30
"""Allowed clock skew on both `iat` and `exp`."""


class Role(StrEnum):
    """Every role a token can carry. `workflow_worker` only ever appears on worker tokens."""

    EMPLOYEE = "employee"
    MANAGER = "manager"
    IT_SERVICE_DESK = "it_service_desk"
    PEOPLE_ADVISOR = "people_advisor"
    WORKFLOW_WORKER = "workflow_worker"


class Kind(StrEnum):
    """Who a token speaks for: a human employee or a workflow worker."""

    HUMAN = "human"
    WORKFLOW_WORKER = "workflow_worker"


ISSUER_BY_KIND: Final = {Kind.HUMAN: ISSUER_ADAPTER, Kind.WORKFLOW_WORKER: ISSUER_WORKER}
KID_PREFIX_BY_KIND: Final = {Kind.HUMAN: "adapter", Kind.WORKFLOW_WORKER: "worker"}

HUMAN_CLAIMS: Final = frozenset(
    {"iss", "aud", "sub", "email", "kind", "roles", "request_id", "jti", "iat", "exp"}
)
WORKER_CLAIMS: Final = frozenset(
    {"iss", "aud", "sub", "kind", "roles", "request_id", "jti", "iat", "exp"}
)
WORKER_OPTIONAL_CLAIMS: Final = frozenset({"on_behalf_of"})

_EMPLOYEE_ID = re.compile(r"TES-\d{5}", re.ASCII)
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+", re.ASCII)
_HEX32 = re.compile(r"[0-9a-f]{32}", re.ASCII)
_WORKFLOW_ID = re.compile(
    r"(joiner|mover|leaver)-TES-\d{5}(?:-(?P<date>\d{4}-\d{2}-\d{2}))?", re.ASCII
)
_KID = re.compile(r"(adapter|worker)-\d+", re.ASCII)
WORKER_SUB_PREFIX: Final = "workflow:"


def is_employee_id(value: str) -> bool:
    """True when `value` is a Tessaro employee ID (`TES-` and five digits)."""
    return _EMPLOYEE_ID.fullmatch(value) is not None


def is_email(value: str) -> bool:
    """True when `value` looks like one email address (no spaces, exactly one `@`)."""
    return _EMAIL.fullmatch(value) is not None


def is_hex32(value: str) -> bool:
    """True for 32 lowercase hex characters: the request ID and `jti` format."""
    return _HEX32.fullmatch(value) is not None


def is_workflow_id(value: str) -> bool:
    """True for a JML workflow ID whose optional date part is a real calendar date."""
    match = _WORKFLOW_ID.fullmatch(value)
    if match is None:
        return False
    day = match.group("date")
    if day is None:
        return True
    try:
        date.fromisoformat(day)
    except ValueError:
        return False
    return True


def kind_of_kid(kid: str) -> Kind | None:
    """The kind a key ID is bound to by its prefix, or None when the kid is malformed."""
    match = _KID.fullmatch(kid)
    if match is None:
        return None
    return Kind.HUMAN if match.group(1) == "adapter" else Kind.WORKFLOW_WORKER


@dataclass(frozen=True, slots=True, kw_only=True)
class HumanPrincipal:
    """A verified human caller. Never holds the raw token."""

    employee_id: str
    email: str
    roles: frozenset[Role]
    request_id: str
    token_id: str
    issued_at: datetime
    expires_at: datetime

    @property
    def kind(self) -> Kind:
        """Always `Kind.HUMAN`."""
        return Kind.HUMAN


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkerPrincipal:
    """A verified workflow worker, optionally acting on an approver's behalf."""

    workflow_id: str
    on_behalf_of: str | None
    roles: frozenset[Role]
    request_id: str
    token_id: str
    issued_at: datetime
    expires_at: datetime

    @property
    def kind(self) -> Kind:
        """Always `Kind.WORKFLOW_WORKER`."""
        return Kind.WORKFLOW_WORKER


Principal = HumanPrincipal | WorkerPrincipal
