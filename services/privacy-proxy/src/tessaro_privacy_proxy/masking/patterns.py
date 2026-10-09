"""The proxy's own recognizers: values whose shape is known, so masking never rests on spaCy.

Spec 0006 AC-3: employee IDs, Dutch street addresses and postcodes, Dutch phone numbers
and Dutch IBANs.
"""

import re
from collections.abc import Sequence

from tessaro_privacy_proxy.masking.entities import EntityType, Source, Span, text_span

_STREET_SUFFIXES = (
    "straat|weg|laan|plein|gracht|kade|kreek|singel|dijk|pad|hof|steeg|park|plantsoen"
)
_PARTICLES = "van|de|der|den|het|ter|ten|op|aan|in"
_LETTERS = r"[a-zà-ÿ'\u2019]*"  # lowercase letters and both apostrophes
_CAPITALIZED = rf"[A-Z]{_LETTERS}"
# IDs, phones and IBANs: `_` and a following letter separate them too (`employee_TES-00012`).
_NOT_AFTER_ALNUM = r"(?<![A-Za-z0-9])"

PATTERNS: Sequence[tuple[EntityType, re.Pattern[str]]] = (
    (EntityType.EMPLOYEE_ID, re.compile(rf"{_NOT_AFTER_ALNUM}TES-\d{{5}}(?!\d)")),
    (
        EntityType.HOME_ADDRESS,
        re.compile(
            rf"(?<!\w)(?:(?:{_CAPITALIZED}|{_PARTICLES})\s+)*"
            rf"[A-Z]{_LETTERS}(?:{_STREET_SUFFIXES})\s+\d+[A-Za-z]?(?:-\d+)?(?!\w)"
        ),
    ),
    (EntityType.HOME_ADDRESS, re.compile(r"(?<!\w)[1-9]\d{3} ?[A-Z]{2}(?!\w)")),
    (
        # Mobile (06) and landline (two or three digit area code): nine digits after the prefix.
        EntityType.PHONE_NUMBER,
        re.compile(r"(?<![\d+])(?:\+31|0031|0)[\s-]?(?:\(0\)[\s-]?)?[1-9](?:[\s-]?\d){8}(?!\d)"),
    ),
    (
        EntityType.IBAN_CODE,
        re.compile(rf"{_NOT_AFTER_ALNUM}NL\d{{2}} ?[A-Z]{{4}} ?\d{{4}} ?\d{{4}} ?\d{{2}}(?!\d)"),
    ),
)


def find_patterns(text: str) -> list[Span]:
    """Every pattern hit in `text`, keyed by its normalized text."""
    return [
        text_span(match.start(), match.end(), entity_type, Source.PATTERN, text)
        for entity_type, pattern in PATTERNS
        for match in pattern.finditer(text)
    ]
