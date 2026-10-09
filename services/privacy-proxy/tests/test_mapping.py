"""The encrypted Redis mapping (spec 0006 AC-5, AC-6, AC-14)."""

import asyncio
from collections.abc import Callable
from typing import cast

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fakeredis import FakeAsyncRedis
from redis.exceptions import ConnectionError as RedisConnectionError

from tessaro_privacy_proxy.mapping.cipher import KEY_BYTES, MappingCipher, decode_key, encode_key
from tessaro_privacy_proxy.mapping.redis_store import RedisMappingStore, conversation_keys
from tessaro_privacy_proxy.masking.entities import EntityType
from tessaro_privacy_proxy.masking.errors import MappingStoreUnavailable

from .conftest import make_store

PERSON = EntityType.PERSON


def test_keys_round_trip_and_bad_keys_are_refused() -> None:
    raw = bytes(range(KEY_BYTES))
    assert decode_key(encode_key(raw)) == raw
    with pytest.raises(ValueError, match="32 bytes"):
        decode_key(encode_key(b"short"))
    with pytest.raises(ValueError, match="base64url"):
        decode_key("not base64 !!")


@pytest.mark.parametrize(
    "damage",
    [lambda k: k[:10] + "!" + k[10:], lambda k: k + "=", lambda k: k.replace(k[5], "+", 1)],
)
def test_a_key_with_stray_characters_is_refused(damage: Callable[[str], str]) -> None:
    """A lenient decoder would drop the stray character and accept a damaged key."""
    key = encode_key(bytes(range(KEY_BYTES)))
    with pytest.raises(ValueError, match="base64url"):
        decode_key(damage(key))


def test_a_value_only_decrypts_in_its_own_conversation_and_type() -> None:
    """covers: AC-5, AC-6 (associated data binds conversation and type)"""
    cipher = MappingCipher(mapping_key=b"m" * KEY_BYTES, lookup_key=b"l" * KEY_BYTES)
    sealed = cipher.encrypt("c1", "PERSON", "Daan de Wit", "f")
    assert "Daan" not in sealed
    assert cipher.decrypt("c1", "PERSON", sealed, "f") == "Daan de Wit"
    with pytest.raises(MappingStoreUnavailable):
        cipher.decrypt("c2", "PERSON", sealed, "f")
    with pytest.raises(MappingStoreUnavailable):
        cipher.decrypt("c1", "EMAIL_ADDRESS", sealed, "f")
    with pytest.raises(MappingStoreUnavailable):
        cipher.decrypt("c1", "PERSON", "@@not-base64@@", "f")


def test_a_value_only_decrypts_for_its_own_lookup_field() -> None:
    """covers: AC-6 (two entries of one type cannot stand in for each other)"""
    cipher = MappingCipher(mapping_key=b"m" * KEY_BYTES, lookup_key=b"l" * KEY_BYTES)
    sealed = cipher.encrypt("c1", "PERSON", "Daan de Wit", "field-a")
    assert cipher.decrypt("c1", "PERSON", sealed, "field-a") == "Daan de Wit"
    with pytest.raises(MappingStoreUnavailable):
        cipher.decrypt("c1", "PERSON", sealed, "field-b")


def test_a_value_that_is_not_utf8_is_a_mapping_error() -> None:
    cipher = MappingCipher(mapping_key=b"m" * KEY_BYTES, lookup_key=b"l" * KEY_BYTES)
    nonce = b"n" * 12
    sealed = AESGCM(b"m" * KEY_BYTES).encrypt(nonce, b"\xff\xfe", b"c1|PERSON|f")
    with pytest.raises(MappingStoreUnavailable):
        cipher.decrypt("c1", "PERSON", encode_key(nonce + sealed), "f")


async def test_swapped_stored_values_never_restore_the_wrong_person(
    redis: FakeAsyncRedis, store: RedisMappingStore
) -> None:
    """covers: AC-6 (someone with Redis write access swaps two entries of one type)"""
    await store.placeholder_for("c1", PERSON, "PERSON|text:anna", "Anna")
    await store.placeholder_for("c1", PERSON, "PERSON|text:bram", "Bram")
    _, rev, _ = conversation_keys("c1")
    one, two = await redis.hmget(rev, ["<PERSON_1>", "<PERSON_2>"])
    assert one is not None
    assert two is not None
    await redis.hset(rev, mapping={"<PERSON_1>": two, "<PERSON_2>": one})
    with pytest.raises(MappingStoreUnavailable):
        await store.originals("c1", ["<PERSON_1>"])


def test_lookup_fields_depend_on_the_lookup_key() -> None:
    """covers: AC-6 (a plain hash of a name would be guessable; an HMAC is not)"""
    one = MappingCipher(mapping_key=b"m" * KEY_BYTES, lookup_key=b"a" * KEY_BYTES)
    two = MappingCipher(mapping_key=b"m" * KEY_BYTES, lookup_key=b"b" * KEY_BYTES)
    assert one.lookup_field("PERSON|text:anna") != two.lookup_field("PERSON|text:anna")


