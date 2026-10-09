"""`just authz-load` helper: read fga output, then set the store and model IDs (spec 0004 AC-11)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tessaro_dataset.fgaload import (
    MODEL_VAR,
    STORE_VAR,
    FgaLoadError,
    StoreCreated,
    check_tuple_write,
    main,
    parse_store_create,
    set_env,
)

from .conftest import REPO_ROOT

STORE_JSON = json.dumps(
    {
        "store": {"id": "01STORE", "name": "tessaro"},
        "model": {"authorization_model_id": "01MODEL"},
    }
)
WRITE_OK = json.dumps({"failed": [], "failed_count": 0, "successful_count": 3, "total_count": 3})
WRITE_FAILED = json.dumps(
    {
        "failed": [{"tuple_key": {"object": "employee:a"}, "reason": "relation not found"}],
        "failed_count": 1,
        "successful_count": 2,
        "total_count": 3,
    }
)


def test_parse_store_create_reads_both_ids() -> None:
    assert parse_store_create(STORE_JSON) == StoreCreated(store_id="01STORE", model_id="01MODEL")


@pytest.mark.parametrize(
    "text",
    ["", "not json", "[]", json.dumps({"store": {"id": "01STORE"}}), json.dumps({"model": {}})],
)
def test_parse_store_create_rejects_bad_output(text: str) -> None:
    with pytest.raises(FgaLoadError):
        parse_store_create(text)


def test_check_tuple_write_counts_successes() -> None:
    assert check_tuple_write(WRITE_OK) == 3


@pytest.mark.parametrize("text", [WRITE_FAILED, "{}", "nope", json.dumps({"failed_count": "x"})])
def test_check_tuple_write_rejects_any_failure(text: str) -> None:
    with pytest.raises(FgaLoadError):
        check_tuple_write(text)


def test_set_env_replaces_existing_lines_and_appends_missing() -> None:
    text = "LOG_LEVEL=DEBUG\nOPENFGA_STORE_ID=old\n# OPENFGA_MODEL_ID=comment\n"
    updated = set_env(text, {"OPENFGA_STORE_ID": "new", "OPENFGA_MODEL_ID": "m1"})
    assert updated == (
        "LOG_LEVEL=DEBUG\nOPENFGA_STORE_ID=new\n# OPENFGA_MODEL_ID=comment\nOPENFGA_MODEL_ID=m1\n"
    )


def test_set_env_collapses_duplicate_lines() -> None:
    updated = set_env("A=1\nA=2\n", {"A": "3"})
    assert updated == "A=3\n"


def test_set_env_does_not_mutate_its_input() -> None:
    values = {"A": "1"}
    set_env("", values)
    assert values == {"A": "1"}


def _files(tmp_path: Path, store: str, write: str) -> tuple[Path, Path, Path]:
    env = tmp_path / ".env"
    env.write_text("OPENFGA_API_URL=http://localhost:18080\nOPENFGA_STORE_ID=\n")
    store_file = tmp_path / "store.json"
    store_file.write_text(store)
    write_file = tmp_path / "write.json"
    write_file.write_text(write)
    return env, store_file, write_file


def test_ids_prints_store_then_model(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, store_file, _ = _files(tmp_path, STORE_JSON, WRITE_OK)
    assert main(["ids", "--store-json", str(store_file)]) == 0
    assert capsys.readouterr().out == "01STORE 01MODEL\n"


def test_env_writes_both_ids_after_a_clean_load(tmp_path: Path) -> None:
    env, store_file, write_file = _files(tmp_path, STORE_JSON, WRITE_OK)
    args = ["env", "--env-file", str(env), "--store-json", str(store_file)]
    assert main([*args, "--write-json", str(write_file)]) == 0
    text = env.read_text()
    assert "OPENFGA_STORE_ID=01STORE\n" in text
    assert text.endswith("OPENFGA_MODEL_ID=01MODEL\n")
    assert text.count("OPENFGA_STORE_ID=") == 1


@pytest.mark.parametrize(("store", "write"), [(STORE_JSON, WRITE_FAILED), ("{}", WRITE_OK)])
def test_env_leaves_the_file_untouched_on_any_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], store: str, write: str
) -> None:
    env, store_file, write_file = _files(tmp_path, store, write)
    before = env.read_text()
    args = ["env", "--env-file", str(env), "--store-json", str(store_file)]
    assert main([*args, "--write-json", str(write_file)]) == 1
    assert env.read_text() == before
    assert "authz-load" in capsys.readouterr().err


def test_ids_fails_on_a_missing_file(tmp_path: Path) -> None:
    assert main(["ids", "--store-json", str(tmp_path / "absent.json")]) == 1


def test_env_fails_when_the_env_file_is_missing(tmp_path: Path) -> None:
    _, store_file, write_file = _files(tmp_path, STORE_JSON, WRITE_OK)
    absent = tmp_path / "absent.env"
    args = ["env", "--env-file", str(absent), "--store-json", str(store_file)]
    assert main([*args, "--write-json", str(write_file)]) == 1
    assert not absent.exists()


@pytest.mark.parametrize(
    "store",
    [
        {"store": {"id": ""}, "model": {"authorization_model_id": "01MODEL"}},
        {"store": {"id": 7}, "model": {"authorization_model_id": "01MODEL"}},
        {"store": "01STORE", "model": {"authorization_model_id": "01MODEL"}},
        {"store": {"id": "01STORE"}, "model": {"authorization_model_id": None}},
    ],
)
def test_parse_store_create_rejects_empty_or_mistyped_ids(store: dict[str, object]) -> None:
    """covers: AC-11 (a blank or odd ID never reaches .env)"""
    with pytest.raises(FgaLoadError):
        parse_store_create(json.dumps(store))


def test_check_tuple_write_accepts_an_empty_clean_write() -> None:
    assert check_tuple_write(json.dumps({"failed_count": 0, "successful_count": 0})) == 0


def test_check_tuple_write_names_the_failure_count() -> None:
    with pytest.raises(FgaLoadError, match="1 tuples failed"):
        check_tuple_write(WRITE_FAILED)


def test_set_env_on_an_empty_file_appends_both_lines() -> None:
    updated = set_env("", {STORE_VAR: "s", MODEL_VAR: "m"})
    assert updated == "OPENFGA_STORE_ID=s\nOPENFGA_MODEL_ID=m\n"


def test_set_env_adds_a_final_newline_when_missing() -> None:
    assert set_env("A=1", {"B": "2"}) == "A=1\nB=2\n"


def test_set_env_leaves_lookalike_names_alone() -> None:
    text = "OPENFGA_STORE_ID_OLD=x\nMY_OPENFGA_STORE_ID=y\n"
    updated = set_env(text, {STORE_VAR: "new"})
    assert updated == text + "OPENFGA_STORE_ID=new\n"


def test_set_env_matches_a_name_written_with_spaces() -> None:
    updated = set_env("OPENFGA_STORE_ID = old\n", {STORE_VAR: "new"})
    assert updated == "OPENFGA_STORE_ID=new\n"


def test_set_env_keeps_other_values_that_hold_equals_signs() -> None:
    text = "DATABASE_URL=postgres://u:p@h/db?a=b\n"
    assert set_env(text, {STORE_VAR: "s"}) == text + "OPENFGA_STORE_ID=s\n"


def test_env_reports_the_tuple_count_and_both_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env, store_file, write_file = _files(tmp_path, STORE_JSON, WRITE_OK)
    args = ["env", "--env-file", str(env), "--store-json", str(store_file)]
    assert main([*args, "--write-json", str(write_file)]) == 0
    out = capsys.readouterr().out
    assert "3 tuples loaded" in out
    assert "OPENFGA_STORE_ID=01STORE" in out
    assert "OPENFGA_MODEL_ID=01MODEL" in out


def test_env_keeps_unrelated_lines_in_place(tmp_path: Path) -> None:
    env, store_file, write_file = _files(tmp_path, STORE_JSON, WRITE_OK)
    args = ["env", "--env-file", str(env), "--store-json", str(store_file)]
    main([*args, "--write-json", str(write_file)])
    assert env.read_text().splitlines()[0] == "OPENFGA_API_URL=http://localhost:18080"


def test_env_fails_and_leaves_env_when_the_write_output_is_missing(tmp_path: Path) -> None:
    """covers: AC-11 (a tuple write that never ran leaves .env untouched)"""
    env, store_file, _ = _files(tmp_path, STORE_JSON, WRITE_OK)
    before = env.read_text()
    args = ["env", "--env-file", str(env), "--store-json", str(store_file)]
    assert main([*args, "--write-json", str(tmp_path / "absent.json")]) == 1
    assert env.read_text() == before


@pytest.mark.parametrize("argv", [[], ["unknown"], ["env"], ["ids"]])
def test_bad_arguments_exit_non_zero(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        main(argv)
    assert exited.value.code != 0


def test_module_run_exits_1_and_keeps_env_on_a_partial_write(tmp_path: Path) -> None:
    """covers: AC-11 (`python -m tessaro_dataset.fgaload env`, as `just authz-load` calls it)"""
    env, store_file, write_file = _files(tmp_path, STORE_JSON, WRITE_FAILED)
    before = env.read_text()
    command = [sys.executable, "-m", "tessaro_dataset.fgaload", "env", "--env-file", str(env)]
    paths = ["--store-json", str(store_file), "--write-json", str(write_file)]
    # Our own interpreter and temp paths, no outside input.
    result = subprocess.run(  # noqa: S603
        [*command, *paths],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "1 tuples failed" in result.stderr
    assert env.read_text() == before


def test_env_example_lists_both_ids_empty() -> None:
    """covers: AC-11 (.env.example lists OPENFGA_STORE_ID and OPENFGA_MODEL_ID, empty)"""
    lines = (REPO_ROOT / ".env.example").read_text().splitlines()
    assert f"{STORE_VAR}=" in lines
    assert f"{MODEL_VAR}=" in lines
