"""The `tessaro-seed` entry point dispatches to one subcommand."""

from collections.abc import Sequence

import pytest

from tessaro_seed import cli


def test_no_subcommand_is_bad_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == cli.EXIT_USAGE
    assert "identity-secrets" in capsys.readouterr().err


def test_an_unknown_subcommand_is_bad_usage() -> None:
    assert cli.main(["nope"]) == cli.EXIT_USAGE


def test_a_subcommand_gets_the_remaining_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def record(args: Sequence[str]) -> int:
        seen.append(list(args))
        return 0

    monkeypatch.setitem(cli.COMMANDS, "identity-secrets", record)
    assert cli.main(["identity-secrets", "--root", "x"]) == 0
    assert seen == [["--root", "x"]]
