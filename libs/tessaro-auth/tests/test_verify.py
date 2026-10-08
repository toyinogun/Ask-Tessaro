"""Every verify check in its fixed order, with an injected clock (AC-6 to AC-8)."""

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tessaro_auth.claims import HumanPrincipal, Role, WorkerPrincipal
from tessaro_auth.issue import DirectoryIdentity, issue_human_token, issue_worker_token
from tessaro_auth.keys import KeySet, Signer, b64url_encode, public_key_bytes
from tessaro_auth.verify import InvalidReason, TokenInvalid, verify

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
IAT = int(NOW.timestamp())
RID = "0123456789abcdef0123456789abcdef"
JTI = "fedcba9876543210fedcba9876543210"


def human_claims(**changes: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "iss": "tessaro-adapter",
        "aud": "tessaro-tools",
        "sub": "TES-01007",
        "email": "noor.dekker@tessaro.example",
        "kind": "human",
        "roles": ["employee"],
        "request_id": RID,
        "jti": JTI,
        "iat": IAT,
        "exp": IAT + 300,
    }
    claims.update(changes)
    return {k: v for k, v in claims.items() if v is not DROP}


def worker_claims(**changes: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "iss": "tessaro-jml-worker",
        "aud": "tessaro-tools",
        "sub": "workflow:joiner-TES-01042",
        "kind": "workflow_worker",
        "roles": ["workflow_worker"],
        "request_id": RID,
        "jti": JTI,
        "iat": IAT,
        "exp": IAT + 300,
    }
    claims.update(changes)
    return {k: v for k, v in claims.items() if v is not DROP}


DROP = object()


def sign(claims: dict[str, Any], key: Ed25519PrivateKey, kid: str = "adapter-1", **hdr: Any) -> str:
    return jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": kid, "typ": "JWT", **hdr})


def signed_raw(header: dict[str, Any], claims: dict[str, Any], key: Ed25519PrivateKey) -> str:
    """Sign exactly this header, bypassing PyJWT's header normalisation."""
    signing_input = ".".join(b64url_encode(json.dumps(v).encode()) for v in (header, claims))
    return f"{signing_input}.{b64url_encode(key.sign(signing_input.encode()))}"


def raw_token(header: object, payload: object, signature: str = "c2ln") -> str:
    def part(value: object) -> str:
        return b64url_encode(json.dumps(value).encode())

    return f"{part(header)}.{part(payload)}.{signature}"


def reason_of(token: str, keyset: KeySet, now: datetime = NOW) -> InvalidReason:
    with pytest.raises(TokenInvalid) as caught:
        verify(token, keyset, now)
    assert str(caught.value) == caught.value.reason.value
    return caught.value.reason


# Happy paths


def test_worker_token_round_trip(worker_signer: Signer, keyset: KeySet) -> None:
    token = issue_worker_token("joiner-TES-01042", "TES-01003", RID, worker_signer, NOW, 300)
    principal = verify(token, keyset, NOW)
    assert isinstance(principal, WorkerPrincipal)
    assert principal.workflow_id == "joiner-TES-01042"
    assert principal.on_behalf_of == "TES-01003"
    assert principal.roles == frozenset({Role.WORKFLOW_WORKER})
    assert principal.request_id == RID
    assert principal.expires_at == datetime.fromtimestamp(IAT + 300, UTC)
    assert principal.kind.value == "workflow_worker"


def test_worker_token_without_approver(worker_key: Ed25519PrivateKey, keyset: KeySet) -> None:
    principal = verify(sign(worker_claims(), worker_key, "worker-1"), keyset, NOW)
    assert isinstance(principal, WorkerPrincipal)
    assert principal.on_behalf_of is None


def test_human_principal_kind(
    adapter_signer: Signer, keyset: KeySet, persona: DirectoryIdentity
) -> None:
    principal = verify(issue_human_token(persona, RID, adapter_signer, NOW, 300), keyset, NOW)
    assert principal.kind.value == "human"


def test_principal_is_frozen_and_never_holds_the_token(
    adapter_key: Ed25519PrivateKey, keyset: KeySet
) -> None:
    token = sign(human_claims(), adapter_key)
    principal = verify(token, keyset, NOW)
    assert isinstance(principal, HumanPrincipal)
    with pytest.raises(AttributeError):
        principal.email = "x@y"  # type: ignore[misc]
    assert token not in repr(principal)


def test_verify_rejects_a_naive_clock(adapter_key: Ed25519PrivateKey, keyset: KeySet) -> None:
    with pytest.raises(ValueError, match="timezone"):
        verify(sign(human_claims(), adapter_key), keyset, datetime(2026, 10, 8))


