"""Directory, patterns, overlap resolution and chunking (spec 0006 AC-3, AC-4, AC-15, AC-17)."""

import pytest

from tessaro_privacy_proxy.masking.chunks import chunk
from tessaro_privacy_proxy.masking.directory import Directory, DirectoryEntry
from tessaro_privacy_proxy.masking.entities import EntityType, Source, Span, normalize, text_span
from tessaro_privacy_proxy.masking.errors import DirectoryError
from tessaro_privacy_proxy.masking.patterns import find_patterns
from tessaro_privacy_proxy.masking.spans import resolve

from .conftest import DAAN


def _found(spans: list[Span], text: str) -> list[tuple[str, EntityType]]:
    return [(text[s.start : s.end], s.entity_type) for s in spans]


def _entry(eid: str, first: str, last: str) -> DirectoryEntry:
    email = f"{first.lower()}.{last.lower()}@tessaro.example"
    return DirectoryEntry(
        employee_id=eid,
        display_name=f"{first} {last}",
        email=email,
        forms=(first, last, f"{first} {last}", email, eid),
        phone=f"+31 6 1234 5{eid[-3:]}",
        iban=f"NL00XTSR0000000{eid[-3:]}",
        street="Teststraat 1",
        postcode="1000 AA",
    )


def test_every_form_of_the_dutch_name_trap_is_found(directory: Directory) -> None:
    """covers: AC-4 (the dutch_name trap, with no analyzer at all)"""
    text = (
        "Daan de Wit, DAAN, de Wit, Wit, daan.dewit@tessaro.example, TES-01005, "
        "@**Daan de Wit**, +31 6 1234 5006, Zonnewijzerkade 58, 1045 LM"
    )
    spans = directory.find(text)
    assert {s.original for s in spans if s.entity_type == EntityType.PERSON} == {"Daan de Wit"}
    types = [t for _, t in _found(spans, text)]
    assert types.count(EntityType.PERSON) == 5
    assert EntityType.EMAIL_ADDRESS in types
    assert EntityType.EMPLOYEE_ID in types
    assert EntityType.PHONE_NUMBER in types
    assert types.count(EntityType.HOME_ADDRESS) == 2
    assert all(s.key.startswith(f"{s.entity_type}|emp:{DAAN}") for s in spans)


def test_name_forms_share_one_person_key_and_other_values_their_own(directory: Directory) -> None:
    """covers: AC-5"""
    spans = directory.find("Daan de Wit and Daan, mail daan.dewit@tessaro.example")
    keys = [s.key for s in spans]
    assert keys[0] == keys[1] == f"PERSON|emp:{DAAN}"
    assert keys[2] == f"EMAIL_ADDRESS|emp:{DAAN}:email"


def test_matching_is_whole_word_on_the_original_text(directory: Directory) -> None:
    """covers: AC-4 (no match inside a longer word; offsets are into the raw text)"""
    text = "Witness the  DAAN de wit case"
    spans = directory.find(text)
    assert _found(spans, text) == [("DAAN de wit", EntityType.PERSON)]


def test_a_shared_first_name_is_masked_and_keyed_by_text() -> None:
    """covers: AC-4, AC-5 (ambiguous forms stay masked)"""
    directory = Directory.from_entries(
        [_entry("TES-00001", "Anna", "Bakker"), _entry("TES-00002", "Anna", "Smit")]
    )
    spans = directory.find("Anna met Anna Smit")
    assert [s.key for s in spans] == ["PERSON|text:anna", "PERSON|emp:TES-00002"]
    assert spans[0].original == "Anna"


def test_an_empty_directory_finds_nothing() -> None:
    assert Directory.from_entries([]).find("Daan de Wit") == []


def test_a_bad_directory_file_refuses_to_load() -> None:
    """covers: AC-4"""
    with pytest.raises(DirectoryError):
        Directory.from_json('{"entries": [{"employee_id": "x"}]}')
    with pytest.raises(DirectoryError):
        Directory.from_json('{"entries": []}')


