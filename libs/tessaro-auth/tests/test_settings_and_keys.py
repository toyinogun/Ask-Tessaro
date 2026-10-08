"""Fail fast key parsing and settings (AC-9)."""

import json
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from tessaro_auth.claims import Kind
from tessaro_auth.devkeys import _private_b64url
from tessaro_auth.keys import (
    KeyEntry,
    KeySet,
    Signer,
    b64url_decode,
    b64url_encode,
    check_signer_against,
    parse_jwks,
    public_key_bytes,
)
from tessaro_auth.settings import TokenSigningSettings, TokenVerifySettings


def jwk(key: Ed25519PrivateKey, kid: str, **changes: Any) -> dict[str, Any]:
    member: dict[str, Any] = KeyEntry.create(kid, key.public_key()).to_jwk()
    member.update(changes)
    return {k: v for k, v in member.items() if v is not None}


def jwks(*members: dict[str, Any]) -> str:
    return json.dumps({"keys": list(members)})


def test_round_trip(keyset: KeySet) -> None:
    parsed = parse_jwks(keyset.to_jwks_json())
    assert set(parsed) == {"adapter-1", "worker-1"}
    assert parsed["adapter-1"].kind is Kind.HUMAN
    assert parsed["adapter-1"].iss == "tessaro-adapter"
    assert parsed["worker-1"].kind is Kind.WORKFLOW_WORKER
    assert parsed["worker-1"].iss == "tessaro-jml-worker"
    assert len(parsed) == 2


def test_several_kids_per_kind_are_allowed_for_rotation(adapter_key: Ed25519PrivateKey) -> None:
    other = Ed25519PrivateKey.generate()
    parsed = parse_jwks(jwks(jwk(adapter_key, "adapter-1"), jwk(other, "adapter-2")))
    assert set(parsed) == {"adapter-1", "adapter-2"}


