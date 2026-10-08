"""Verification: every check in the fixed spec 0003 AC-7 order, first failure wins."""

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, TypeGuard

import jwt

from tessaro_auth.claims import (
    AUDIENCE,
    CLOCK_LEEWAY_SECONDS,
    HUMAN_CLAIMS,
    MAX_LIFETIME_SECONDS,
    WORKER_CLAIMS,
    WORKER_OPTIONAL_CLAIMS,
    WORKER_SUB_PREFIX,
    HumanPrincipal,
    Kind,
    Principal,
    Role,
    WorkerPrincipal,
    is_email,
    is_employee_id,
    is_hex32,
    is_workflow_id,
)
from tessaro_auth.issue import ALGORITHM
from tessaro_auth.keys import KeyEntry, KeySet, b64url_decode

_ALLOWED_HEADER_MEMBERS: Final = frozenset({"alg", "kid", "typ"})
_ROLE_VALUES: Final = frozenset(role.value for role in Role)

Claims = Mapping[str, object]


class InvalidReason(StrEnum):
    """Why a token was rejected, in check order."""

    MALFORMED = "malformed"
    UNKNOWN_KEY = "unknown_key"
    BAD_ALGORITHM = "bad_algorithm"
    BAD_SIGNATURE = "bad_signature"
    WRONG_AUDIENCE = "wrong_audience"
    KIND_NOT_ALLOWED = "kind_not_allowed"
    WRONG_ISSUER = "wrong_issuer"
    CLAIMS_INVALID = "claims_invalid"
    LIFETIME_TOO_LONG = "lifetime_too_long"
    NOT_YET_VALID = "not_yet_valid"
    EXPIRED = "expired"