# AC-8: the core security property


def test_worker_kind_signed_by_the_adapter_key_is_refused(
    adapter_key: Ed25519PrivateKey, keyset: KeySet
) -> None:
    forged = sign(worker_claims(), adapter_key, "adapter-1")
    assert reason_of(forged, keyset) is InvalidReason.KIND_NOT_ALLOWED


def test_human_kind_signed_by_the_worker_key_is_refused(
    worker_key: Ed25519PrivateKey, keyset: KeySet
) -> None:
    forged = sign(human_claims(), worker_key, "worker-1")
    assert reason_of(forged, keyset) is InvalidReason.KIND_NOT_ALLOWED


def test_adapter_key_claiming_the_worker_kid_fails_the_signature(
    adapter_key: Ed25519PrivateKey, keyset: KeySet
) -> None:
    forged = sign(worker_claims(), adapter_key, "worker-1")
    assert reason_of(forged, keyset) is InvalidReason.BAD_SIGNATURE


# Step 1: malformed


@pytest.mark.parametrize(
    "token",
    [
        "",
        "abc",
        "a.b",
        "a.b.c.d",
        ".e30.sig",
        "e30..sig",
        "e30=.e30.sig",
        "!!!.e30.sig",
        b64url_encode(b"[1]") + ".e30.sig",
        "e30." + b64url_encode(b'"x"') + ".sig",
        b64url_encode(b"\xff\xfe") + ".e30.sig",
        b64url_encode(b"{not json") + ".e30.sig",
    ],
)
def test_malformed_structure(token: str, keyset: KeySet) -> None:
    assert reason_of(token, keyset) is InvalidReason.MALFORMED


@pytest.mark.parametrize("member", ["jwk", "jku", "x5u", "x5c", "crit", "b64", "cty"])
def test_header_members_beyond_alg_kid_typ_are_refused(
    adapter_key: Ed25519PrivateKey, keyset: KeySet, member: str
) -> None:
    header = {"alg": "EdDSA", "kid": "adapter-1", "typ": "JWT", member: False}
    token = signed_raw(header, human_claims(), adapter_key)
    assert reason_of(token, keyset) is InvalidReason.MALFORMED


def test_signed_raw_helper_builds_a_valid_token(
    adapter_key: Ed25519PrivateKey, keyset: KeySet
) -> None:
    header = {"alg": "EdDSA", "kid": "adapter-1", "typ": "JWT"}
    assert verify(signed_raw(header, human_claims(), adapter_key), keyset, NOW)


def test_embedded_jwk_is_refused_even_with_a_valid_signature(
    adapter_key: Ed25519PrivateKey, keyset: KeySet
) -> None:
    attacker = Ed25519PrivateKey.generate()
    jwk = {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": b64url_encode(public_key_bytes(attacker.public_key())),
    }
    token = sign(human_claims(), attacker, jwk=jwk)
    assert reason_of(token, keyset) is InvalidReason.MALFORMED


def test_typ_other_than_jwt_is_refused(adapter_key: Ed25519PrivateKey, keyset: KeySet) -> None:
    token = jwt.encode(
        human_claims(),
        adapter_key,
        algorithm="EdDSA",
        headers={"kid": "adapter-1", "typ": "at+jwt"},
    )
    assert reason_of(token, keyset) is InvalidReason.MALFORMED


def test_typ_may_be_absent(adapter_key: Ed25519PrivateKey, keyset: KeySet) -> None:
    token = jwt.encode(
        human_claims(), adapter_key, algorithm="EdDSA", headers={"kid": "adapter-1", "typ": None}
    )
    assert "typ" not in jwt.get_unverified_header(token)
    assert verify(token, keyset, NOW).request_id == RID


# Step 2: unknown key


@pytest.mark.parametrize("kid", [None, 7, "adapter-2", "worker-9", "../adapter-1"])
def test_unknown_key(adapter_key: Ed25519PrivateKey, keyset: KeySet, kid: object) -> None:
    header: dict[str, object] = {"alg": "EdDSA", "typ": "JWT"}
    if kid is not None:
        header["kid"] = kid
    assert reason_of(raw_token(header, human_claims()), keyset) is InvalidReason.UNKNOWN_KEY


# Step 3: algorithm


def test_alg_none_is_refused(keyset: KeySet) -> None:
    token = raw_token({"alg": "none", "kid": "adapter-1", "typ": "JWT"}, human_claims(), "")
    assert reason_of(token, keyset) is InvalidReason.BAD_ALGORITHM


