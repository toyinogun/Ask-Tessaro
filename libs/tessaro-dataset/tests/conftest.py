"""Shared fixtures: the real dataset at a pinned anchor, and helpers to break a copy of it."""

import copy
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from tessaro_dataset import AMSTERDAM, Dataset, DatasetError, DateContext, load_dataset
from tessaro_dataset.assemble import RawSources, build_dataset
from tessaro_dataset.loader import DatasetPaths, read_sources

REPO_ROOT = Path(__file__).resolve().parents[3]
PATHS = DatasetPaths.under(REPO_ROOT)
WEDNESDAY_10 = datetime(2026, 10, 7, 10, 0, tzinfo=AMSTERDAM)

Mutator = Callable[[dict[str, Any]], None]


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    """The real dataset with the anchor pinned to Wednesday 7 October 2026, 10:00."""
    return load_dataset(PATHS, anchor=WEDNESDAY_10)


@pytest.fixture(scope="session")
def sources() -> RawSources:
    """The real sources as parsed YAML, read once."""
    return read_sources(PATHS)


def edited(sources: RawSources, file: str, mutate: Mutator) -> RawSources:
    """A deep copy of the sources with one file's document changed by `mutate`."""
    files = copy.deepcopy(dict(sources.files))
    document = files[file]
    assert isinstance(document, dict)
    mutate(document)
    return RawSources(files=files, bundles=sources.bundles, pages=sources.pages, read_problems=())


def find(document: dict[str, Any], key: str, record_id: str, id_key: str = "id") -> dict[str, Any]:
    """The raw record with this ID in one section of a document."""
    record: dict[str, Any] = next(r for r in document[key] if r[id_key] == record_id)
    return record


def problems_of(sources: RawSources, anchor: datetime = WEDNESDAY_10) -> list[str]:
    """Build the dataset and return every problem message, or [] when it is valid."""
    try:
        build_dataset(sources, DateContext(anchor=anchor))
    except DatasetError as exc:
        return [str(p) for p in exc.problems]
    return []
