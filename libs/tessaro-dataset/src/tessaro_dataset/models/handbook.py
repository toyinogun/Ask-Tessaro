"""Handbook pages (Markdown with YAML front matter)."""

from tessaro_dataset.models.common import Record, Slug, Text


class HandbookPage(Record):
    """One handbook page; the slug is its file name."""

    slug: Slug
    title: Text
    chapter: Text
    owner_team: Slug
    body: Text
