"""Directory, patterns, overlap resolution and chunking (spec 0006 AC-3, AC-4, AC-15, AC-17)."""

from itertools import pairwise

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
    assert spans[0].key == "PERSON|text:daan de wit and co tod"
    assert spans[0].original == "Daan de Wit and Co tod"


def test_a_name_outside_the_directory_never_takes_an_employee_key(
    directory: Directory,
) -> None:
    """covers: AC-5, AC-15 (Jan Bakker is not the employee whose surname is Bakker)"""
    text = "I spoke with Jan Bakker yesterday"
    analyzer = _span(13, 23, Source.ANALYZER, text, EntityType.PERSON)
    spans = resolve([*directory.find(text), analyzer], text)
    assert [(s.start, s.end, s.key, s.original) for s in spans] == [
        (13, 23, "PERSON|text:jan bakker", "Jan Bakker")
    ]


def test_a_span_bridging_two_employees_is_keyed_by_its_text() -> None:
    """covers: AC-15"""
    found = Directory.from_entries(
        [_entry("TES-00001", "Jan", "Smit"), _entry("TES-00002", "Pieter", "Bakker")]
    )
    text = "Jan Bakker"
    analyzer = _span(0, 10, Source.ANALYZER, text, EntityType.PERSON)
    spans = resolve([*found.find(text), analyzer], text)
    assert [(s.start, s.end, s.key) for s in spans] == [(0, 10, "PERSON|text:jan bakker")]


def test_an_exact_directory_match_keeps_the_employee_key(directory: Directory) -> None:
    """covers: AC-15 (a merge that adds nothing keeps the winner)"""
    text = "Is Daan de Wit in?"
    analyzer = _span(3, 14, Source.ANALYZER, text, EntityType.PERSON)
    spans = resolve([*directory.find(text), analyzer], text)
    assert [(s.start, s.end, s.key) for s in spans] == [(3, 14, f"PERSON|emp:{DAAN}")]


@pytest.mark.parametrize("possessive", ["'s", "\u2019s", "'S"])
def test_an_analyzer_possessive_is_trimmed(directory: Directory, possessive: str) -> None:
    """covers: AC-3, AC-15 (the directory match wins, the possessive stays readable)"""
    text = f"Daan de Wit{possessive} claim"
    analyzer = _span(0, 13, Source.ANALYZER, text, EntityType.PERSON)
    spans = resolve([*directory.find(text), analyzer], text)
    assert [(s.start, s.end, s.key) for s in spans] == [(0, 11, f"PERSON|emp:{DAAN}")]


def test_a_possessive_alone_is_dropped_and_other_sources_are_never_trimmed() -> None:
    """covers: AC-15"""
    text = "it's Anna's"
    spans = resolve(
        [
            _span(2, 4, Source.ANALYZER, text, EntityType.PERSON),
            _span(5, 11, Source.PATTERN, text, EntityType.PERSON),
        ],
        text,
    )
    assert [(s.start, s.end) for s in spans] == [(5, 11)]


@pytest.mark.parametrize(
    ("text", "end"),
    [
        ("Jones called", 5),  # ends in s, no apostrophe
        ("O'Neil called", 6),  # an apostrophe inside the name
        ("Anna' called", 5),  # an apostrophe with no s
        ("Anna`s called", 6),  # a backtick is not an apostrophe
    ],
)
def test_an_analyzer_span_without_a_possessive_is_kept_whole(text: str, end: int) -> None:
    """covers: AC-15 (only a trailing apostrophe s is trimmed)"""
    spans = resolve([_span(0, end, Source.ANALYZER, text, EntityType.PERSON)], text)
    assert [(s.start, s.end) for s in spans] == [(0, end)]


def test_a_trimmed_name_outside_the_directory_is_keyed_without_the_possessive() -> None:
    """covers: AC-3, AC-5, AC-15 (the same placeholder as the plain name)"""
    text = "Wilhelmina Oosterhuis's claim"
    spans = resolve([_span(0, 23, Source.ANALYZER, text, EntityType.PERSON)], text)
    assert [(s.start, s.end, s.key, s.original) for s in spans] == [
        (0, 21, "PERSON|text:wilhelmina oosterhuis", "Wilhelmina Oosterhuis")
    ]


