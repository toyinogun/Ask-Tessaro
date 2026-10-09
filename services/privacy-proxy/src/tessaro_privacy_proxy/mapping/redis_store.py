"""The conversation mapping in Redis: three hashes per conversation, two Lua scripts.

Keys (the braces are a literal Redis hash tag, so all three share one slot):
`proxy:conv:{<cid>}:fwd` lookup field to placeholder, `:rev` placeholder to
`<lookup field>:<ciphertext>`, `:seq` entity type to the last number issued.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from tessaro_privacy_proxy.mapping.cipher import MappingCipher
from tessaro_privacy_proxy.masking.entities import EntityType
from tessaro_privacy_proxy.masking.errors import MappingStoreUnavailable

# KEYS: fwd rev seq. ARGV: ttl seconds. 0 = new conversation, 1 = refreshed, error = drifted.
TOUCH = """
local present = redis.call('EXISTS', KEYS[1], KEYS[2], KEYS[3])
if present == 0 then return 0 end
if present < 3 then return redis.error_reply('PARTIAL conversation keys') end
for i = 1, 3 do redis.call('EXPIRE', KEYS[i], ARGV[1]) end
return 1
"""

# KEYS: fwd rev seq. ARGV: lookup field, entity type, stored value, ttl seconds.
ALLOCATE = """
local placeholder = redis.call('HGET', KEYS[1], ARGV[1])
if not placeholder then
  local n = redis.call('HINCRBY', KEYS[3], ARGV[2], 1)
  placeholder = '<' .. ARGV[2] .. '_' .. n .. '>'
  redis.call('HSET', KEYS[1], ARGV[1], placeholder)
  redis.call('HSET', KEYS[2], placeholder, ARGV[3])
end
for i = 1, 3 do redis.call('EXPIRE', KEYS[i], ARGV[4]) end
return placeholder
"""

_PLACEHOLDER = re.compile(r"<([A-Z_]+)_\d+>")
_SEPARATOR = ":"  # never in a hex lookup field or a base64url ciphertext


def conversation_keys(conversation_id: str) -> tuple[str, str, str]:
    """The fwd, rev and seq keys of one conversation."""
    base = f"proxy:conv:{{{conversation_id}}}"
    return f"{base}:fwd", f"{base}:rev", f"{base}:seq"


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


@dataclass(frozen=True)
class RedisMappingStore:
    """`MappingStore` on Redis. Every Redis failure becomes `MappingStoreUnavailable`."""

    redis: Redis
    cipher: MappingCipher
    ttl_seconds: int

    async def touch(self, conversation_id: str) -> None:
        """Refresh all three keys' expiry; fail closed when only some of them exist (AC-6)."""
        try:
            await self.redis.eval(TOUCH, 3, *conversation_keys(conversation_id), self.ttl_seconds)
        except RedisError as exc:
            raise MappingStoreUnavailable("mapping store refused touch") from exc

    async def placeholder_for(
        self, conversation_id: str, entity_type: EntityType, key: str, original: str
    ) -> str:
        """The placeholder for `key`, allocated atomically (AC-5, AC-14)."""
        field = self.cipher.lookup_field(key)
        sealed = self.cipher.encrypt(conversation_id, entity_type, original, field)
        try:
            result = await self.redis.eval(
                ALLOCATE,
                3,
                *conversation_keys(conversation_id),
                field,
                str(entity_type),
                f"{field}{_SEPARATOR}{sealed}",
                self.ttl_seconds,
            )
        except RedisError as exc:
            raise MappingStoreUnavailable("mapping store refused allocate") from exc
        return _text(result)

    async def originals(
        self, conversation_id: str, placeholders: Sequence[str]
    ) -> Mapping[str, str]:
        """Decrypted originals of the placeholders this conversation issued.

        Each value must decrypt for its lookup field, and that field must still map to the
        same placeholder; anything else means the stored data was altered: fail closed.
        """
        if not placeholders:
            return {}
        fwd, rev, _ = conversation_keys(conversation_id)
        try:
            stored = await self.redis.hmget(rev, list(placeholders))
        except RedisError as exc:
            raise MappingStoreUnavailable("mapping store refused read") from exc
        found = [
            _Stored(match[0], match[1], *_split(_text(value)))
            for match, value in zip(map(_PLACEHOLDER.fullmatch, placeholders), stored, strict=True)
            if match is not None and value is not None
        ]
        if not found:
            return {}
        try:
            owners = await self.redis.hmget(fwd, [item.field for item in found])
        except RedisError as exc:
            raise MappingStoreUnavailable("mapping store refused read") from exc
        if any(
            owner is None or _text(owner) != i.placeholder
            for i, owner in zip(found, owners, strict=True)
        ):
            raise MappingStoreUnavailable("a stored mapping value is not its placeholder's")
        return {
            i.placeholder: self.cipher.decrypt(conversation_id, i.entity_type, i.sealed, i.field)
            for i in found
        }


@dataclass(frozen=True)
class _Stored:
    """One `rev` entry, split into its parts."""

    placeholder: str
    entity_type: str
    field: str
    sealed: str


def _split(value: str) -> tuple[str, str]:
    field, separator, sealed = value.partition(_SEPARATOR)
    if not separator:
        raise MappingStoreUnavailable("a stored mapping value has no lookup field")
    return field, sealed
