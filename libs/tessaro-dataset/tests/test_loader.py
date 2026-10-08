"""The file reading edge: bad YAML, duplicate keys, front matter and missing files."""

import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tessaro_dataset import DatasetError, DatasetPaths, load_dataset
from tessaro_dataset.loader import read_sources

from .conftest import PATHS, REPO_ROOT, WEDNESDAY_10


@pytest.fixture
def copy_root(tmp_path: Path) -> Path:
    shutil.copytree(
        REPO_ROOT / "dataset", tmp_path / "dataset", ignore=shutil.ignore_patterns("build")
    )
    shutil.copytree(REPO_ROOT / "bundles", tmp_path / "bundles")
    return tmp_path


def _problems(root: Path) -> list[str]:
    with pytest.raises(DatasetError) as caught:
        load_dataset(DatasetPaths.under(root), anchor=WEDNESDAY_10)
    return [str(p) for p in caught.value.problems]


def test_duplicate_keys_and_bad_yaml(copy_root: Path) -> None:
    (copy_root / "dataset" / "channels.yaml").write_text("channels:\n- name: a\n  name: b\n")
    (copy_root / "dataset" / "claims.yaml").write_text("claims: [unclosed\n")
    problems = _problems(copy_root)
    assert any("channels.yaml" in p and "duplicate keys" in p for p in problems)
    assert any("claims.yaml" in p and "invalid YAML" in p for p in problems)


def test_missing_file_and_front_matter(copy_root: Path) -> None:
    (copy_root / "dataset" / "standins.yaml").unlink()
    (copy_root / "dataset" / "handbook" / "public-holidays.md").write_text("# no front matter\n")
    (copy_root / "dataset" / "handbook" / "parental-leave.md").write_text("---\ntitle: x\n")
    problems = _problems(copy_root)
    assert any("standins.yaml" in p and "cannot read" in p for p in problems)
    assert any("public-holidays" in p and "front matter" in p for p in problems)
    assert any("parental-leave" in p and "front matter" in p for p in problems)


def test_default_paths_and_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)
    assert DatasetPaths.default() == PATHS
    assert len(read_sources(PATHS).pages) == 20
    assert load_dataset(anchor=WEDNESDAY_10).anchor == WEDNESDAY_10
    with pytest.raises(ValueError, match="time zone"):
        load_dataset(PATHS, anchor=datetime(2026, 10, 7, 10, 0))
    with pytest.raises(ValueError, match="above 0"):
        load_dataset(PATHS, anchor=WEDNESDAY_10, stand_in_duration=timedelta(0))