def test_a_possessive_is_trimmed_from_any_analyzer_type() -> None:
    """covers: AC-15 (the trim is not limited to PERSON)"""
    text = "NL91ABNA0417164300's balance"
    spans = resolve([_span(0, 20, Source.ANALYZER, text, EntityType.IBAN_CODE)], text)
    assert [(s.start, s.end, s.entity_type) for s in spans] == [(0, 18, EntityType.IBAN_CODE)]


def test_a_single_character_analyzer_span_is_kept() -> None:
    """covers: AC-15 (too short to hold a possessive)"""
    text = "s"
    spans = resolve([_span(0, 1, Source.ANALYZER, text, EntityType.PERSON)], text)
    assert [(s.start, s.end) for s in spans] == [(0, 1)]


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


def _covers(text: str, pieces: list[tuple[int, str]], limit: int) -> None:
    assert all(len(p) <= limit for _, p in pieces)
    assert all(text[o : o + len(p)] == p for o, p in pieces)
    assert pieces[0][0] == 0
    assert pieces[-1][0] + len(pieces[-1][1]) == len(text)
    for (first, piece), (second, _) in pairwise(pieces):
        assert first < second <= first + len(piece)  # no gap between neighbours


def test_long_text_is_split_on_lines_with_true_offsets() -> None:
    """covers: AC-17"""
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(500))
    pieces = chunk(text, limit=1000)
    _covers(text, pieces, 1000)
    assert all(p.endswith("\n") for _, p in pieces[:-1])


def test_a_long_line_splits_on_spaces_and_a_huge_word_is_cut() -> None:
    """covers: AC-17"""
    text = "word " * 300 + "y" * 2500
    _covers(text, chunk(text, limit=1000), 1000)


def test_a_name_across_a_chunk_boundary_is_whole_in_one_chunk() -> None:
    """covers: AC-17 (chunks overlap, so a value cut by one boundary is whole in the next)"""
    for shift in range(0, 40, 3):
        text = "a " * (395 + shift) + "Jan Jansen NL91 ABNA 0417 1643 00 " + "b " * 800
        pieces = chunk(text, limit=1000, overlap=100)
        _covers(text, pieces, 1000)
        assert any("Jan Jansen NL91 ABNA 0417 1643 00" in p for _, p in pieces)


def test_the_overlap_must_leave_room_in_a_chunk() -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk("x" * 50, limit=10, overlap=5)


def test_letters_ignore_case_treats_as_i_never_crash_the_lookup() -> None:
    """covers: AC-4 (re.IGNORECASE folds i, dotless i and dotted capital I; casefold() not)"""
    directory = Directory.from_entries([_entry("TES-00003", "Zoë", "Bakir")])
    text = "BAK\u0131R, BAK\u0130R and bakir"
    spans = directory.find(text)
    assert len(spans) == 3
    assert {s.key for s in spans} == {"PERSON|emp:TES-00003"}


def test_directory_forms_are_stored_in_nfc() -> None:
    """covers: AC-4 (a decomposed form in the export still matches composed text)"""
    directory = Directory.from_entries([_entry("TES-00003", "Zoe\u0308", "Bakir")])
    text = "Zo\u00eb Bakir"
    assert _found(directory.find(text), text) == [(text, EntityType.PERSON)]


@pytest.mark.parametrize(
    ("text", "value", "entity_type"),
    [
        ("employee_TES-00012", "TES-00012", EntityType.EMPLOYEE_ID),
        ("x TES-00012abc", "TES-00012", EntityType.EMPLOYEE_ID),
        ("phone_0612345678", "0612345678", EntityType.PHONE_NUMBER),
        ("iban_NL91ABNA0417164300", "NL91ABNA0417164300", EntityType.IBAN_CODE),
    ],
)
def test_patterns_treat_underscore_and_trailing_letters_as_separators(
    text: str, value: str, entity_type: EntityType
) -> None:
    """covers: AC-3 (snake case keys and file names do not hide a value)"""
    assert (value, entity_type) in _found(find_patterns(text), text)


def test_directory_treats_underscore_as_a_separator(directory: Directory) -> None:
    """covers: AC-4"""
    text = "id_TES-01005 user_daan"
    assert _found(directory.find(text), text) == [
        ("TES-01005", EntityType.EMPLOYEE_ID),
        ("daan", EntityType.PERSON),
    ]
