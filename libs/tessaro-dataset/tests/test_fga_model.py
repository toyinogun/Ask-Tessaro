"""The registry follows authz/model.fga, checked without the fga CLI (spec 0004 AC-9)."""

import re
from pathlib import Path

import pytest

from tessaro_dataset.registry import ALLOWED_RELATIONS, CONDITIONED_RELATIONS

from .conftest import REPO_ROOT

MODEL = REPO_ROOT / "authz" / "model.fga"

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
