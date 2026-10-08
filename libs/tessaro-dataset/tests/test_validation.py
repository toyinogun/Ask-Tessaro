"""Invalid datasets fail with one DatasetError listing every problem (AC-5, AC-6)."""

from typing import Any

import pytest

from tessaro_dataset.assemble import RawPage, RawSources

from .conftest import edited, find, problems_of


def _has(problems: list[str], *fragments: str) -> bool:
    return any(all(f in p for f in fragments) for p in problems)


def test_real_sources_are_valid(sources: RawSources) -> None:
    assert problems_of(sources) == []


def test_four_problems_reported_together(sources: RawSources) -> None:
    def break_employees(doc: dict[str, Any]) -> None:
        find(doc, "employees", "TES-01008")["team_id"] = "marketing"
        find(doc, "employees", "TES-01010")["first_name"] = "Lotte"
        find(doc, "employees", "TES-01010")["last_name"] = "Meijer"
        find(doc, "employees", "TES-01005")["traps"] = []

    def overdraw(doc: dict[str, Any]) -> None:
        find(doc, "applications", "leave-0006").update(
            from_date="@anchor+1wd", to_date="@anchor+50wd"
        )

    broken = edited(edited(sources, "employees.yaml", break_employees), "leave.yaml", overdraw)
    problems = problems_of(broken)
    assert _has(problems, "TES-01008", "unknown team marketing")
    assert _has(problems, "lotte.meijer@tessaro.example", "duplicate email")
    assert _has(problems, "below zero")
    assert _has(problems, "dutch_name", "exactly once")


@pytest.mark.parametrize(
    ("file", "key", "record_id", "field", "value", "expected"),
    [
        ("bookings.yaml", "bookings", "book-0001", "start", 630, "start"),
        ("employees.yaml", "employees", "TES-01001", "it_agent", "no", "it_agent"),
        ("employees.yaml", "employees", "TES-01001", "it_agent", 1, "it_agent"),
        ("leave.yaml", "applications", "leave-0002", "from_date", "@tomorrow", "unknown date"),
        ("leave.yaml", "applications", "leave-0002", "from_date", "@anchor+15m", "date field"),
        ("claims.yaml", "claims", "EXP-0002", "amount", 149.0, "quoted strings"),
        ("claims.yaml", "claims", "EXP-0002", "amount", "149", "2 decimal places"),
        ("claims.yaml", "claims", "EXP-0002", "amount", "abc", "not an amount"),
        ("employees.yaml", "employees", "TES-01001", "phone", "+31 6 5555 0000", "phone"),
        ("employees.yaml", "employees", "TES-01001", "nickname", "Mia", "nickname"),
    ],
)
def test_field_problems(
    sources: RawSources,
    file: str,
    key: str,
    record_id: str,
    field: str,
    value: object,
    expected: str,
) -> None:
    id_key = "id"

    def mutate(doc: dict[str, Any]) -> None:
        find(doc, key, record_id, id_key)[field] = value

    problems = problems_of(edited(sources, file, mutate))
    assert _has(problems, record_id, expected), problems


def _edit(sources: RawSources, file: str, key: str, record_id: str, **changes: object) -> list[str]:
    def mutate(doc: dict[str, Any]) -> None:
        record = find(doc, key, record_id, "asset_tag" if key == "devices" else "id")
        record.update(changes)

    return problems_of(edited(sources, file, mutate))


