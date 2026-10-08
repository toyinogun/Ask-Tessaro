"""Handbook facts that eval questions rely on, checked against both the data and the pages."""

from collections.abc import Iterator
from types import MappingProxyType
from typing import Final

from tessaro_dataset.dataset import Dataset
from tessaro_dataset.errors import Problem

VACATION_DAYS_PER_YEAR: Final = 25
CLAIM_PAYMENT_MIN_WORKING_DAYS: Final = 5
TICKET_QUEUES: Final = frozenset({"it", "people", "finance", "workplace"})
HANDBOOK_PAGE_COUNT: Final = 20

PAGE_FACTS: Final = MappingProxyType(
    {
        "reporting-sick": (
            "before 09:30",
            "you never need to say why",
            "no doctor's note for the first 7 days",
        ),
        "vacation-and-leave-types": (
            f"{VACATION_DAYS_PER_YEAR} vacation days a year",
            "allocated on 1 January",
            "Frappe HR",
        ),
        "working-abroad": (
            "up to 20 working days a year",
            "from an EU country",
            "People approval in advance",
            "case by case review by People",
        ),
        "expense-claims": (
            "within 30 days",
            "receipts",
            f"at least {CLAIM_PAYMENT_MIN_WORKING_DAYS} working days after approval",
        ),
        "laptop-repair-and-replacement": (
            "raise an IT ticket",
            "a loan laptop within 1 working day",
        ),
        "requesting-access": (
            "the IT queue",
            "elevated access needs IT approval",
        ),
        "accounts-and-passwords": (
            "Authentik",
            "the assistant cannot reset",
        ),
    }
)
"""Exact phrases each page must contain, keyed by page slug."""


def _page_phrases(dataset: Dataset) -> dict[str, tuple[str, ...]]:
    phrases = dict(PAGE_FACTS)
    for office in dataset.offices:
        phrases[f"{office.id}-office"] = (office.street, office.postcode, office.city)
    phrases["who-to-contact"] = tuple(
        f"{team.name} queue" for team in dataset.teams if team.ticket_queue
    )
    return phrases


def check_facts(dataset: Dataset) -> Iterator[Problem]:
    """The facts hold in the data and appear word for word (ignoring case) on their pages."""
    for alloc in dataset.allocations:
        if alloc.days != VACATION_DAYS_PER_YEAR:
            yield Problem(
                "leave.yaml",
                f"{alloc.employee_id}/{alloc.year}",
                f"allocation must be {VACATION_DAYS_PER_YEAR} days (handbook fact)",
            )
    queues = {t.ticket_queue for t in dataset.teams if t.ticket_queue}
    if queues != TICKET_QUEUES:
        yield Problem("company.yaml", "-", f"team queues must be {sorted(TICKET_QUEUES)}")
    pages = {p.slug: p for p in dataset.pages}
    if len(pages) != HANDBOOK_PAGE_COUNT:
        yield Problem("handbook", "-", f"expected {HANDBOOK_PAGE_COUNT} pages, found {len(pages)}")
    for slug, phrases in sorted(_page_phrases(dataset).items()):
        page = pages.get(slug)
        if page is None:
            yield Problem(f"handbook/{slug}.md", slug, "page is missing")
            continue
        for phrase in phrases:
            if phrase.casefold() not in page.body.casefold():
                yield Problem(f"handbook/{slug}.md", slug, f"must state {phrase!r}")