class TokenInvalid(Exception):
    """The token was rejected. The message is the reason only, never token content."""

    def __init__(self, reason: InvalidReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


_PYJWT_REASONS: Final[tuple[tuple[type[jwt.PyJWTError], InvalidReason], ...]] = (
    (jwt.InvalidSignatureError, InvalidReason.BAD_SIGNATURE),
    (jwt.InvalidAudienceError, InvalidReason.WRONG_AUDIENCE),
    (jwt.MissingRequiredClaimError, InvalidReason.CLAIMS_INVALID),
    (jwt.DecodeError, InvalidReason.MALFORMED),
)
"""PyJWT exceptions, mapped once. Order matters: InvalidSignatureError is a DecodeError."""


def _fail(reason: InvalidReason) -> TokenInvalid:
    return TokenInvalid(reason)


def _json_object(segment: str) -> dict[str, object]:
    try:
        value = json.loads(b64url_decode(segment))
    except (ValueError, UnicodeDecodeError) as exc:
        raise _fail(InvalidReason.MALFORMED) from exc
    if not isinstance(value, dict):
        raise _fail(InvalidReason.MALFORMED)
    return value


def _check_header(token: str) -> dict[str, object]:
    """Step 1: three base64url parts, JSON objects, only `alg`, `kid`, `typ` in the header."""
    parts = token.split(".")
    if len(parts) != 3 or not parts[0] or not parts[1]:
        raise _fail(InvalidReason.MALFORMED)
    header = _json_object(parts[0])
    _json_object(parts[1])
    if not header.keys() <= _ALLOWED_HEADER_MEMBERS:
        raise _fail(InvalidReason.MALFORMED)
    if "typ" in header and header["typ"] != "JWT":
        raise _fail(InvalidReason.MALFORMED)
    return header


def _entry_for(header: Mapping[str, object], keyset: KeySet) -> KeyEntry:
    """Step 2: the kid must name a key in the local set."""
    kid = header.get("kid")
    if not isinstance(kid, str) or kid not in keyset:
        raise _fail(InvalidReason.UNKNOWN_KEY)
    return keyset[kid]


def _verified_claims(token: str, entry: KeyEntry) -> dict[str, Any]:
    """Step 4: the signature, with a typed Ed25519 key and only EdDSA allowed."""
    try:
        # Any: PyJWT returns the payload as dict[str, Any]; every claim is type checked below.
        claims: dict[str, Any] = jwt.decode(
            token,
            key=entry.public_key,
            algorithms=[ALGORITHM],
            options={
                "verify_aud": False,
                "verify_iss": False,
                "verify_exp": False,
                "verify_nbf": False,
                "verify_iat": False,
                "verify_sub": False,
                "verify_jti": False,
            },
        )
    except jwt.PyJWTError as exc:
        raise _fail(_pyjwt_reason(exc)) from exc
    return claims


def _pyjwt_reason(exc: jwt.PyJWTError) -> InvalidReason:
    for exc_type, reason in _PYJWT_REASONS:
        if isinstance(exc, exc_type):
            return reason
    return InvalidReason.MALFORMED


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_claim_set(claims: Claims, kind: Kind) -> tuple[int, int]:
    """Step 8: exactly the claims for the kind, integer times, and `exp > iat`."""
    names = claims.keys()
    if kind is Kind.HUMAN:
        exact = names == HUMAN_CLAIMS
    else:
        exact = WORKER_CLAIMS <= names <= WORKER_CLAIMS | WORKER_OPTIONAL_CLAIMS
    iat, exp = claims.get("iat"), claims.get("exp")
    if not exact or not _is_int(iat) or not _is_int(exp):
        raise _fail(InvalidReason.CLAIMS_INVALID)
    if exp <= iat:
        raise _fail(InvalidReason.CLAIMS_INVALID)
    return iat, exp


def _check_times(iat: int, exp: int, now: datetime) -> None:
    """Steps 9 to 11: lifetime cap, then not before, then expiry, each with the leeway."""
    if exp - iat > MAX_LIFETIME_SECONDS:
        raise _fail(InvalidReason.LIFETIME_TOO_LONG)
    instant = now.timestamp()
    if iat > instant + CLOCK_LEEWAY_SECONDS:
        raise _fail(InvalidReason.NOT_YET_VALID)
    if instant > exp + CLOCK_LEEWAY_SECONDS:
        raise _fail(InvalidReason.EXPIRED)


def _valid_str(value: object, check: Callable[[str], bool]) -> TypeGuard[str]:
    return isinstance(value, str) and check(value)


def _human_roles(roles: object) -> frozenset[Role] | None:
    if not isinstance(roles, list) or not roles:
        return None
    if not all(isinstance(r, str) and r in _ROLE_VALUES for r in roles):
        return None
    if len(set(roles)) != len(roles) or Role.WORKFLOW_WORKER.value in roles:
        return None
    return frozenset(Role(r) for r in roles)


def _human_principal(claims: Claims, iat: int, exp: int) -> HumanPrincipal:
    sub, email, roles = claims["sub"], claims["email"], _human_roles(claims["roles"])
    if not _valid_str(sub, is_employee_id) or not _valid_str(email, is_email) or roles is None:
        raise _fail(InvalidReason.CLAIMS_INVALID)
    return HumanPrincipal(
        employee_id=sub,
        email=email,
        roles=roles,
        request_id=str(claims["request_id"]),
        token_id=str(claims["jti"]),
        issued_at=datetime.fromtimestamp(iat, UTC),
        expires_at=datetime.fromtimestamp(exp, UTC),
    )


def _worker_principal(claims: Claims, iat: int, exp: int) -> WorkerPrincipal:
    sub, on_behalf_of = claims["sub"], claims.get("on_behalf_of")
    workflow_id = sub[len(WORKER_SUB_PREFIX) :] if isinstance(sub, str) else ""
    if (
        not isinstance(sub, str)
        or not sub.startswith(WORKER_SUB_PREFIX)
        or not is_workflow_id(workflow_id)
        or ("on_behalf_of" in claims and not _valid_str(on_behalf_of, is_employee_id))
        or claims["roles"] != [Role.WORKFLOW_WORKER.value]
    ):
        raise _fail(InvalidReason.CLAIMS_INVALID)
    return WorkerPrincipal(
        workflow_id=workflow_id,
        on_behalf_of=on_behalf_of if isinstance(on_behalf_of, str) else None,
        roles=frozenset({Role.WORKFLOW_WORKER}),
        request_id=str(claims["request_id"]),
        token_id=str(claims["jti"]),
        issued_at=datetime.fromtimestamp(iat, UTC),
        expires_at=datetime.fromtimestamp(exp, UTC),
    )


def verify(token: str, keyset: KeySet, now: datetime) -> Principal:
    """Verify a token against the local key set at `now`; raises TokenInvalid(reason)."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    header = _check_header(token)
    entry = _entry_for(header, keyset)
    if header.get("alg") != ALGORITHM:
        raise _fail(InvalidReason.BAD_ALGORITHM)
    claims = _verified_claims(token, entry)
    if claims.get("aud") != AUDIENCE:
        raise _fail(InvalidReason.WRONG_AUDIENCE)
    if claims.get("kind") != entry.kind.value:
        raise _fail(InvalidReason.KIND_NOT_ALLOWED)
    if claims.get("iss") != entry.iss:
        raise _fail(InvalidReason.WRONG_ISSUER)
    iat, exp = _check_claim_set(claims, entry.kind)
    _check_times(iat, exp, now)
    if not _valid_str(claims["request_id"], is_hex32) or not _valid_str(claims["jti"], is_hex32):
        raise _fail(InvalidReason.CLAIMS_INVALID)
    if entry.kind is Kind.HUMAN:
        return _human_principal(claims, iat, exp)
    return _worker_principal(claims, iat, exp)