def test_every_dataset_street_matches_the_address_pattern(directory: Directory) -> None:
    """covers: AC-3 (every street in dataset/ must match the street pattern)"""
    streets = {
        t.employee_id: form
        for form, targets in directory.targets.items()
        for t in targets
        if t.field == "street"
    }
    assert len(streets) >= 30
    for street in streets.values():
        text = f"I live at {street.title()} now"
        hits = [s for s in find_patterns(text) if s.entity_type == EntityType.HOME_ADDRESS]
        assert [text[s.start : s.end].casefold() for s in hits] == [street], street


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ask TES-01005 about it", ("TES-01005", EntityType.EMPLOYEE_ID)),
        ("send it to Prins Hendrikkade 12A please", ("Prins Hendrikkade 12A", "HOME")),
        ("at Van Baerlestraat 5-7 today", ("Van Baerlestraat 5-7", "HOME")),
        ("postcode 1045LM is", ("1045LM", "HOME")),
        ("call 06-12345678 now", ("06-12345678", EntityType.PHONE_NUMBER)),
        ("call +31 20 123 4567 now", ("+31 20 123 4567", EntityType.PHONE_NUMBER)),
        ("call 020 1234567 now", ("020 1234567", EntityType.PHONE_NUMBER)),
        ("pay NL91 XTSR 4170 0000 00 now", ("NL91 XTSR 4170 0000 00", EntityType.IBAN_CODE)),
        ("pay NL91XTSR4170000000 now", ("NL91XTSR4170000000", EntityType.IBAN_CODE)),
    ],
)
def test_patterns(text: str, expected: tuple[str, object]) -> None:
    """covers: AC-3"""
    value, kind = expected
    entity = EntityType.HOME_ADDRESS if kind == "HOME" else kind
    assert (value, entity) in _found(find_patterns(text), text)


def test_patterns_leave_dates_amounts_and_cities_alone() -> None:
    """covers: AC-3 (FR-P6)"""
    text = "Your Berlin claim of €120.50 from 3 March 2026 for 1200 EUR, ref 2026-10-07"
    assert find_patterns(text) == []


def test_phone_and_iban_keys_ignore_spacing() -> None:
    """covers: AC-5 (normalized text keys)"""
    assert normalize(EntityType.PHONE_NUMBER, "06-1234 5678") == "0612345678"
    assert normalize(EntityType.IBAN_CODE, "NL91 XTSR") == "nl91xtsr"
    assert normalize(EntityType.PERSON, "  Anna   Smit ") == "anna smit"


def _span(start: int, end: int, source: Source, text: str, kind: EntityType) -> Span:
    return text_span(start, end, kind, source, text)


def test_overlap_directory_wins_and_nothing_nests(directory: Directory) -> None:
    """covers: AC-15 (the email is masked once, as an email)"""
    text = "mail daan.dewit@tessaro.example now"
    analyzer_person = _span(5, 9, Source.ANALYZER, text, EntityType.PERSON)
    spans = resolve([*directory.find(text), analyzer_person], text)
    assert _found(spans, text) == [("daan.dewit@tessaro.example", EntityType.EMAIL_ADDRESS)]


def test_a_partial_overlap_merges_into_the_winner(directory: Directory) -> None:
    """covers: AC-15 (never half masked)"""
    text = "ask Daan de Wit and Co today"
    analyzer = _span(9, 26, Source.ANALYZER, text, EntityType.PERSON)  # "de Wit and Co tod"
    spans = resolve([*directory.find(text), analyzer], text)
    assert len(spans) == 1
    assert (spans[0].start, spans[0].end) == (4, 26)
    assert spans[0].key == f"PERSON|emp:{DAAN}"


def test_a_merged_text_span_is_keyed_by_its_wider_text() -> None:
    """covers: AC-15"""
    text = "Anna Maria Smit"
    first = _span(0, 10, Source.PATTERN, text, EntityType.PERSON)
    second = _span(5, 15, Source.ANALYZER, text, EntityType.PERSON)
    third = _span(11, 15, Source.ANALYZER, text, EntityType.PERSON)
    spans = resolve([second, first, third], text)
    assert [(s.start, s.end, s.key) for s in spans] == [(0, 15, "PERSON|text:anna maria smit")]


def test_a_span_bridging_two_winners_merges_all_three() -> None:
    """covers: AC-15"""
    text = "aaaa bbbb cccc dddd"
    spans = resolve(
        [
            _span(0, 4, Source.DIRECTORY, text, EntityType.PERSON),
            _span(10, 14, Source.DIRECTORY, text, EntityType.PERSON),
            _span(2, 12, Source.ANALYZER, text, EntityType.PERSON),
            _span(15, 19, Source.ANALYZER, text, EntityType.PERSON),
        ],
        text,
    )
    assert [(s.start, s.end) for s in spans] == [(0, 14), (15, 19)]


def test_short_text_is_one_chunk() -> None:
    """covers: AC-17"""
    assert chunk("hello") == [(0, "hello")]


def test_long_text_is_split_on_lines_with_true_offsets() -> None:
    """covers: AC-17"""
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(500))
    pieces = chunk(text, limit=1000)
    assert all(len(p) <= 1000 for _, p in pieces)
    assert "".join(p for _, p in pieces) == text
    assert all(text[o : o + len(p)] == p for o, p in pieces)
    assert all(p.endswith("\n") for _, p in pieces[:-1])


def test_a_long_line_splits_on_spaces_and_a_huge_word_is_cut() -> None:
    """covers: AC-17"""
    text = "word " * 300 + "y" * 2500
    pieces = chunk(text, limit=1000)
    assert all(len(p) <= 1000 for _, p in pieces)
    assert "".join(p for _, p in pieces) == text
    assert all(text[o : o + len(p)] == p for o, p in pieces)