def test_hs256_signed_with_the_public_key_is_refused(
    adapter_key: Ed25519PrivateKey, keyset: KeySet
) -> None:
    secret = public_key_bytes(adapter_key.public_key())
    token = jwt.encode(human_claims(), secret, algorithm="HS256", headers={"kid": "adapter-1"})
    assert reason_of(token, keyset) is InvalidReason.BAD_ALGORITHM


def test_missing_alg_is_refused(keyset: KeySet) -> None:
    token = raw_token({"kid": "adapter-1"}, human_claims())
    assert reason_of(token, keyset) is InvalidReason.BAD_ALGORITHM


# Step 4: signature


def test_flipped_payload_byte_fails_the_signature(
    adapter_key: Ed25519PrivateKey, keyset: KeySet
) -> None:
    header, payload, signature = sign(human_claims(), adapter_key).split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["roles"] = ["employee", "manager"]
    tampered = f"{header}.{b64url_encode(json.dumps(claims).encode())}.{signature}"
    assert reason_of(tampered, keyset) is InvalidReason.BAD_SIGNATURE


def test_swapped_signature_fails(adapter_key: Ed25519PrivateKey, keyset: KeySet) -> None:
    first = sign(human_claims(), adapter_key)
    second = sign(human_claims(sub="TES-01008"), adapter_key)
    swapped = ".".join([*second.split(".")[:2], first.split(".")[2]])
    assert reason_of(swapped, keyset) is InvalidReason.BAD_SIGNATURE


def test_garbage_signature_is_bad_signature(keyset: KeySet) -> None:
    token = raw_token({"alg": "EdDSA", "kid": "adapter-1", "typ": "JWT"}, human_claims())
    assert reason_of(token, keyset) is InvalidReason.BAD_SIGNATURE


def test_undecodable_signature_is_malformed(adapter_key: Ed25519PrivateKey, keyset: KeySet) -> None:
    head, body, _ = sign(human_claims(), adapter_key).split(".")
    assert reason_of(f"{head}.{body}.!!", keyset) is InvalidReason.MALFORMED


# Steps 5 to 7: audience, kind, issuer


@pytest.mark.parametrize("aud", [DROP, "tessaro-other", ["tessaro-tools"], None])
def test_wrong_audience(adapter_key: Ed25519PrivateKey, keyset: KeySet, aud: object) -> None:
    token = sign(human_claims(aud=aud), adapter_key)
    assert reason_of(token, keyset) is InvalidReason.WRONG_AUDIENCE


def test_audience_is_checked_before_expiry(adapter_key: Ed25519PrivateKey, keyset: KeySet) -> None:
    token = sign(human_claims(aud="elsewhere", iat=IAT - 3600, exp=IAT - 3300), adapter_key)
    assert reason_of(token, keyset) is InvalidReason.WRONG_AUDIENCE


@pytest.mark.parametrize("kind", [DROP, "admin", "Human"])
def test_kind_must_match_the_key(
    adapter_key: Ed25519PrivateKey, keyset: KeySet, kind: object
) -> None:
    token = sign(human_claims(kind=kind), adapter_key)
    assert reason_of(token, keyset) is InvalidReason.KIND_NOT_ALLOWED


@pytest.mark.parametrize("iss", [DROP, "tessaro-jml-worker", "tessaro-adapter "])
def test_issuer_must_match_the_key(
    adapter_key: Ed25519PrivateKey, keyset: KeySet, iss: object
) -> None:
    token = sign(human_claims(iss=iss), adapter_key)
    assert reason_of(token, keyset) is InvalidReason.WRONG_ISSUER


# Step 8: claim set and integer times


@pytest.mark.parametrize(
    "changes",
    [
        {"email": DROP},
        {"jti": DROP},
        {"extra": "x"},
        {"on_behalf_of": "TES-01003"},
        {"iat": "1"},
        {"exp": 1.5},
        {"iat": True},
        {"exp": IAT},
        {"exp": IAT - 1},
    ],
)
def test_human_claim_set(
    adapter_key: Ed25519PrivateKey, keyset: KeySet, changes: dict[str, object]
) -> None:
    token = sign(human_claims(**changes), adapter_key)
    assert reason_of(token, keyset) is InvalidReason.CLAIMS_INVALID


@pytest.mark.parametrize("changes", [{"email": "x@y"}, {"request_id": DROP}])
def test_worker_claim_set(
    worker_key: Ed25519PrivateKey, keyset: KeySet, changes: dict[str, object]
) -> None:
    token = sign(worker_claims(**changes), worker_key, "worker-1")
    assert reason_of(token, keyset) is InvalidReason.CLAIMS_INVALID


# Steps 9 to 11: lifetime, not before, expiry


