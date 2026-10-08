"""Turn already parsed YAML into a validated `Dataset`, collecting every problem.

Pure domain code: the loader reads the files and hands the parsed objects here.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from tessaro_dataset.dataset import Dataset
from tessaro_dataset.dates import DateContext, anchor_warnings
from tessaro_dataset.errors import DatasetError, Problem
from tessaro_dataset.models import (
    AccessBundle,
    Booking,
    Channel,
    Device,
    Employee,
    ExpenseClaim,
    HandbookPage,
    LeaveAllocation,
    LeaveApplication,
    Office,
    Space,
    StandIn,
    Team,
    Ticket,
)
from tessaro_dataset.validate import check

_ID_KEYS = ("id", "asset_tag", "name", "slug", "team")


@dataclass(frozen=True)
class RawPage:
    """A handbook page as read from disk: slug, parsed front matter and Markdown body."""

    slug: str
    front_matter: object
    body: str


@dataclass(frozen=True)
class RawSources:
    """Parsed YAML documents by file name, plus bundles and handbook pages."""

    files: Mapping[str, object] = field(default_factory=dict)
    bundles: Mapping[str, object] = field(default_factory=dict)
    pages: Sequence[RawPage] = ()
    read_problems: Sequence[Problem] = ()


@dataclass(frozen=True)
class _Section:
    file: str
    key: str
    model: type[BaseModel]


_SECTIONS = (
    _Section("company.yaml", "offices", Office),
    _Section("company.yaml", "spaces", Space),
    _Section("company.yaml", "teams", Team),
    _Section("employees.yaml", "employees", Employee),
    _Section("standins.yaml", "standins", StandIn),
    _Section("leave.yaml", "allocations", LeaveAllocation),
    _Section("leave.yaml", "applications", LeaveApplication),
    _Section("claims.yaml", "claims", ExpenseClaim),
    _Section("devices.yaml", "devices", Device),
    _Section("tickets.yaml", "tickets", Ticket),
    _Section("bookings.yaml", "bookings", Booking),
    _Section("channels.yaml", "channels", Channel),
)


def record_label(item: object) -> str:
    """The best identifier for a raw record, for problem messages."""
    if isinstance(item, Mapping):
        for key in _ID_KEYS:
            if key in item:
                return str(item[key])
        if "employee_id" in item:
            return f"{item['employee_id']}/{item.get('year', '?')}"
    return "?"


def _format(error: ValidationError) -> str:
    parts = []
    for detail in error.errors(include_url=False):
        where = ".".join(str(p) for p in detail["loc"]) or "record"
        parts.append(f"{where}: {detail['msg']}")
    return "; ".join(parts)


def _prepare(section: _Section, item: object) -> object:
    """Number ticket articles from their list order before validation."""
    if section.model is Ticket and isinstance(item, Mapping):
        articles = item.get("articles")
        if isinstance(articles, list):
            numbered = [
                {**a, "seq": i} if isinstance(a, Mapping) else a
                for i, a in enumerate(articles, start=1)
            ]
            return {**item, "articles": numbered}
    return item


def _validate_items(
    file: str, items: object, model: type[BaseModel], ctx: DateContext
) -> tuple[list[Any], list[Problem]]:
    if not isinstance(items, list):
        return [], [Problem(file, "-", f"expected a list, got {type(items).__name__}")]
    records: list[Any] = []
    problems: list[Problem] = []
    for item in items:
        try:
            records.append(model.model_validate(item, context=ctx))
        except ValidationError as exc:
            problems.append(Problem(file, record_label(item), _format(exc)))
    return records, problems


def _section(
    sources: RawSources, section: _Section, ctx: DateContext
) -> tuple[list[Any], list[Problem]]:
    document = sources.files.get(section.file)
    if document is None:
        return [], [Problem(section.file, "-", "file is missing or empty")]
    if not isinstance(document, Mapping) or section.key not in document:
        return [], [Problem(section.file, "-", f"expected a top level '{section.key}' list")]
    items = document[section.key]
    prepared = [_prepare(section, i) for i in items] if isinstance(items, list) else items
    return _validate_items(section.file, prepared, section.model, ctx)


def _bundles(sources: RawSources, ctx: DateContext) -> tuple[list[Any], list[Problem]]:
    records: list[Any] = []
    problems: list[Problem] = []
    for name, document in sorted(sources.bundles.items()):
        found, issues = _validate_items(f"bundles/{name}", [document], AccessBundle, ctx)
        records.extend(found)
        problems.extend(issues)
    return records, problems


def _pages(sources: RawSources, ctx: DateContext) -> tuple[list[Any], list[Problem]]:
    records: list[Any] = []
    problems: list[Problem] = []
    for page in sorted(sources.pages, key=lambda p: p.slug):
        meta = page.front_matter if isinstance(page.front_matter, Mapping) else {}
        raw = {**meta, "slug": page.slug, "body": page.body}
        found, issues = _validate_items(f"handbook/{page.slug}.md", [raw], HandbookPage, ctx)
        records.extend(found)
        problems.extend(issues)
    return records, problems


def build_dataset(sources: RawSources, ctx: DateContext) -> Dataset:
    """Validate every record and every cross record rule; raise one `DatasetError` if any fail."""
    problems = list(sources.read_problems)
    parsed: dict[str, list[Any]] = {}
    for section in _SECTIONS:
        records, issues = _section(sources, section, ctx)
        parsed[section.key] = records
        problems.extend(issues)
    parsed["bundles"], bundle_issues = _bundles(sources, ctx)
    parsed["pages"], page_issues = _pages(sources, ctx)
    problems.extend(bundle_issues + page_issues)
    dataset = Dataset(
        anchor=ctx.anchor,
        stand_in_duration=ctx.stand_in_duration,
        warnings=anchor_warnings(ctx.anchor),
        **{key: tuple(records) for key, records in parsed.items()},
    )
    problems.extend(check(dataset))
    if problems:
        raise DatasetError(problems)
    return dataset
