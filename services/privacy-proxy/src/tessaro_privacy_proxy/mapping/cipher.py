"""Keys for the mapping: HMAC lookup fields and AES-256-GCM values bound to their conversation."""

import base64
import hashlib
import hmac
import os
import re
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tessaro_privacy_proxy.masking.errors import MappingStoreUnavailable

KEY_BYTES = 32
_NONCE_BYTES = 12
_BASE64URL = re.compile(r"[A-Za-z0-9_-]*")


def _b64decode(text: str) -> bytes:
    """Strict unpadded base64url: any other character is an error, never silently dropped."""
    if _BASE64URL.fullmatch(text) is None:
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def decode_key(text: str) -> bytes:
    """An unpadded base64url key of exactly 32 bytes; raises ValueError otherwise."""
    try:
        raw = _b64decode(text)
    except ValueError as exc:
        raise ValueError("key is not base64url") from exc
    if len(raw) != KEY_BYTES:
        raise ValueError(f"key must be {KEY_BYTES} bytes, got {len(raw)}")
    return raw


def encode_key(raw: bytes) -> str:
    """Unpadded base64url, the format `decode_key` reads."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _associated_data(conversation_id: str, entity_type: str, lookup_field: str) -> bytes:
    return f"{conversation_id}|{entity_type}|{lookup_field}".encode()


@dataclass(frozen=True)
class MappingCipher:
    """Two separate keys: one only tests "seen before?", one only reads values."""

    mapping_key: bytes
    lookup_key: bytes

    def lookup_field(self, key: str) -> str:
        """Hex HMAC-SHA256 of an entity key: comparable, but not reversible or guessable."""
        return hmac.new(self.lookup_key, key.encode(), hashlib.sha256).hexdigest()

    def encrypt(
        self, conversation_id: str, entity_type: str, original: str, lookup_field: str
    ) -> str:
        """base64url(nonce + ciphertext), bound to the conversation, type and lookup field.

        The lookup field ties a value to one entity, so two values of one type cannot be
        swapped in Redis without the store noticing (see `RedisMappingStore.originals`).
        """
        nonce = os.urandom(_NONCE_BYTES)
        sealed = AESGCM(self.mapping_key).encrypt(
            nonce,
            original.encode(),
            _associated_data(conversation_id, entity_type, lookup_field),
        )
        return encode_key(nonce + sealed)

    def decrypt(
        self, conversation_id: str, entity_type: str, stored: str, lookup_field: str
    ) -> str:
        """The original text; raises `MappingStoreUnavailable` when it does not decrypt here."""
        try:
            raw = _b64decode(stored)
            opened = AESGCM(self.mapping_key).decrypt(
                raw[:_NONCE_BYTES],
                raw[_NONCE_BYTES:],
                _associated_data(conversation_id, entity_type, lookup_field),
            )
            return opened.decode()
        except (InvalidTag, ValueError) as exc:  # UnicodeDecodeError is a ValueError
            raise MappingStoreUnavailable("a stored mapping value did not decrypt") from exc
