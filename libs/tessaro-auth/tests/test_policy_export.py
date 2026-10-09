"""The role to scope table (AC-1, AC-10) and its generated OPA data never drift (AC-2)."""

import json
from pathlib import Path

import pytest

from tessaro_auth.claims import Role
from tessaro_auth.policy_export import ROLE_SCOPES_DATA, export, generated_files, main
from tessaro_auth.roles import ROLE_SCOPES
from tessaro_contracts.export import TOOLS_DATA, repo_root
from tessaro_contracts.scopes import Scope

ROOT = repo_root(Path(__file__).parent)

EMPLOYEE_SCOPES = frozenset(
    {
        Scope.IT_READ,
        Scope.HR_READ,
        Scope.FINANCE_READ,
        Scope.WORKPLACE_READ,
        Scope.KB_READ,
        Scope.QUEUE_HANDOFF,
        Scope.WORKFLOW_READ,
    }
)


# AC-1: exactly PRD 8.2, Manager flattened


def test_role_scopes_match_prd_8_2() -> None:
    assert dict(ROLE_SCOPES) == {
        Role.EMPLOYEE: EMPLOYEE_SCOPES,
        Role.MANAGER: EMPLOYEE_SCOPES | {Scope.TEAM_READ},
        Role.IT_SERVICE_DESK: frozenset({Scope.IT_READ_ANY, Scope.WORKFLOW_READ_ANY}),
        Role.PEOPLE_ADVISOR: frozenset({Scope.HR_READ_ANY, Scope.WORKFLOW_READ_ANY}),
        Role.WORKFLOW_WORKER: frozenset(
            {Scope.IDENTITY_WRITE, Scope.IT_WRITE, Scope.WORKPLACE_WRITE, Scope.HR_READ_ANY}
        ),
    }


def test_role_scopes_values_are_frozensets() -> None:
    assert all(isinstance(scopes, frozenset) for scopes in ROLE_SCOPES.values())


# AC-2: generated file shape and drift


def test_role_scopes_data_shape() -> None:
    data = json.loads(generated_files()[ROLE_SCOPES_DATA])
    assert set(data) == {"role_scopes"}
    assert set(data["role_scopes"]) == {role.value for role in Role}
    for role, scopes in data["role_scopes"].items():
        assert scopes == sorted(scopes)
        assert set(scopes) == {s.value for s in ROLE_SCOPES[Role(role)]}


def test_policy_files_sit_flat_in_policy() -> None:
    assert Path("policy/role_scopes.json") == ROLE_SCOPES_DATA
    assert Path("policy/tools.json") == TOOLS_DATA
    assert not (ROOT / "policy/data").exists()


@pytest.mark.parametrize("relative", sorted(generated_files(), key=str))
def test_committed_policy_data_matches_role_scopes(relative: Path) -> None:
    committed = ROOT / relative
    assert committed.exists(), f"{relative} is missing; run `just contracts`"
    assert committed.read_text(encoding="utf-8") == generated_files()[relative], (
        f"{relative} is stale; run `just contracts`"
    )


def test_export_writes_under_root(tmp_path: Path) -> None:
    export(tmp_path)
    written = (tmp_path / ROLE_SCOPES_DATA).read_text(encoding="utf-8")
    assert written == generated_files()[ROLE_SCOPES_DATA]


def test_main_writes_and_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(tmp_path)]) == 0
    assert (tmp_path / ROLE_SCOPES_DATA).exists()
    assert str(ROLE_SCOPES_DATA) in capsys.readouterr().out


def test_main_fails_on_a_write_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "policy").write_text("not a folder", encoding="utf-8")
    assert main(["--root", str(tmp_path)]) == 1
    assert "policy" in capsys.readouterr().err
