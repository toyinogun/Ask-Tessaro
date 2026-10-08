"""Shared fixtures: one fresh key pair per issuer and the matching key set."""

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tessaro_auth.issue import DirectoryIdentity
from tessaro_auth.keys import KeyEntry, KeySet, Signer


@pytest.fixture(scope="session")
def adapter_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture(scope="session")
def worker_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture
def adapter_signer(adapter_key: Ed25519PrivateKey) -> Signer:
    return Signer.create("adapter-1", adapter_key)


@pytest.fixture
def worker_signer(worker_key: Ed25519PrivateKey) -> Signer:
    return Signer.create("worker-1", worker_key)


@pytest.fixture
def keyset(adapter_key: Ed25519PrivateKey, worker_key: Ed25519PrivateKey) -> KeySet:
    return KeySet.of(
        KeyEntry.create("adapter-1", adapter_key.public_key()),
        KeyEntry.create("worker-1", worker_key.public_key()),
    )


@pytest.fixture
def persona() -> DirectoryIdentity:
    """The demo persona as the adapter would read it from Authentik."""
    return DirectoryIdentity(
        employee_id="TES-01007",
        email="noor.dekker@tessaro.example",
        groups=("staff", "team-payments", "managers", "staff"),
        is_active=True,
    )
