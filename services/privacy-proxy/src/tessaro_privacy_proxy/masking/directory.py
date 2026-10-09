"""The directory recognizer: every known way to write each employee, matched exactly (FR-P3).

Reads the shape of the dataset's `directory.json` export (spec 0002, extended by spec 0006).
"""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Self

from pydantic import BaseModel, ConfigDict, ValidationError

from tessaro_privacy_proxy.masking.entities import EntityType, Source, Span, text_span
from tessaro_privacy_proxy.masking.errors import DirectoryError

# A letter or digit, but not `_`: snake case keys and file names still separate words.
_BEFORE = r"(?<![^\W_])"
_AFTER = r"(?![^\W_])"


class DirectoryEntry(BaseModel):
    """One person as exported; extra export fields are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    employee_id: str
    display_name: str
    email: str
    forms: tuple[str, ...]
    phone: str
    iban: str
    street: str
    postcode: str


class DirectoryFile(BaseModel):
    """The whole export: `{"entries": [...]}`."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    entries: tuple[DirectoryEntry, ...]


@dataclass(frozen=True)
class _Target:
    """What a matched form means: an employee and which of their values it is."""

    employee_id: str
    entity_type: EntityType
    field: str | None  # None for a name form: every name form shares one PERSON entity


def _form_key(form: str) -> str:
    """How a form is stored and looked up: NFC (the request text is NFC too), then casefolded."""
    return unicodedata.normalize("NFC", form).casefold()


def _targets(entry: DirectoryEntry) -> Iterable[tuple[str, _Target]]:
    eid = entry.employee_id
    for form in entry.forms:
        if form.casefold() == entry.email.casefold():
            yield form, _Target(eid, EntityType.EMAIL_ADDRESS, "email")
        elif form == eid:
            yield form, _Target(eid, EntityType.EMPLOYEE_ID, "employee_id")
        else:
            yield form, _Target(eid, EntityType.PERSON, None)
    yield entry.phone, _Target(eid, EntityType.PHONE_NUMBER, "phone")
    yield entry.iban, _Target(eid, EntityType.IBAN_CODE, "iban")
    yield entry.street, _Target(eid, EntityType.HOME_ADDRESS, "street")
    yield entry.postcode, _Target(eid, EntityType.HOME_ADDRESS, "postcode")


@dataclass(frozen=True)
class Directory:
    """Exact matcher over every directory form, longest form first, whole words only."""

    pattern: re.Pattern[str] | None
    forms: tuple[str, ...]  # the keys of `targets`, in the order the pattern tries them
    targets: Mapping[str, tuple[_Target, ...]]
    display_names: Mapping[str, str]

    @classmethod
    def from_entries(cls, entries: Iterable[DirectoryEntry]) -> Self:
        """Build the matcher. A form shared by several employees keeps every target."""
        by_form: defaultdict[str, set[_Target]] = defaultdict(set)
        display_names: dict[str, str] = {}
        for entry in entries:
            display_names[entry.employee_id] = entry.display_name
            for form, target in _targets(entry):
                if form.strip():
                    by_form[_form_key(form)].add(target)
        targets = {
            form: tuple(sorted(found, key=lambda t: (t.employee_id, t.entity_type, t.field or "")))
            for form, found in by_form.items()
        }
        forms = tuple(sorted(targets, key=lambda f: (-len(f), f)))
        alternation = "|".join(re.escape(f) for f in forms)
        pattern = (
            re.compile(rf"{_BEFORE}(?:{alternation}){_AFTER}", re.IGNORECASE) if forms else None
        )
        return cls(pattern=pattern, forms=forms, targets=targets, display_names=display_names)

    @classmethod
    def from_json(cls, text: str) -> Self:
        """Parse a `directory.json` export; raises `DirectoryError` when it does not fit."""
        try:
            parsed = DirectoryFile.model_validate_json(text)
        except ValidationError as exc:
            raise DirectoryError(
                f"directory file is invalid: {exc.error_count()} problems"
            ) from exc
        if not parsed.entries:
            raise DirectoryError("directory file has no entries")
        return cls.from_entries(parsed.entries)

    def find(self, text: str) -> list[Span]:
        """Every directory form in `text`, offsets into `text` itself (spec 0006 AC-4).

        The masker passes NFC text, so a decomposed name still meets its NFC form.
        """
        if self.pattern is None:
            return []
        return [self._span(m.start(), m.end(), text) for m in self.pattern.finditer(text)]

    def _lookup(self, matched: str) -> tuple[_Target, ...]:
        """The targets of the form the pattern matched.

        `re.IGNORECASE` also equates letters `casefold()` keeps apart (`i`, the dotless i
        U+0131 and the dotted capital I U+0130), so a miss on the folded key falls back to
        the first form, in pattern order, that matches.
        """
        found = self.targets.get(matched.casefold())
        if found is not None:
            return found
        form = next(
            f
            for f in self.forms
            if len(f) == len(matched) and re.fullmatch(re.escape(f), matched, re.IGNORECASE)
        )
        return self.targets[form]

    def _span(self, start: int, end: int, text: str) -> Span:
        found = self._lookup(text[start:end])
        first = found[0]
        same_entity = all(
            (t.employee_id, t.entity_type, t.field)
            == (first.employee_id, first.entity_type, first.field)
            for t in found
        )
        if not same_entity:
            # A form several employees share (a common first name): keyed by its text (AC-5).
            return text_span(start, end, first.entity_type, Source.DIRECTORY, text)
        if first.field is None:
            return Span(
                start=start,
                end=end,
                entity_type=EntityType.PERSON,
                source=Source.DIRECTORY,
                key=f"{EntityType.PERSON}|emp:{first.employee_id}",
                original=self.display_names[first.employee_id],
            )
        original = text[start:end]
        return Span(
            start=start,
            end=end,
            entity_type=first.entity_type,
            source=Source.DIRECTORY,
            key=f"{first.entity_type}|emp:{first.employee_id}:{first.field}",
            original=original,
        )
