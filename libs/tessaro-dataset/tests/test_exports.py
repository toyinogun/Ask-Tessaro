"""Exporters: seed versus demo inputs, leaks, tuples and determinism (AC-7 to AC-12, AC-16)."""

import json
from decimal import Decimal

import yaml

from tessaro_dataset import (
    EXPORTERS,
    Dataset,
    export_all,
    export_authentik,
    export_bookstack,
    export_demo_actions,
    export_directory,
    export_erpnext,
    export_frappe_hr,
    export_openfga,
    export_seatsurfing,
    export_snipeit,
    export_zammad,
    export_zulip,
    load_dataset,
    render_exports,
)
from tessaro_dataset.derive import iban_is_valid
from tessaro_dataset.exports.openfga import STAND_IN_CONDITION
from tessaro_dataset.models import LeaveApplication, sensitive_fields
from tessaro_dataset.registry import ALLOWED_RELATIONS, CONDITIONED_RELATIONS, FGA_ORG

from .conftest import PATHS, WEDNESDAY_10

LISA = "TES-01042"


def test_every_target_has_an_exporter() -> None:
    assert set(EXPORTERS) == {
        "frappe_hr",
        "erpnext",
        "zammad",
        "snipeit",
        "seatsurfing",
        "bookstack",
        "authentik",
        "zulip",
        "openfga",
        "directory",
        "demo_actions",
    }


def test_seed_leaves_out_joiners_unless_asked(dataset: Dataset) -> None:
    for name, run in EXPORTERS.items():
        if name in ("directory", "demo_actions", "bookstack"):
            continue
        seed = json.dumps(run(dataset, False).model_dump(mode="json"))
        assert LISA not in seed, name
    full = export_frappe_hr(dataset, include_demo_inputs=True)
    assert LISA in {e.employee for e in full.employees}
    assert LISA in {e.employee_id for e in export_directory(dataset).entries}
    assert LISA in json.dumps(export_openfga(dataset, True).model_dump(mode="json"))


def test_seed_holds_leaver_and_mover_before(dataset: Dataset) -> None:
    employees = {e.employee: e for e in export_frappe_hr(dataset).employees}
    assert employees["TES-01007"].relieving_date is None
    assert employees["TES-01023"].department == "finance"
    assert employees["TES-01023"].reports_to == "TES-01022"
    demo = export_demo_actions(dataset)
    assert [a.action for a in demo.actions] == [
        "create_employee",
        "create_employee",
        "set_relieving_date",
        "move_employee",
    ]
    assert [a.employee_id for a in demo.actions] == [LISA, "TES-01043", "TES-01007", "TES-01023"]
    move = {v.field: v.value for v in demo.actions[3].values}
    assert move == {"department": "payments", "reports_to": "TES-01001", "move_date": "2026-10-14"}
    assert demo.demo_only_ids == (LISA, "TES-01043")


def _sensitive_values(dataset: Dataset) -> list[str]:
    assert sensitive_fields(LeaveApplication) == ("reason",)
    return [a.reason for a in dataset.applications if a.reason]


def test_sensitive_reason_reaches_only_frappe_hr(dataset: Dataset) -> None:
    values = _sensitive_values(dataset)
    assert values
    files = render_exports(export_all(dataset, include_demo_inputs=True))
    for name, content in files.items():
        for value in values:
            if name == "frappe_hr.json":
                assert json.dumps(value)[1:-1] in content
            else:
                assert value not in content, name


def test_tuples(dataset: Dataset) -> None:
    tuples = export_openfga(dataset).tuples
    for t in tuples:
        object_type = t.object.split(":")[0]
        user_type = t.user.split(":")[0]
        assert user_type in ALLOWED_RELATIONS[(object_type, t.relation)]
        expected = CONDITIONED_RELATIONS.get((object_type, t.relation))
        assert (t.condition.name if t.condition else None) == expected
        assert object_type != "lifecycle_case"
    relations = {t.relation for t in tuples}
    assert relations == {
        "owner",
        "team",
        "member",
        "manager",
        "hr_advisor",
        "stand_in",
        "it_approver",
    }
    assert any(t.user == "user:TES-01007" and t.object == "team:workplace" for t in tuples)
    stand_in = [t for t in tuples if t.relation == "stand_in"]
    assert all(t.condition and t.condition.name == STAND_IN_CONDITION for t in stand_in)


