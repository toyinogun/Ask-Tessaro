"""The `tessaro-dataset` command: exit codes, flags and env settings (AC-13, AC-16)."""

import io
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from tessaro_dataset import AMSTERDAM
from tessaro_dataset.cli import main

from .conftest import REPO_ROOT

ANCHOR = "2026-10-07T10:00+02:00"


def run(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(list(args), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_validate_ok() -> None:
    code, out, _ = run("validate", "--root", str(REPO_ROOT), "--anchor", ANCHOR)
    assert code == 0
    assert "33 employees valid" in out


def test_validate_warns_on_weekend() -> None:
    code, _, err = run("validate", "--root", str(REPO_ROOT), "--anchor", "2026-10-10T10:00+02:00")
    assert code == 0
    assert "weekend" in err


def test_validate_broken_copy_prints_every_problem(tmp_path: Path) -> None:
    shutil.copytree(
        REPO_ROOT / "dataset", tmp_path / "dataset", ignore=shutil.ignore_patterns("build")
    )
    shutil.copytree(REPO_ROOT / "bundles", tmp_path / "bundles")
    employees = tmp_path / "dataset" / "employees.yaml"
    text = employees.read_text().replace("team_id: finance", "team_id: sales")
    employees.write_text(text.replace("- dutch_name", "- dutch_name\n  - dutch_name"))
    code, _, err = run("validate", "--root", str(tmp_path), "--anchor", ANCHOR)
    assert code == 1
    assert "unknown team sales" in err
    assert "dutch_name" in err


def test_usage_errors() -> None:
    assert run("validate", "--bogus")[0] == 2
    assert run("frobnicate")[0] == 2
    assert run("validate", "--anchor", "yesterday")[0] == 2
    assert run("validate", "--anchor", "2026-10-07T10:00")[0] == 2
    assert run("validate", "--stand-in-minutes", "0")[0] == 2
    assert run("standin", "--minutes", "x")[0] == 2
    assert run("--help")[0] == 0


def test_export_writes_every_target(tmp_path: Path) -> None:
    out_dir = tmp_path / "build"
    code, out, _ = run(
        "export",
        "--root",
        str(REPO_ROOT),
        "--anchor",
        ANCHOR,
        "--out",
        str(out_dir),
        "--stand-in-minutes",
        "20",
        "--include-demo-inputs",
    )
    assert code == 0
    assert "wrote 11 files" in out
    assert (out_dir / "openfga.tuples.yaml").exists()
    assert "TES-01042" in (out_dir / "frappe_hr.json").read_text()
    tuples = yaml.safe_load((out_dir / "openfga.tuples.yaml").read_text())
    windows = [t["condition"]["context"]["valid_until"] for t in tuples if "condition" in t]
    assert "2026-10-07T10:20:00+02:00" in windows


def test_env_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TESSARO_DATASET_ANCHOR", "2026-10-07T08:00:00+00:00")
    monkeypatch.setenv("TESSARO_DATASET_STAND_IN_MINUTES", "30")
    code, out, _ = run("validate", "--root", str(REPO_ROOT))
    assert code == 0
    assert "2026-10-07T10:00:00+02:00" in out
    monkeypatch.setenv("TESSARO_DATASET_STAND_IN_MINUTES", "-1")
    code, _, err = run("validate", "--root", str(REPO_ROOT))
    assert code == 2
    assert "TESSARO_DATASET" in err
    monkeypatch.setenv("TESSARO_DATASET_STAND_IN_MINUTES", "15")
    monkeypatch.setenv("TESSARO_DATASET_ANCHOR", "2026-10-07T10:00:00")
    assert run("validate", "--root", str(REPO_ROOT))[0] == 2


def test_standin_prints_a_fresh_window() -> None:
    before = datetime.now(AMSTERDAM).replace(second=0, microsecond=0)
    code, out, _ = run("standin", "--root", str(REPO_ROOT), "--minutes", "5")
    assert code == 0
    rows = yaml.safe_load(out)
    assert len(rows) == 1
    row = rows[0]
    assert (row["user"], row["relation"], row["object"]) == (
        "user:TES-01002",
        "stand_in",
        "team:payments",
    )
    start = datetime.fromisoformat(row["condition"]["context"]["valid_from"])
    end = datetime.fromisoformat(row["condition"]["context"]["valid_until"])
    assert end - start == timedelta(minutes=5)
    assert before <= start <= before + timedelta(minutes=1)


def test_anchor_flag_wins_over_the_env_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    """covers: AC-3 (--anchor takes precedence over TESSARO_DATASET_ANCHOR)"""
    monkeypatch.setenv("TESSARO_DATASET_ANCHOR", "2026-10-07T08:00:00+00:00")
    code, out, _ = run("validate", "--root", str(REPO_ROOT), "--anchor", "2026-10-09T11:00+02:00")
    assert code == 0
    assert "2026-10-09T11:00:00+02:00" in out


def test_env_stand_in_minutes_moves_the_window_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """covers: AC-8, AC-13 (TESSARO_DATASET_STAND_IN_MINUTES sets valid_until)"""
    monkeypatch.setenv("TESSARO_DATASET_STAND_IN_MINUTES", "30")
    out_dir = tmp_path / "build"
    code, _, _ = run("export", "--root", str(REPO_ROOT), "--anchor", ANCHOR, "--out", str(out_dir))
    assert code == 0
    tuples = yaml.safe_load((out_dir / "openfga.tuples.yaml").read_text())
    pieter = next(
        t for t in tuples if t["relation"] == "stand_in" and t["object"] == "team:payments"
    )
    assert pieter["condition"]["context"]["valid_until"] == "2026-10-07T10:30:00+02:00"


def test_export_without_the_flag_keeps_joiners_in_the_directory_only(tmp_path: Path) -> None:
    """covers: AC-7, AC-13 (seed export leaves out demo inputs; directory always has them)"""
    out_dir = tmp_path / "build"
    code, _, _ = run("export", "--root", str(REPO_ROOT), "--anchor", ANCHOR, "--out", str(out_dir))
    assert code == 0
    assert "TES-01042" not in (out_dir / "frappe_hr.json").read_text()
    assert "TES-01042" not in (out_dir / "openfga.tuples.yaml").read_text()
    assert "TES-01042" in (out_dir / "directory.json").read_text()
