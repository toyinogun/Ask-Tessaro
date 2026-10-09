"""What the proxy masks: entity types, detected spans and the keys that identify an entity."""

import re
import unicodedata
from dataclasses import dataclass
from enum import IntEnum, StrEnum


class EntityType(StrEnum):
    """The placeholder types the model may see, as in `<PERSON_1>`."""

    PERSON = "PERSON"
    EMAIL_ADDRESS = "EMAIL_ADDRESS"
    PHONE_NUMBER = "PHONE_NUMBER"
    IBAN_CODE = "IBAN_CODE"
    HOME_ADDRESS = "HOME_ADDRESS"
    EMPLOYEE_ID = "EMPLOYEE_ID"


ANALYZER_TYPES = (
    EntityType.PERSON,
    EntityType.EMAIL_ADDRESS,
    EntityType.PHONE_NUMBER,
    EntityType.IBAN_CODE,
)
"""The only types the Presidio analyzer is asked for (spec 0006 AC-3)."""


class Source(IntEnum):
    """Who found a span. A lower value wins an overlap (spec 0006 AC-15)."""

    DIRECTORY = 0
    PATTERN = 1
    ANALYZER = 2


@dataclass(frozen=True)
class Span:
    """A detected value: `[start, end)` in the segment, its type, entity key and stored original.

    `key` identifies the entity within a conversation (it is HMACed before storage);
    `original` is what a placeholder restores to.
    """

    start: int
    end: int
    entity_type: EntityType
    source: Source
    key: str
    original: str

    @property
    def length(self) -> int:
        """Characters covered."""
        return self.end - self.start

    def overlaps(self, other: "Span") -> bool:
        """Whether the two spans share at least one character."""
        return self.start < other.end and other.start < self.end

    def contains(self, other: "Span") -> bool:
        """Whether `other` lies entirely inside this span."""
        return self.start <= other.start and other.end <= self.end


_COMPACT_TYPES = frozenset({EntityType.PHONE_NUMBER, EntityType.IBAN_CODE})
_WHITESPACE = re.compile(r"\s+")
_SEPARATORS = re.compile(r"[\s-]+")


def normalize(entity_type: EntityType, text: str) -> str:
    """NFKC, casefolded, whitespace collapsed; phones and IBANs also lose spaces and hyphens."""
    folded = unicodedata.normalize("NFKC", text).casefold().strip()
    if entity_type in _COMPACT_TYPES:
        return _SEPARATORS.sub("", folded)
    return _WHITESPACE.sub(" ", folded)


def text_span(start: int, end: int, entity_type: EntityType, source: Source, text: str) -> Span:
    """A span keyed by its own normalized text (anything not tied to a directory employee)."""
    original = text[start:end]
    return Span(
        start=start,
        end=end,
        entity_type=entity_type,
        source=source,
        key=f"{entity_type}|text:{normalize(entity_type, original)}",
        original=original,
    )