def test_it_approvers_hang_off_the_org(dataset: Dataset) -> None:
    """covers: spec 0004 AC-9 (one org it_approver tuple per flagged seed employee)"""
    tuples = export_openfga(dataset).tuples
    approvers = {t.user for t in tuples if t.relation == "it_approver"}
    expected = {f"user:{e.id}" for e in dataset.seed_employees() if e.it_approver}
    assert approvers == expected
    assert "user:TES-01012" in approvers
    assert {t.object for t in tuples if t.relation == "it_approver"} == {f"org:{FGA_ORG}"}


def test_tuple_file_is_fga_cli_shape(dataset: Dataset) -> None:
    rows = yaml.safe_load(
        render_exports({"openfga": export_openfga(dataset)})["openfga.tuples.yaml"]
    )
    assert {"user", "relation", "object"} <= set(rows[0])
    conditioned = [r for r in rows if "condition" in r]
    assert conditioned
    assert set(conditioned[0]["condition"]["context"]) == {"valid_from", "valid_until"}


def test_exports_are_byte_identical() -> None:
    first = render_exports(export_all(load_dataset(PATHS, anchor=WEDNESDAY_10)))
    second = render_exports(export_all(load_dataset(PATHS, anchor=WEDNESDAY_10)))
    assert first == second
    assert len(first) == 11


def test_target_records(dataset: Dataset) -> None:
    claim = export_erpnext(dataset).expense_claims[0]
    assert (claim.name, claim.total_claimed_amount) == ("EXP-0001", Decimal("412.60"))
    assert claim.payable_iban.startswith("NL")
    zammad = export_zammad(dataset)
    repair = next(t for t in zammad.tickets if t.number == "T-1001")
    visible = [a for a in repair.articles if not a.internal]
    assert repair.latest_update == visible[-1].created_at
    assert "AI assistant" in visible[-1].body
    agents = {u.employee_id: u.agent_groups for u in zammad.users if u.agent_groups}
    assert agents["TES-01013"] == ("it",)
    assert agents["TES-01019"] == ("people",)
    assert "TES-01015" not in agents
    assert [g.name for g in zammad.groups] == ["finance", "it", "people", "workplace"]
    snipe = export_snipeit(dataset)
    assert sum(a.assigned_to is None and a.status == "ready_to_deploy" for a in snipe.assets) == 7
    seats = export_seatsurfing(dataset)
    assert seats.bookings[0].enter.hour == 9
    assert {loc.id for loc in seats.locations} == {"amsterdam", "rotterdam"}
    book = export_bookstack(dataset)
    assert len(book.pages) == 20
    assert book.books[0].name == "Tessaro handbook"
    assert {c.slug for c in book.chapters} >= {"time-off", "money"}
    auth = export_authentik(dataset)
    elevated = {g.name for g in auth.groups if g.elevated}
    assert "prod-readonly" in elevated
    assert all("prod-readonly" not in u.groups for u in auth.users)
    zulip = export_zulip(dataset)
    assert any(s.channel == "announcements" for s in zulip.subscriptions)
    assert next(u for u in zulip.users if u.employee_id == "TES-01005").full_name == "Daan de Wit"


def test_exporters_do_not_change_the_dataset(dataset: Dataset) -> None:
    before = dataset.employees
    export_all(dataset, include_demo_inputs=True)
    assert dataset.employees is before