def test_lifetime_cap(adapter_key: Ed25519PrivateKey, keyset: KeySet) -> None:
    assert verify(sign(human_claims(exp=IAT + 600), adapter_key), keyset, NOW)
    too_long = sign(human_claims(exp=IAT + 601), adapter_key)
    assert reason_of(too_long, keyset) is InvalidReason.LIFETIME_TOO_LONG


def test_lifetime_is_checked_before_expiry(adapter_key: Ed25519PrivateKey, keyset: KeySet) -> None:
    token = sign(human_claims(iat=IAT - 9000, exp=IAT - 1000), adapter_key)
    assert reason_of(token, keyset) is InvalidReason.LIFETIME_TOO_LONG


def test_not_yet_valid_with_30_seconds_leeway(
    adapter_key: Ed25519PrivateKey, keyset: KeySet
) -> None:
    assert verify(sign(human_claims(iat=IAT + 30, exp=IAT + 330), adapter_key), keyset, NOW)
    early = sign(human_claims(iat=IAT + 31, exp=IAT + 331), adapter_key)
    assert reason_of(early, keyset) is InvalidReason.NOT_YET_VALID


def test_expiry_with_30_seconds_leeway(adapter_key: Ed25519PrivateKey, keyset: KeySet) -> None:
    token = sign(human_claims(), adapter_key)
    exp = NOW + timedelta(seconds=300)
    assert verify(token, keyset, exp + timedelta(seconds=30))
    assert reason_of(token, keyset, exp + timedelta(seconds=31)) is InvalidReason.EXPIRED


def test_longest_accepted_window_is_660_seconds(
    adapter_key: Ed25519PrivateKey, keyset: KeySet
) -> None:
    token = sign(human_claims(iat=IAT + 30, exp=IAT + 630), adapter_key)
    assert verify(token, keyset, NOW)
    assert verify(token, keyset, NOW + timedelta(seconds=660))
    assert reason_of(token, keyset, NOW + timedelta(seconds=661)) is InvalidReason.EXPIRED


# Step 12: claim values


@pytest.mark.parametrize(
    "changes",
    [
        {"sub": "TES-1007"},
        {"sub": 1007},
        {"email": "not an email"},
        {"email": None},
        {"request_id": "ABCDEF0123456789abcdef0123456789"},
        {"jti": "short"},
        {"jti": 12},
        {"roles": []},
        {"roles": "employee"},
        {"roles": ["employee", "employee"]},
        {"roles": ["employee", "admin"]},
        {"roles": ["employee", 1]},
        {"roles": ["workflow_worker"]},
        {"roles": ["employee", "workflow_worker"]},
    ],
)
def test_human_claim_values(
    adapter_key: Ed25519PrivateKey, keyset: KeySet, changes: dict[str, object]
) -> None:
    token = sign(human_claims(**changes), adapter_key)
    assert reason_of(token, keyset) is InvalidReason.CLAIMS_INVALID


@pytest.mark.parametrize(
    "changes",
    [
        {"sub": "joiner-TES-01042"},
        {"sub": "workflow:onboard-TES-01042"},
        {"sub": "workflow:joiner-TES-01042-2026-02-30"},
        {"sub": 5},
        {"on_behalf_of": "maria"},
        {"on_behalf_of": None},
        {"roles": ["workflow_worker", "employee"]},
        {"roles": ["employee"]},
        {"roles": []},
    ],
)
def test_worker_claim_values(
    worker_key: Ed25519PrivateKey, keyset: KeySet, changes: dict[str, object]
) -> None:
    token = sign(worker_claims(**changes), worker_key, "worker-1")
    assert reason_of(token, keyset) is InvalidReason.CLAIMS_INVALID


def test_claim_values_are_checked_after_expiry(
    adapter_key: Ed25519PrivateKey, keyset: KeySet
) -> None:
    token = sign(human_claims(sub="bad", iat=IAT - 1000, exp=IAT - 700), adapter_key)
    assert reason_of(token, keyset) is InvalidReason.EXPIRED


def test_pyjwt_errors_map_once() -> None:
    from tessaro_auth.verify import _pyjwt_reason

    assert _pyjwt_reason(jwt.InvalidSignatureError()) is InvalidReason.BAD_SIGNATURE
    assert _pyjwt_reason(jwt.InvalidAudienceError()) is InvalidReason.WRONG_AUDIENCE
    assert _pyjwt_reason(jwt.MissingRequiredClaimError("aud")) is InvalidReason.CLAIMS_INVALID
    assert _pyjwt_reason(jwt.DecodeError()) is InvalidReason.MALFORMED
    assert _pyjwt_reason(jwt.ImmatureSignatureError()) is InvalidReason.MALFORMED
