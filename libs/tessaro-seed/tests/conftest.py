"""Shared fixtures: the real dataset at a pinned anchor and the identity input built from it."""

from datetime import datetime
from pathlib import Path

import pytest

from tessaro_dataset import AMSTERDAM, Dataset, load_dataset
from tessaro_dataset.loader import DatasetPaths
from tessaro_seed.identity.command import identity_input
from tessaro_seed.identity.reconcile import IdentityInput

REPO_ROOT = Path(__file__).resolve().parents[3]
# The demo password the tests seed with (a stand in, not a secret).
DEMO = "demo-pass"
WEDNESDAY_10 = datetime(2026, 10, 7, 10, 0, tzinfo=AMSTERDAM)


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    """The real dataset with the anchor pinned to Wednesday 7 October 2026, 10:00."""
    return load_dataset(DatasetPaths.under(REPO_ROOT), anchor=WEDNESDAY_10)


@pytest.fixture(scope="session")
def data(dataset: Dataset) -> IdentityInput:
    """What the seed reconciles to, with a fixed demo password."""
    return identity_input(dataset, DEMO)
