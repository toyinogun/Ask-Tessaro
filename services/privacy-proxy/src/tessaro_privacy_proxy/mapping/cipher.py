"""Keys for the mapping: HMAC lookup fields and AES-256-GCM values bound to their conversation."""

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tessaro_privacy_proxy.masking.errors import MappingStoreUnavailable

KEY_BYTES = 32
_NONCE_BYTES = 12


def decode_key(text: str) -> bytes:
    """An unpadded base64url key of exactly 32 bytes; raises ValueError otherwise."""
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except ValueError as exc:
        raise ValueError("key is not base64url") from exc
    if len(raw) != KEY_BYTES:
        raise ValueError(f"key must be {KEY_BYTES} bytes, got {len(raw)}")
    return raw


def encode_key(raw: bytes) -> str:
    """Unpadded base64url, the format `decode_key` reads."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _associated_data(conversation_id: str, entity_type: str) -> bytes:
    return f"{conversation_id}|{entity_type}".encode()


@dataclass(frozen=True)
class MappingCipher:
    """Two separate keys: one only tests "seen before?", one only reads values."""

    mapping_key: bytes
    lookup_key: bytes

    def lookup_field(self, key: str) -> str:
        """Hex HMAC-SHA256 of an entity key: comparable, but not reversible or guessable."""
        return hmac.new(self.lookup_key, key.encode(), hashlib.sha256).hexdigest()

    def encrypt(self, conversation_id: str, entity_type: str, original: str) -> str:
        """base64url(nonce + ciphertext), with the conversation and type as associated data."""
        nonce = os.urandom(_NONCE_BYTES)
        sealed = AESGCM(self.mapping_key).encrypt(
            nonce, original.encode(), _associated_data(conversation_id, entity_type)
        )
        return encode_key(nonce + sealed)

    def decrypt(self, conversation_id: str, entity_type: str, stored: str) -> str:
        """The original text; raises `MappingStoreUnavailable` when it does not decrypt here."""
        try:
            raw = base64.urlsafe_b64decode(stored + "=" * (-len(stored) % 4))
            opened = AESGCM(self.mapping_key).decrypt(
                raw[:_NONCE_BYTES],
                raw[_NONCE_BYTES:],
                _associated_data(conversation_id, entity_type),
            )
        except (InvalidTag, ValueError) as exc:
            raise MappingStoreUnavailable("a stored mapping value did not decrypt") from exc
        return opened.decode()