def test_use_and_alg_are_optional(adapter_key: Ed25519PrivateKey) -> None:
    assert parse_jwks(jwks(jwk(adapter_key, "adapter-1", use=None, alg=None)))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{not json", "not valid JSON"),
        ("[]", "JWK set"),
        ('{"keys": {}}', "JWK set"),
        ('{"keys": []}', "empty"),
        ('{"keys": ["x"]}', "JSON object"),
    ],
)
def test_structural_defects(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_jwks(text)


@pytest.mark.parametrize(
    ("kid", "changes", "message"),
    [
        ("adapter-1", {"kty": "EC"}, "Ed25519"),
        ("adapter-1", {"crv": "X25519"}, "Ed25519"),
        ("adapter-1", {"kty": None}, "kty"),
        ("adapter-1", {"x": "AAAA"}, "32 bytes"),
        ("adapter-1", {"x": "not base64!"}, "base64url"),
        ("adapter-1", {"use": "enc"}, "use"),
        ("adapter-1", {"alg": "RS256"}, "alg"),
        ("adapter-1", {"tessaro_kind": "workflow_worker"}, "tessaro_kind"),
        ("adapter-1", {"tessaro_iss": "tessaro-jml-worker"}, "tessaro_kind"),
        ("adapter-1", {"tessaro_kind": None}, "tessaro_kind"),
        ("worker-1", {"tessaro_kind": "human", "tessaro_iss": "tessaro-adapter"}, "tessaro"),
        ("admin-1", {}, "does not match"),
        ("adapter-", {}, "does not match"),
        ("adapter-1a", {}, "does not match"),
    ],
)
def test_member_defects(
    adapter_key: Ed25519PrivateKey, kid: str, changes: dict[str, Any], message: str
) -> None:
    member = jwk(adapter_key, "worker-1" if kid == "worker-1" else "adapter-1", **changes)
    member["kid"] = kid
    with pytest.raises(ValueError, match=message):
        parse_jwks(jwks(member))


def test_duplicate_kid(adapter_key: Ed25519PrivateKey) -> None:
    member = jwk(adapter_key, "adapter-1")
    with pytest.raises(ValueError, match="duplicate"):
        parse_jwks(jwks(member, member))


def test_empty_keyset_is_refused() -> None:
    with pytest.raises(ValueError, match="empty"):
        KeySet.of()


def test_b64url_decode_is_strict() -> None:
    assert b64url_decode(b64url_encode(b"\x00\x01\x02")) == b"\x00\x01\x02"
    for bad in ("a", "ab==", "a+b/", "a b"):
        with pytest.raises(ValueError, match="base64url"):
            b64url_decode(bad)


def test_signer_repr_never_shows_the_key(adapter_key: Ed25519PrivateKey) -> None:
    signer = Signer.from_base64url("adapter-1", _private_b64url(adapter_key))
    assert repr(signer) == "Signer(kid='adapter-1', kind='human')"
    assert public_key_bytes(signer.private_key.public_key()) == public_key_bytes(
        adapter_key.public_key()
    )


# check_signer_against


def test_matching_signer_passes(adapter_signer: Signer, keyset: KeySet) -> None:
    check_signer_against(adapter_signer, keyset)


def test_signer_with_another_key_fails(keyset: KeySet) -> None:
    impostor = Signer.create("adapter-1", Ed25519PrivateKey.generate())
    with pytest.raises(ValueError, match="does not match"):
        check_signer_against(impostor, keyset)


def test_signer_kid_missing_from_the_keyset_fails(adapter_key: Ed25519PrivateKey) -> None:
    keyset = KeySet.of(KeyEntry.create("worker-1", Ed25519PrivateKey.generate().public_key()))
    with pytest.raises(ValueError, match="not in TOKEN_VERIFY_KEYS"):
        check_signer_against(Signer.create("adapter-1", adapter_key), keyset)


# Settings


def test_verify_settings_parse_the_keyset(monkeypatch: pytest.MonkeyPatch, keyset: KeySet) -> None:
    monkeypatch.setenv("TOKEN_VERIFY_KEYS", keyset.to_jwks_json())
    settings = TokenVerifySettings()
    assert set(settings.keyset) == {"adapter-1", "worker-1"}


def test_verify_settings_parse_the_keyset_once(
    monkeypatch: pytest.MonkeyPatch, keyset: KeySet
) -> None:
    monkeypatch.setenv("TOKEN_VERIFY_KEYS", keyset.to_jwks_json())
    settings = TokenVerifySettings()
    assert settings.keyset is settings.keyset


@pytest.mark.parametrize("value", [None, "", "{}", '{"keys": []}'])
def test_verify_settings_fail_fast(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("TOKEN_VERIFY_KEYS", raising=False)
    else:
        monkeypatch.setenv("TOKEN_VERIFY_KEYS", value)
    with pytest.raises(ValidationError):
        TokenVerifySettings()


def test_signing_settings(monkeypatch: pytest.MonkeyPatch, worker_key: Ed25519PrivateKey) -> None:
    monkeypatch.setenv("TOKEN_SIGNING_KEY", _private_b64url(worker_key))
    monkeypatch.setenv("TOKEN_SIGNING_KID", "worker-1")
    monkeypatch.setenv("TOKEN_TTL_SECONDS", "")
    settings = TokenSigningSettings()
    assert settings.token_ttl_seconds == 300
    assert settings.signer.kind is Kind.WORKFLOW_WORKER
    assert settings.signer.kid == "worker-1"
    assert settings.signer is settings.signer
    assert "token_signing_key=SecretStr('**********')" in repr(settings)


@pytest.mark.parametrize(
    "env",
    [
        {"TOKEN_SIGNING_KEY": None},
        {"TOKEN_SIGNING_KEY": ""},
        {"TOKEN_SIGNING_KID": None},
        {"TOKEN_SIGNING_KEY": "AAAA"},
        {"TOKEN_SIGNING_KEY": "not base64!"},
        {"TOKEN_SIGNING_KID": "signer-1"},
        {"TOKEN_TTL_SECONDS": "0"},
        {"TOKEN_TTL_SECONDS": "601"},
        {"TOKEN_TTL_SECONDS": "five"},
    ],
)
def test_signing_settings_fail_fast(
    monkeypatch: pytest.MonkeyPatch, adapter_key: Ed25519PrivateKey, env: dict[str, str | None]
) -> None:
    base: dict[str, str | None] = {
        "TOKEN_SIGNING_KEY": _private_b64url(adapter_key),
        "TOKEN_SIGNING_KID": "adapter-1",
        "TOKEN_TTL_SECONDS": "300",
        **env,
    }
    for name, value in base.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError) as caught:
        TokenSigningSettings()
    assert _private_b64url(adapter_key) not in str(caught.value)


def test_ttl_bounds_are_inclusive(
    monkeypatch: pytest.MonkeyPatch, adapter_key: Ed25519PrivateKey
) -> None:
    monkeypatch.setenv("TOKEN_SIGNING_KEY", _private_b64url(adapter_key))
    monkeypatch.setenv("TOKEN_SIGNING_KID", "adapter-1")
    for ttl in ("1", "600"):
        monkeypatch.setenv("TOKEN_TTL_SECONDS", ttl)
        assert TokenSigningSettings().token_ttl_seconds == int(ttl)