@pytest.mark.parametrize(
    ("file", "key", "record_id", "changes", "expected"),
    [
        ("employees.yaml", "employees", "TES-01004", {"office_id": "utrecht"}, "unknown office"),
        ("employees.yaml", "employees", "TES-01004", {"demo_role": None}, "refused_colleague"),
        ("employees.yaml", "employees", "TES-01004", {"is_ceo": True}, "exactly one CEO"),
        ("employees.yaml", "employees", "TES-01004", {"joining_date": "@anchor+1d"}, "demo_input"),
        ("employees.yaml", "employees", "TES-01004", {"relieving_date": "@anchor+3wd"}, "leavers"),
        ("employees.yaml", "employees", "TES-01012", {"it_approver": False}, "it_approver"),
        ("standins.yaml", "standins", "standin-payments", {"user_id": "TES-01001"}, "manager"),
        ("standins.yaml", "standins", "standin-payments", {"valid_from": "@anchor+1d"}, "before"),
        ("standins.yaml", "standins", "standin-payments", {"team_id": "sales"}, "unknown team"),
        ("leave.yaml", "applications", "leave-0002", {"from_date": "@anchor+5wd"}, "after to_date"),
        ("leave.yaml", "applications", "leave-0002", {"to_date": "2026-10-10"}, "weekend"),
        ("leave.yaml", "applications", "leave-0002", {"employee_id": "TES-01042"}, "joiner"),
        ("leave.yaml", "applications", "leave-0002", {"employee_id": "TES-09999"}, "unknown"),
        ("claims.yaml", "claims", "EXP-0001", {"approved_on": None}, "approved_on"),
        ("claims.yaml", "claims", "EXP-0003", {"paid_on": None}, "paid_on"),
        ("claims.yaml", "claims", "EXP-0002", {"submitted_on": None}, "submitted_on"),
        ("claims.yaml", "claims", "EXP-0002", {"approver_id": "TES-01007"}, "claimant"),
        ("claims.yaml", "claims", "EXP-0001", {"expected_payment_date": "@anchor"}, "on or after"),
        ("claims.yaml", "claims", "EXP-0002", {"status": "paid"}, "paid_on"),
        ("devices.yaml", "devices", "TES-LT-0001", {"assigned_to": None}, "assigned_to"),
        ("devices.yaml", "devices", "TES-LT-0032", {"assigned_to": "TES-01001"}, "ready_to"),
        ("devices.yaml", "devices", "TES-LT-0001", {"laptop_profile": "gamer"}, "unknown profile"),
        ("devices.yaml", "devices", "TES-LT-0002", {"serial": "TSR0007331"}, "duplicate serial"),
        ("tickets.yaml", "tickets", "T-1002", {"pending_until": None}, "pending_until"),
        ("tickets.yaml", "tickets", "T-1001", {"state": "closed"}, "in_repair"),
        ("tickets.yaml", "tickets", "T-1001", {"owner_id": "TES-01015"}, "cannot own"),
        ("tickets.yaml", "tickets", "T-1005", {"owner_id": "TES-01013"}, "cannot own"),
        ("tickets.yaml", "tickets", "T-1001", {"asset_tag": "TES-LT-9999"}, "unknown device"),
        ("tickets.yaml", "tickets", "T-1001", {"created_at": "@anchor"}, "back in time"),
        (
            "bookings.yaml",
            "bookings",
            "book-0004",
            {"status": "booked", "space_id": "ams-desk-03"},
            "overlaps",
        ),
        ("bookings.yaml", "bookings", "book-0001", {"start": "18:00"}, "before end"),
        ("bookings.yaml", "bookings", "book-0001", {"date": "2026-10-11"}, "weekend"),
        ("bookings.yaml", "bookings", "book-0001", {"space_id": "ams-desk-99"}, "unknown space"),
        ("company.yaml", "teams", "payments", {"manager_id": "TES-01011"}, "not in the team"),
        ("company.yaml", "teams", "it", {"ticket_queue": None}, "queues"),
        ("company.yaml", "spaces", "ams-desk-01", {"office_id": "utrecht"}, "unknown office"),
        ("channels.yaml", "channels", "general", {"extra_member_ids": ["TES-09999"]}, "unknown"),
        ("leave.yaml", "applications", "leave-0004", {"traps": []}, "sensitive_absence"),
    ],
)
def test_cross_record_problems(
    sources: RawSources,
    file: str,
    key: str,
    record_id: str,
    changes: dict[str, object],
    expected: str,
) -> None:
    if key == "channels":

        def mutate(doc: dict[str, Any]) -> None:
            find(doc, key, record_id, "name").update(changes)

        problems = problems_of(edited(sources, file, mutate))
    else:
        problems = _edit(sources, file, key, record_id, **changes)
    assert _has(problems, expected), problems


