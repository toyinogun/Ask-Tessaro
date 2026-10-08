"""Tracer bullet: mint a human token for the demo persona and verify it (AC-1, AC-6)."""

from datetime import UTC, datetime, timedelta

import jwt

from tessaro_auth.claims import HumanPrincipal, Role
from tessaro_auth.issue import DirectoryIdentity, issue_human_token
from tessaro_auth.keys import KeySet, Signer
from tessaro_auth.verify import verify

NOW = datetime(2026, 10, 8, 9, 30, 15, 750_000, tzinfo=UTC)
REQUEST_ID = "0123456789abcdef0123456789abcdef"


def test_human_token_round_trip(
    adapter_signer: Signer, keyset: KeySet, persona: DirectoryIdentity
) -> None:
    token = issue_human_token(persona, REQUEST_ID, adapter_signer, NOW, 300)

    assert jwt.get_unverified_header(token) == {"alg": "EdDSA", "kid": "adapter-1", "typ": "JWT"}
    claims = jwt.decode(token, options={"verify_signature": False})
    iat = int(NOW.timestamp())
    assert claims == {
        "iss": "tessaro-adapter",
        "aud": "tessaro-tools",
        "sub": "TES-01007",
        "email": "noor.dekker@tessaro.example",
        "kind": "human",
        "roles": ["employee", "manager"],
        "request_id": REQUEST_ID,
        "jti": claims["jti"],
        "iat": iat,
        "exp": iat + 300,
    }
    assert len(claims["jti"]) == 32
    assert all(c in "0123456789abcdef" for c in claims["jti"])

    principal = verify(token, keyset, NOW + timedelta(seconds=10))

    assert principal == HumanPrincipal(
        employee_id="TES-01007",
        email="noor.dekker@tessaro.example",
        roles=frozenset({Role.EMPLOYEE, Role.MANAGER}),
        request_id=REQUEST_ID,
        token_id=claims["jti"],
        issued_at=datetime.fromtimestamp(iat, UTC),
        expires_at=datetime.fromtimestamp(iat + 300, UTC),
    )
    assert principal.issued_at.tzinfo is UTC


def test_each_token_gets_a_fresh_jti(adapter_signer: Signer, persona: DirectoryIdentity) -> None:
    first = jwt.decode(
        issue_human_token(persona, REQUEST_ID, adapter_signer, NOW, 300),
        options={"verify_signature": False},
    )
    second = jwt.decode(
        issue_human_token(persona, REQUEST_ID, adapter_signer, NOW, 300),
        options={"verify_signature": False},
    )
    assert first["jti"] != second["jti"]
