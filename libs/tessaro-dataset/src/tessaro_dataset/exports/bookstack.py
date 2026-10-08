"""BookStack: one handbook book, its chapters and the 20 pages."""

import re

from tessaro_dataset.dataset import Dataset
from tessaro_dataset.exports.base import ExportRecord

BOOK_NAME = "Tessaro handbook"
BOOK_SLUG = "tessaro-handbook"


def chapter_slug(name: str) -> str:
    """A URL slug for a chapter name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class StackBook(ExportRecord):
    """The one handbook book."""

    slug: str
    name: str


class StackChapter(ExportRecord):
    """A chapter of the handbook."""

    slug: str
    name: str
    book_slug: str


class StackPage(ExportRecord):
    """A handbook page in Markdown."""

    slug: str
    name: str
    chapter_slug: str
    owner_team: str
    markdown: str


class BookStackExport(ExportRecord):
    """Everything the BookStack seed job writes."""

    books: tuple[StackBook, ...]
    chapters: tuple[StackChapter, ...]
    pages: tuple[StackPage, ...]


def export_bookstack(dataset: Dataset, include_demo_inputs: bool = False) -> BookStackExport:
    """The handbook as one book, chapters from page front matter, pages sorted by slug."""
    chapters = sorted({p.chapter for p in dataset.pages})
    return BookStackExport(
        books=(StackBook(slug=BOOK_SLUG, name=BOOK_NAME),),
        chapters=tuple(
            StackChapter(slug=chapter_slug(c), name=c, book_slug=BOOK_SLUG) for c in chapters
        ),
        pages=tuple(
            StackPage(
                slug=p.slug,
                name=p.title,
                chapter_slug=chapter_slug(p.chapter),
                owner_team=p.owner_team,
                markdown=p.body,
            )
            for p in sorted(dataset.pages, key=lambda p: p.slug)
        ),
    )