def test_duplicate_trap_and_missing_cast(sources: RawSources) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        find(doc, "employees", "TES-01004")["traps"] = ["dutch_name"]
        find(doc, "employees", "TES-01003")["demo_role"] = "manager"

    problems = problems_of(edited(sources, "employees.yaml", mutate))
    assert _has(problems, "dutch_name", "found 2")
    assert _has(problems, "manager", "TES-01003")
    assert _has(problems, "persona", "none")


def test_balance_and_allocation_rules(sources: RawSources) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["allocations"][0]["days"] = 30

    problems = problems_of(edited(sources, "leave.yaml", mutate))
    assert _has(problems, "must be 25 days")


def test_minimums(sources: RawSources) -> None:
    def no_stock(doc: dict[str, Any]) -> None:
        doc["devices"] = [d for d in doc["devices"] if d["status"] != "ready_to_deploy"]

    assert _has(problems_of(edited(sources, "devices.yaml", no_stock)), "laptops in stock")

    def no_vacation(doc: dict[str, Any]) -> None:
        doc["applications"] = [
            a for a in doc["applications"] if a["id"] not in ("leave-0001", "leave-0002")
        ]

    problems = problems_of(edited(sources, "leave.yaml", no_vacation))
    assert _has(problems, "covering the anchor date")
    assert _has(problems, "on vacation in 5 working days")

    def one_state(doc: dict[str, Any]) -> None:
        for b in doc["bookings"]:
            b["status"] = "booked"
        doc["bookings"] = [b for b in doc["bookings"] if b["id"] != "book-0004"]

    assert _has(problems_of(edited(sources, "bookings.yaml", one_state)), "more than one state")

    def full_office(doc: dict[str, Any]) -> None:
        doc["bookings"] += [
            {
                "id": f"fill-{i:02d}-{d}",
                "employee_id": "TES-01009",
                "space_id": f"ams-desk-{i:02d}",
                "date": "@next_monday",
                "start": "09:00",
                "end": "17:00",
                "status": "booked",
            }
            for i in range(1, 13)
            for d in ("x",)
        ]

    assert _has(problems_of(edited(sources, "bookings.yaml", full_office)), "free desks")


def test_leaver_and_mover_minimums(sources: RawSources) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        find(doc, "employees", "TES-01007")["relieving_date"] = "@anchor+1wd"
        find(doc, "employees", "TES-01023")["pending_move"] = {
            "to_team_id": "it",
            "move_date": "@anchor+5wd",
        }

    problems = problems_of(edited(sources, "employees.yaml", mutate))
    assert _has(problems, "leave on the anchor date")
    assert _has(problems, "mover must move")

    def no_standin(doc: dict[str, Any]) -> None:
        doc["standins"] = [s for s in doc["standins"] if s["id"] != "standin-workplace"]

    assert _has(problems_of(edited(sources, "standins.yaml", no_standin)), "another team")

    def no_pieter(doc: dict[str, Any]) -> None:
        doc["standins"] = [s for s in doc["standins"] if s["id"] != "standin-payments"]

    assert _has(problems_of(edited(sources, "standins.yaml", no_pieter)), "stand in arrangement")


def test_structural_problems(sources: RawSources) -> None:
    missing = RawSources(
        files={k: v for k, v in sources.files.items() if k != "claims.yaml"},
        bundles=sources.bundles,
        pages=sources.pages,
    )
    assert _has(problems_of(missing), "claims.yaml", "missing")
    wrong_key = edited(sources, "channels.yaml", lambda doc: doc.update(chans=doc.pop("channels")))
    assert _has(problems_of(wrong_key), "top level 'channels'")
    not_list = edited(sources, "bookings.yaml", lambda doc: doc.update(bookings={"a": 1}))
    assert _has(problems_of(not_list), "expected a list")


