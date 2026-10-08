"""Signing and verify keys. A key ID's prefix fixes the one kind and issuer it may sign for."""

import base64
import binascii
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from tessaro_auth.claims import ISSUER_BY_KIND, Kind, kind_of_kid

ED25519_KEY_BYTES: Final = 32
_B64URL = re.compile(r"[A-Za-z0-9_-]*", re.ASCII)


def b64url_encode(raw: bytes) -> str:
    """Unpadded base64url, the JOSE encoding."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    """Strict unpadded base64url decode; raises ValueError on anything else."""
    if _B64URL.fullmatch(text) is None or len(text) % 4 == 1:
        raise ValueError("not unpadded base64url")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except binascii.Error as exc:
        raise ValueError("not unpadded base64url") from exc


def _require_kind(kid: str) -> Kind:
    kind = kind_of_kid(kid)
    if kind is None:
        raise ValueError(f"key id {kid[:64]!r} does not match (adapter|worker)-<n>")
    return kind


def private_key_from_base64url(text: str) -> Ed25519PrivateKey:
    """An Ed25519 private key from the base64url of its raw 32 bytes; ValueError otherwise."""
    raw = b64url_decode(text)
    if len(raw) != ED25519_KEY_BYTES:
        raise ValueError("signing key must be 32 bytes of base64url")
    return Ed25519PrivateKey.from_private_bytes(raw)


def public_key_bytes(key: Ed25519PublicKey) -> bytes:
    """The raw 32 byte public key."""
    return key.public_bytes(Encoding.Raw, PublicFormat.Raw)


@dataclass(frozen=True, slots=True, kw_only=True)
class Signer:
    """A minter's private key, its key ID, and the kind the key ID binds it to."""

    kid: str
    private_key: Ed25519PrivateKey
    kind: Kind

    @classmethod
    def create(cls, kid: str, private_key: Ed25519PrivateKey) -> "Signer":
        """Build a signer, taking the kind from the kid prefix; ValueError on a bad kid."""
        return cls(kid=kid, private_key=private_key, kind=_require_kind(kid))

    @classmethod
    def from_base64url(cls, kid: str, key_b64url: str) -> "Signer":
        """Build a signer from the base64url of a raw 32 byte Ed25519 private key."""
        return cls.create(kid, private_key_from_base64url(key_b64url))

    def __repr__(self) -> str:
        return f"Signer(kid={self.kid!r}, kind={self.kind.value!r})"


@dataclass(frozen=True, slots=True, kw_only=True)
class KeyEntry:
    """One verify key with the only kind and issuer it may vouch for."""

    kid: str
    public_key: Ed25519PublicKey
    kind: Kind
    iss: str

    @classmethod
    def create(cls, kid: str, public_key: Ed25519PublicKey) -> "KeyEntry":
        """Build an entry whose kind and issuer come from the kid prefix."""
        kind = _require_kind(kid)
        return cls(kid=kid, public_key=public_key, kind=kind, iss=ISSUER_BY_KIND[kind])

    def to_jwk(self) -> dict[str, str]:
        """This entry as a JWK set member, with the two Tessaro binding members."""
        return {
            "kty": "OKP",
            "crv": "Ed25519",
            "x": b64url_encode(public_key_bytes(self.public_key)),
            "kid": self.kid,
            "alg": "EdDSA",
            "use": "sig",
            "tessaro_kind": self.kind.value,
            "tessaro_iss": self.iss,
        }


@dataclass(frozen=True, slots=True)
class KeySet(Mapping[str, KeyEntry]):
    """The local, immutable verify keys, by key ID. Keys are never fetched or taken from a token."""

    entries: Mapping[str, KeyEntry]

    @classmethod
    def of(cls, *entries: KeyEntry) -> "KeySet":
        """Build a key set; ValueError on an empty set or a duplicate kid."""
        if not entries:
            raise ValueError("the key set is empty")
        by_kid: dict[str, KeyEntry] = {}
        for entry in entries:
            if entry.kid in by_kid:
                raise ValueError(f"duplicate key id {entry.kid!r}")
            by_kid[entry.kid] = entry
        return cls(MappingProxyType(by_kid))

    def __getitem__(self, kid: str) -> KeyEntry:
        return self.entries[kid]

    def __iter__(self) -> Iterator[str]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def to_jwks_json(self) -> str:
        """The key set as one line of JWK set JSON (the `TOKEN_VERIFY_KEYS` format)."""
        return json.dumps(
            {"keys": [self.entries[kid].to_jwk() for kid in sorted(self.entries)]},
            separators=(",", ":"),
        )


_JWK_REQUIRED = ("kty", "crv", "x", "kid")


def _parse_jwk(member: object) -> KeyEntry:
    if not isinstance(member, dict):
        raise ValueError("every key must be a JSON object")
    for field in _JWK_REQUIRED:
        if not isinstance(member.get(field), str):
            raise ValueError(f"key is missing the string member {field!r}")
    kid: str = member["kid"]
    kind = _require_kind(kid)
    if member["kty"] != "OKP" or member["crv"] != "Ed25519":
        raise ValueError(f"key {kid!r} is not an Ed25519 OKP key")
    raw = b64url_decode(member["x"])
    if len(raw) != ED25519_KEY_BYTES:
        raise ValueError(f"key {kid!r}: x must decode to 32 bytes")
    if "use" in member and member["use"] != "sig":
        raise ValueError(f"key {kid!r}: use must be 'sig'")
    if "alg" in member and member["alg"] != "EdDSA":
        raise ValueError(f"key {kid!r}: alg must be 'EdDSA'")
    if (
        member.get("tessaro_kind") != kind.value
        or member.get("tessaro_iss") != (ISSUER_BY_KIND[kind])
    ):
        raise ValueError(
            f"key {kid!r}: tessaro_kind/tessaro_iss must be {kind.value}/{ISSUER_BY_KIND[kind]}"
        )
    return KeyEntry.create(kid, Ed25519PublicKey.from_public_bytes(raw))


def parse_jwks(text: str) -> KeySet:
    """Parse `TOKEN_VERIFY_KEYS` (a JWK set) into a KeySet; ValueError on any defect."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("TOKEN_VERIFY_KEYS is not valid JSON") from exc
    if not isinstance(document, dict) or not isinstance(document.get("keys"), list):
        raise ValueError('TOKEN_VERIFY_KEYS must be a JWK set: {"keys": [...]}')
    return KeySet.of(*(_parse_jwk(member) for member in document["keys"]))


def check_signer_against(signer: Signer, keyset: KeySet) -> None:
    """Fail when the signer's public key is not its kid's entry in the key set."""
    entry = keyset.get(signer.kid)
    if entry is None:
        raise ValueError(f"signing key id {signer.kid!r} is not in TOKEN_VERIFY_KEYS")
    if public_key_bytes(entry.public_key) != public_key_bytes(signer.private_key.public_key()):
        raise ValueError(f"signing key does not match the verify key {signer.kid!r}")