async def test_same_key_same_placeholder_numbered_per_type(store: RedisMappingStore) -> None:
    """covers: AC-5"""
    first = await store.placeholder_for("c1", PERSON, "PERSON|emp:TES-01005", "Daan de Wit")
    again = await store.placeholder_for("c1", PERSON, "PERSON|emp:TES-01005", "Daan de Wit")
    other = await store.placeholder_for("c1", PERSON, "PERSON|text:anna", "Anna")
    mail = await store.placeholder_for("c1", EntityType.EMAIL_ADDRESS, "E|x", "a@b.example")
    assert (first, again, other, mail) == (
        "<PERSON_1>",
        "<PERSON_1>",
        "<PERSON_2>",
        "<EMAIL_ADDRESS_1>",
    )
    assert await store.originals("c1", ["<PERSON_1>", "<PERSON_2>", "<PERSON_7>", "junk"]) == {
        "<PERSON_1>": "Daan de Wit",
        "<PERSON_2>": "Anna",
    }
    assert await store.originals("c1", []) == {}


async def test_a_placeholder_never_restores_in_another_conversation(
    store: RedisMappingStore,
) -> None:
    """covers: AC-5"""
    await store.placeholder_for("c1", PERSON, "PERSON|text:anna", "Anna")
    assert await store.originals("c2", ["<PERSON_1>"]) == {}


async def test_redis_holds_no_plain_text(redis: FakeAsyncRedis, store: RedisMappingStore) -> None:
    """covers: AC-6"""
    await store.placeholder_for("c1", PERSON, "PERSON|emp:TES-01005", "Daan de Wit")
    keys = await redis.keys("*")
    stored = [await redis.hgetall(key) for key in keys]
    dump = repr(keys) + repr(stored)
    assert "Daan" not in dump
    assert "TES-01005" not in dump
    assert set(await redis.keys("*")) == {k.encode() for k in conversation_keys("c1")}


async def test_expiry_slides_on_every_call(redis: FakeAsyncRedis) -> None:
    """covers: AC-6 (touch refreshes all three keys)"""
    store = make_store(redis, ttl_seconds=100)
    await store.touch("c1")  # a new conversation: nothing to refresh, no error
    assert await redis.keys("*") == []
    await store.placeholder_for("c1", PERSON, "k", "v")
    for key in conversation_keys("c1"):
        await redis.expire(key, 5)
    await store.touch("c1")
    assert [await redis.ttl(k) for k in conversation_keys("c1")] == [100, 100, 100]


async def test_partly_present_keys_fail_closed(
    redis: FakeAsyncRedis, store: RedisMappingStore
) -> None:
    """covers: AC-6 (a drifted conversation must not renumber)"""
    await store.placeholder_for("c1", PERSON, "k", "v")
    await redis.delete(conversation_keys("c1")[2])
    with pytest.raises(MappingStoreUnavailable):
        await store.touch("c1")


async def test_concurrent_allocations_agree(store: RedisMappingStore) -> None:
    """covers: AC-14"""
    same = await asyncio.gather(
        *(store.placeholder_for("c1", PERSON, "PERSON|text:anna", "Anna") for _ in range(20))
    )
    assert set(same) == {"<PERSON_1>"}
    distinct = await asyncio.gather(
        *(store.placeholder_for("c1", PERSON, f"PERSON|text:p{i}", f"P{i}") for i in range(20))
    )
    assert len(set(distinct)) == 20
    assert "<PERSON_1>" not in distinct


class _DeadRedis:
    async def eval(self, *_args: object) -> object:
        raise RedisConnectionError("down")

    async def hmget(self, *_args: object) -> object:
        raise RedisConnectionError("down")


async def test_every_redis_failure_is_mapping_store_unavailable() -> None:
    """covers: AC-8"""
    store = make_store(cast(FakeAsyncRedis, _DeadRedis()))
    with pytest.raises(MappingStoreUnavailable):
        await store.touch("c1")
    with pytest.raises(MappingStoreUnavailable):
        await store.placeholder_for("c1", PERSON, "k", "v")
    with pytest.raises(MappingStoreUnavailable):
        await store.originals("c1", ["<PERSON_1>"])


async def test_a_stored_value_without_its_lookup_field_fails_closed(
    redis: FakeAsyncRedis, store: RedisMappingStore
) -> None:
    """covers: AC-6"""
    await store.placeholder_for("c1", PERSON, "PERSON|text:anna", "Anna")
    _, rev, _ = conversation_keys("c1")
    await redis.hset(rev, "<PERSON_1>", "no-separator")
    with pytest.raises(MappingStoreUnavailable):
        await store.originals("c1", ["<PERSON_1>"])


class _FwdReadFails(FakeAsyncRedis):
    async def hmget(self, name: str, keys: list[str]) -> object:  # type: ignore[override]
        if name.endswith(":fwd"):
            raise RedisConnectionError("down")
        return await super().hmget(name, keys)


async def test_a_failed_ownership_read_is_mapping_store_unavailable() -> None:
    """covers: AC-8 (the second read during restore fails closed too)"""
    redis = _FwdReadFails()
    store = make_store(redis)
    await store.placeholder_for("c1", PERSON, "PERSON|text:anna", "Anna")
    with pytest.raises(MappingStoreUnavailable):
        await store.originals("c1", ["<PERSON_1>"])
    await redis.aclose()
