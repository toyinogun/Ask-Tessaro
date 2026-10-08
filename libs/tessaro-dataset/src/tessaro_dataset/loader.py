"""The file reading edge: YAML files, bundles and handbook Markdown into a `Dataset`."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from tessaro_dataset.assemble import RawPage, RawSources, build_dataset
from tessaro_dataset.dataset import Dataset
from tessaro_dataset.dates import DEFAULT_STAND_IN_DURATION, DateContext, default_anchor
from tessaro_dataset.errors import Problem

DATA_FILES = (
    "company.yaml",
    "employees.yaml",
    "standins.yaml",
    "leave.yaml",
    "claims.yaml",
    "tickets.yaml",
    "devices.yaml",
    "bookings.yaml",
    "channels.yaml",
)
_FRONT_MATTER = "---"


class _StrictLoader(yaml.SafeLoader):
    """A safe loader that refuses duplicate keys instead of keeping the last one."""


def _no_duplicates(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False) -> object:
    keys = [loader.construct_object(key, deep=deep) for key, _ in node.value]
    repeated = sorted({str(k) for k in keys if keys.count(k) > 1})
    if repeated:
        raise yaml.constructor.ConstructorError(
            None, None, f"duplicate keys {repeated}", node.start_mark
        )
    return loader.construct_mapping(node, deep=deep)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates)


@dataclass(frozen=True)
class DatasetPaths:
    """Where the dataset and the access bundles live."""

    dataset_dir: Path
    bundles_dir: Path

    @classmethod
    def default(cls) -> "DatasetPaths":
        """`dataset/` and `bundles/` under the current directory (the repo root)."""
        return cls.under(Path.cwd())

    @classmethod
    def under(cls, root: Path) -> "DatasetPaths":
        """`dataset/` and `bundles/` under `root`."""
        return cls(dataset_dir=root / "dataset", bundles_dir=root / "bundles")


def _parse_yaml(text: str, label: str) -> tuple[object, list[Problem]]:
    try:
        return yaml.load(text, Loader=_StrictLoader), []  # noqa: S506 (a SafeLoader subclass)
    except yaml.YAMLError as exc:
        return None, [Problem(label, "-", f"invalid YAML: {exc}")]


def _read_text(path: Path, label: str) -> tuple[str | None, list[Problem]]:
    try:
        return path.read_text(encoding="utf-8"), []
    except OSError as exc:
        return None, [Problem(label, "-", f"cannot read: {exc.strerror}")]


def _split_page(text: str) -> tuple[str, str] | None:
    if not text.startswith(_FRONT_MATTER + "\n"):
        return None
    end = text.find("\n" + _FRONT_MATTER + "\n", len(_FRONT_MATTER))
    if end == -1:
        return None
    return text[len(_FRONT_MATTER) + 1 : end], text[end + len(_FRONT_MATTER) + 2 :].strip()


def _read_pages(directory: Path) -> tuple[list[RawPage], list[Problem]]:
    pages: list[RawPage] = []
    problems: list[Problem] = []
    for path in sorted(directory.glob("*.md")):
        label = f"handbook/{path.name}"
        text, issues = _read_text(path, label)
        problems.extend(issues)
        parts = _split_page(text) if text is not None else None
        if text is not None and parts is None:
            problems.append(Problem(label, path.stem, "needs YAML front matter between --- lines"))
        if parts is not None:
            meta, meta_issues = _parse_yaml(parts[0], label)
            problems.extend(meta_issues)
            pages.append(RawPage(slug=path.stem, front_matter=meta, body=parts[1]))
    return pages, problems


def read_sources(paths: DatasetPaths) -> RawSources:
    """Read every source file; unreadable or malformed files become problems, not exceptions."""
    problems: list[Problem] = []
    files: dict[str, object] = {}
    for name in DATA_FILES:
        text, issues = _read_text(paths.dataset_dir / name, name)
        problems.extend(issues)
        if text is not None:
            files[name], parse_issues = _parse_yaml(text, name)
            problems.extend(parse_issues)
    bundles: dict[str, object] = {}
    for path in sorted(paths.bundles_dir.glob("*.yaml")):
        label = f"bundles/{path.name}"
        text, issues = _read_text(path, label)
        problems.extend(issues)
        if text is not None:
            bundles[path.name], parse_issues = _parse_yaml(text, label)
            problems.extend(parse_issues)
    pages, page_issues = _read_pages(paths.dataset_dir / "handbook")
    return RawSources(
        files=files, bundles=bundles, pages=tuple(pages), read_problems=(*problems, *page_issues)
    )


def load_dataset(
    paths: DatasetPaths | None = None,
    anchor: datetime | None = None,
    stand_in_duration: timedelta = DEFAULT_STAND_IN_DURATION,
) -> Dataset:
    """Load and validate the dataset at `anchor` (default: now in Amsterdam).

    Raises `DatasetError` listing every problem, or `ValueError` for a naive anchor or a
    stand in duration of 0 or less.
    """
    ctx = DateContext(anchor=anchor or default_anchor(), stand_in_duration=stand_in_duration)
    return build_dataset(read_sources(paths or DatasetPaths.default()), ctx)