SORT_KEYS: dict[tuple[str, str], tuple[str, ...]] = {
    ("frappe_hr", "departments"): ("department_id",),
    ("frappe_hr", "employees"): ("employee",),
    ("frappe_hr", "leave_allocations"): ("employee", "from_date"),
    ("frappe_hr", "leave_applications"): ("name",),
    ("erpnext", "expense_claims"): ("name",),
    ("zammad", "users"): ("employee_id",),
    ("zammad", "groups"): ("name",),
    ("zammad", "tickets"): ("number",),
    ("snipeit", "users"): ("employee_num",),
    ("snipeit", "assets"): ("asset_tag",),
    ("seatsurfing", "locations"): ("id",),
    ("seatsurfing", "spaces"): ("id",),
    ("seatsurfing", "bookings"): ("id",),
    ("bookstack", "books"): ("slug",),
    ("bookstack", "chapters"): ("slug",),
    ("bookstack", "pages"): ("slug",),
    ("authentik", "users"): ("employee_id",),
    ("authentik", "groups"): ("name",),
    ("zulip", "users"): ("email",),
    ("zulip", "channels"): ("name",),
    ("zulip", "subscriptions"): ("channel", "email"),
    ("openfga", "tuples"): ("object", "relation", "user"),
    ("directory", "entries"): ("employee_id",),
    ("demo_actions", "actions"): ("order",),
}


def test_every_exported_list_is_sorted_by_its_key(dataset: Dataset) -> None:
    """covers: AC-12 (stable record order)"""
    seen: set[tuple[str, str]] = set()
    for name, export in export_all(dataset, include_demo_inputs=True).items():
        for field, rows in export.model_dump(mode="json").items():
            if not (isinstance(rows, list) and rows and isinstance(rows[0], dict)):
                continue
            keys = SORT_KEYS[(name, field)]
            values = [tuple(str(row[k]) for k in keys) for row in rows]
            assert values == sorted(values), f"{name}.{field}"
            seen.add((name, field))
    assert seen == set(SORT_KEYS)


def test_authentik_groups_follow_the_derivation_rules(dataset: Dataset) -> None:
    """covers: AC-9 (groups are derived for every person, never written by hand)"""
    users = {u.employee_id: set(u.groups) for u in export_authentik(dataset, True).users}
    managers = {t.manager_id for t in dataset.teams}
    advisors = {a for t in dataset.teams for a in t.hr_advisor_ids}
    for employee in dataset.employees:
        groups = users[employee.id]
        assert "staff" in groups
        if employee.team_id:
            assert f"team-{employee.team_id}" in groups
        assert ("managers" in groups) == (employee.id in managers), employee.id
        assert ("people-advisors" in groups) == (employee.id in advisors), employee.id
        assert ("it-agents" in groups) == employee.it_agent, employee.id
        assert ("finance-team" in groups) == (employee.team_id == "finance"), employee.id
        assert ("workplace-team" in groups) == (employee.team_id == "workplace"), employee.id


def test_tuple_users_are_known_employees_or_teams(dataset: Dataset) -> None:
    """covers: AC-8 (user objects are user:<employee id>)"""
    known = {e.id for e in dataset.employees}
    tuples = export_openfga(dataset, True).tuples
    for t in tuples:
        kind, _, ident = t.user.partition(":")
        if kind == "user":
            assert ident in known, t
    owners = {(t.object, t.user) for t in tuples if t.relation == "owner"}
    assert owners == {(f"employee:{e.id}", f"user:{e.id}") for e in dataset.employees}


def test_every_claim_iban_is_valid_on_the_made_up_bank(dataset: Dataset) -> None:
    """covers: AC-11 (IBANs on bank code XTSR with a valid mod 97 checksum)"""
    claims = export_erpnext(dataset, True).expense_claims
    assert claims
    for claim in claims:
        assert claim.payable_iban.startswith("NL")
        assert claim.payable_iban[4:8] == "XTSR"
        assert iban_is_valid(claim.payable_iban), claim.name


def test_create_actions_carry_the_joiner_record(dataset: Dataset) -> None:
    """covers: AC-16 (each change lists the record and its field values)"""
    creates = [a for a in export_demo_actions(dataset).actions if a.action == "create_employee"]
    lisa, second = ({v.field: v.value for v in a.values} for a in creates)
    assert lisa["employee"] == LISA
    assert lisa["date_of_joining"] == "2026-10-12"
    assert (lisa["department"], lisa["reports_to"]) == ("payments", "TES-01001")
    assert lisa["company_email"].endswith("@tessaro.example")
    assert second["employee"] == "TES-01043"
    assert second["date_of_joining"] > lisa["date_of_joining"]
    assert [a.demo_step for a in creates] == [3, 5]