def test_bundle_problems(sources: RawSources) -> None:
    bundles = dict(sources.bundles)
    payments = dict(bundles.pop("payments.yaml"))  # type: ignore[call-overload]
    bundles["payments.yaml"] = {
        **payments,
        "authentik_groups": ["staff", "gods"],
        "zulip_channels": ["random"],
        "default_office": "utrecht",
        "laptop_profile": "gamer",
    }
    bundles["sales.yaml"] = {**payments, "team": "sales"}
    del bundles["it.yaml"]
    broken = RawSources(files=sources.files, bundles=bundles, pages=sources.pages)
    problems = problems_of(broken)
    for fragment in (
        "unknown Authentik group gods",
        "unknown Zulip channel random",
        "unknown office utrecht",
        "unknown laptop profile gamer",
        "bundle for an unknown team",
        "team has no access bundle",
    ):
        assert _has(problems, fragment), fragment


def test_handbook_problems(sources: RawSources) -> None:
    pages = [p for p in sources.pages if p.slug != "working-abroad"]
    reworded = [
        RawPage(p.slug, p.front_matter, p.body.replace("before 09:30", "early"))
        if p.slug == "reporting-sick"
        else p
        for p in pages
    ]
    extra = RawPage("misc", {"title": "Misc", "chapter": "Other", "owner_team": "sales"}, "x")
    broken = RawSources(files=sources.files, bundles=sources.bundles, pages=[*reworded, extra])
    problems = problems_of(broken)
    assert _has(problems, "working-abroad", "missing")
    assert _has(problems, "before 09:30")
    assert _has(problems, "misc", "owner_team")
    bad_meta = RawPage("broken", ["not", "a", "mapping"], "body")
    assert _has(
        problems_of(RawSources(sources.files, sources.bundles, [*pages, bad_meta])), "broken"
    )


@pytest.mark.parametrize(
    ("file", "key", "record_id", "what"),
    [
        ("employees.yaml", "employees", "TES-01004", "employee id"),
        ("leave.yaml", "applications", "leave-0002", "application id"),
        ("claims.yaml", "claims", "EXP-0002", "claim id"),
        ("tickets.yaml", "tickets", "T-1002", "ticket id"),
        ("bookings.yaml", "bookings", "book-0001", "booking id"),
    ],
)
def test_duplicate_ids_are_reported(
    sources: RawSources, file: str, key: str, record_id: str, what: str
) -> None:
    """covers: AC-6 (duplicate IDs)"""

    def mutate(doc: dict[str, Any]) -> None:
        doc[key].append(dict(find(doc, key, record_id)))

    problems = problems_of(edited(sources, file, mutate))
    assert _has(problems, file, record_id, f"duplicate {what}"), problems


def test_article_earlier_than_the_one_before_is_reported(sources: RawSources) -> None:
    """covers: AC-6 (article times that go backwards)"""

    def mutate(doc: dict[str, Any]) -> None:
        articles = find(doc, "tickets", "T-1001")["articles"]
        articles[1]["at"] = "@anchor-2dT10:00"

    problems = problems_of(edited(sources, "tickets.yaml", mutate))
    assert _has(problems, "tickets.yaml", "T-1001", "goes back in time"), problems


def test_pending_move_to_an_unknown_team_is_reported(sources: RawSources) -> None:
    """covers: AC-6 (dangling references)"""

    def mutate(doc: dict[str, Any]) -> None:
        find(doc, "employees", "TES-01023")["pending_move"]["to_team_id"] = "sales"

    problems = problems_of(edited(sources, "employees.yaml", mutate))
    assert _has(problems, "TES-01023", "pending_move names an unknown team"), problems


def test_every_problem_names_its_file_and_record(sources: RawSources) -> None:
    """covers: AC-2, AC-6 (a bad date expression names the file and the record)"""

    def mutate(doc: dict[str, Any]) -> None:
        find(doc, "applications", "leave-0002")["to_date"] = "next week"

    problems = problems_of(edited(sources, "leave.yaml", mutate))
    assert any(p.startswith("leave.yaml [leave-0002]:") for p in problems), problems
