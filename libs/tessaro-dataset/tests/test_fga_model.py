"""The registry follows authz/model.fga, checked without the fga CLI (spec 0004 AC-9)."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tessaro_dataset.registry import ALLOWED_RELATIONS, CONDITIONED_RELATIONS

from .conftest import REPO_ROOT

AUTHZ = REPO_ROOT / "authz"
MODEL = AUTHZ / "model.fga"
SPEC = REPO_ROOT / "docs" / "specs" / "0004-record-access-model" / "index.md"
TEST_FILES = sorted(AUTHZ.glob("*.fga.yaml"))

# Tuples a workflow writes, the only ones a test file may add inline (spec 0004 AC-10).
WORKFLOW_RELATIONS = frozenset(
    {
        ("lifecycle_case", "org"),
        ("lifecycle_case", "team"),
        ("lifecycle_case", "subject"),
        ("employee", "team"),
    }
)

_TYPE = re.compile(r"^type\s+(\w+)\s*$")
_DIRECT = re.compile(r"^define\s+(\w+)\s*:\s*\[([^\]]*)\]")

Relations = dict[tuple[str, str], frozenset[str]]
Conditions = dict[tuple[str, str], str]


def parse_model(text: str) -> tuple[Relations, Conditions]:
    """Directly assignable (type, relation) pairs, their user types and any condition."""
    relations: Relations = {}
    conditions: Conditions = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("condition "):
            current = None
            continue
        if found := _TYPE.match(line):
            current = found.group(1)
            continue
        direct = _DIRECT.match(line)
        if current is None or direct is None:
            continue
        key = (current, direct.group(1))
        users: set[str] = set()
        for part in direct.group(2).split(","):
            user, _, condition = part.strip().partition(" with ")
            users.add(user.strip())
            if condition:
                conditions[key] = condition.strip()
        relations[key] = frozenset(users)
    return relations, conditions


def test_registry_equals_the_model() -> None:
    """covers: AC-9 (ALLOWED_RELATIONS and CONDITIONED_RELATIONS follow the model)"""
    relations, conditions = parse_model(MODEL.read_text())
    assert relations == dict(ALLOWED_RELATIONS)
    assert conditions == dict(CONDITIONED_RELATIONS)


def test_a_dropped_relation_is_caught(tmp_path: Path) -> None:
    """covers: AC-9 (drift between the model and the registry fails)"""
    text = MODEL.read_text().replace("    define hr_advisor: [user]\n", "")
    scratch = tmp_path / "model.fga"
    scratch.write_text(text)
    relations, _ = parse_model(scratch.read_text())
    assert ("team", "hr_advisor") not in relations
    assert relations != dict(ALLOWED_RELATIONS)


def test_parser_reads_conditions_and_skips_computed_relations() -> None:
    relations, conditions = parse_model(
        "model\n  schema 1.1\ntype user\ntype team\n  relations\n"
        "    define stand_in: [user with within_window, team#member]\n"
        "    define approver: stand_in\n"
        "condition within_window(x: timestamp) {\n  x < x\n}\n"
    )
    assert relations == {("team", "stand_in"): frozenset({"user", "team#member"})}
    assert conditions == {("team", "stand_in"): "within_window"}


@pytest.mark.parametrize("relation", ["can_approve", "can_view", "approver"])
def test_computed_relations_are_not_assignable(relation: str) -> None:
    relations, _ = parse_model(MODEL.read_text())
    assert all(rel != relation for _, rel in relations)


def _spec_model_block() -> list[str]:
    """The model block in spec 0004's *Feature design*, one line per entry."""
    blocks = re.findall(r"```text\n(model\n.*?)```", SPEC.read_text(), flags=re.DOTALL)
    assert len(blocks) == 1, "spec 0004 should hold exactly one model block"
    return [line.rstrip() for line in blocks[0].strip().splitlines()]


def test_model_file_matches_the_spec_line_for_line() -> None:
    """covers: AC-1 (authz/model.fga holds exactly the model in the spec)"""
    model = [line.rstrip() for line in MODEL.read_text().strip().splitlines()]
    assert model == _spec_model_block()


def test_model_declares_the_five_types_and_the_window_condition() -> None:
    """covers: AC-1 (schema 1.1, the five types and within_window)"""
    text = MODEL.read_text()
    types = {m.group(1) for line in text.splitlines() if (m := _TYPE.match(line.strip()))}
    assert types == {"user", "org", "team", "employee", "lifecycle_case"}
    assert "schema 1.1" in text
    assert "current_time >= valid_from && current_time < valid_until" in text


def test_there_is_a_test_file_per_area() -> None:
    """covers: AC-10 (one fga test file each for employees, stand ins, cases and the mover)"""
    names = {path.name for path in TEST_FILES}
    assert names == {
        "employee.fga.yaml",
        "stand_in.fga.yaml",
        "lifecycle_case.fga.yaml",
        "mover.fga.yaml",
    }


def _load(path: Path) -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(path.read_text())
    return document


@pytest.mark.parametrize("path", TEST_FILES, ids=lambda p: p.name)
def test_test_files_read_the_model_and_the_dataset_tuples_beside_them(path: Path) -> None:
    """covers: AC-10 (paths relative to authz/, never `../`, which fga refuses)"""
    document = _load(path)
    assert document["model_file"] == "model.fga"
    assert document["tuple_file"] == ".build/openfga.tuples.yaml"
    assert "../" not in path.read_text()


@pytest.mark.parametrize("path", TEST_FILES, ids=lambda p: p.name)
def test_inline_tuples_are_only_workflow_written_and_assignable(path: Path) -> None:
    """covers: AC-10 (inline tuples add only what a workflow writes, and the model accepts them)"""
    relations, _ = parse_model(MODEL.read_text())
    for test in _load(path)["tests"]:
        for row in test.get("tuples", []):
            object_type = row["object"].partition(":")[0]
            user_type = row["user"].partition(":")[0]
            key = (object_type, row["relation"])
            assert key in WORKFLOW_RELATIONS, row
            assert user_type in relations[key], row


@pytest.mark.parametrize("path", TEST_FILES, ids=lambda p: p.name)
def test_every_check_carries_a_current_time(path: Path) -> None:
    """A check with no current_time would make every stand in tuple error, hiding real denials."""
    for test in _load(path)["tests"]:
        for check in test.get("check", []):
            assert "current_time" in check.get("context", {}), (test["name"], check)
