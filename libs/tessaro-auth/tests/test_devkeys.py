"""`just keys` writes dev token keys into `.env` once, and they work together (AC-10)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tessaro_auth.devkeys import ensure_dev_keys, main, read_env
from tessaro_auth.issue import DirectoryIdentity, issue_human_token, issue_worker_token
from tessaro_auth.keys import Signer, parse_jwks
from tessaro_auth.verify import verify

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
RID = "0123456789abcdef0123456789abcdef"
TEMPLATE = """# Tokens
TOKEN_SIGNING_KEY=
TOKEN_SIGNING_KID=
TOKEN_TTL_SECONDS=
TOKEN_VERIFY_KEYS=
DEV_ADAPTER_SIGNING_KEY=
DEV_WORKER_SIGNING_KEY=
REDIS_URL=redis://localhost:6379/0
"""


def test_generated_keys_mint_and_verify() -> None:
    updated = ensure_dev_keys(TEMPLATE)
    assert updated is not None
    env = read_env(updated)
    keyset = parse_jwks(env["TOKEN_VERIFY_KEYS"])
    adapter = Signer.from_base64url("adapter-1", env["DEV_ADAPTER_SIGNING_KEY"])
    worker = Signer.from_base64url("worker-1", env["DEV_WORKER_SIGNING_KEY"])
    identity = DirectoryIdentity(
        employee_id="TES-01007", email="a@b", groups=("staff",), is_active=True
    )

    human = issue_human_token(identity, RID, adapter, NOW, 300)
    robot = issue_worker_token("joiner-TES-01042", None, RID, worker, NOW, 300)

    assert verify(human, keyset, NOW).kind.value == "human"
    assert verify(robot, keyset, NOW).kind.value == "workflow_worker"


def test_lines_are_rewritten_in_place_with_single_quoted_json() -> None:
    updated = ensure_dev_keys(TEMPLATE)
    assert updated is not None
    lines = updated.splitlines()
    assert len(lines) == len(TEMPLATE.splitlines())
    verify_line = next(line for line in lines if line.startswith("TOKEN_VERIFY_KEYS="))
    assert verify_line.startswith("TOKEN_VERIFY_KEYS='{")
    assert verify_line.endswith("}'")
    assert "TOKEN_SIGNING_KEY=" in lines
    assert "REDIS_URL=redis://localhost:6379/0" in lines


def test_nothing_changes_when_all_three_are_set() -> None:
    once = ensure_dev_keys(TEMPLATE)
    assert once is not None
    assert ensure_dev_keys(once) is None


@pytest.mark.parametrize("missing", ["DEV_WORKER_SIGNING_KEY", "TOKEN_VERIFY_KEYS"])
def test_any_missing_variable_rewrites_all_three(missing: str) -> None:
    once = ensure_dev_keys(TEMPLATE)
    assert once is not None
    blanked = "\n".join(
        f"{missing}=" if line.startswith(f"{missing}=") else line for line in once.splitlines()
    )
    again = ensure_dev_keys(blanked)
    assert again is not None
    before, after = read_env(once), read_env(again)
    for name in ("DEV_ADAPTER_SIGNING_KEY", "DEV_WORKER_SIGNING_KEY", "TOKEN_VERIFY_KEYS"):
        assert after[name]
        assert after[name] != before[name]


def test_absent_variables_are_appended() -> None:
    updated = ensure_dev_keys("REDIS_URL=x\n# DEV_ADAPTER_SIGNING_KEY=commented\n")
    assert updated is not None
    env = read_env(updated)
    assert env["DEV_ADAPTER_SIGNING_KEY"]
    assert env["DEV_WORKER_SIGNING_KEY"]
    assert "# DEV_ADAPTER_SIGNING_KEY=commented" in updated


def test_read_env_strips_matching_quotes_only() -> None:
    env = read_env("A='x'\nB=\"y\"\nC='z\nnoequals\n# D=1\n")
    assert env == {"A": "x", "B": "y", "C": "'z"}


def test_main_writes_then_leaves_alone(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(TEMPLATE, encoding="utf-8")

    assert main(["--env-file", str(env_file)]) == 0
    first = env_file.read_text(encoding="utf-8")
    assert main(["--env-file", str(env_file)]) == 0

    assert env_file.read_text(encoding="utf-8") == first
    out = capsys.readouterr().out
    assert "wrote fresh dev token keys" in out
    assert "unchanged" in out
    assert read_env(first)["DEV_ADAPTER_SIGNING_KEY"] not in out


def test_main_needs_an_env_file(tmp_path: Path) -> None:
    assert main(["--env-file", str(tmp_path / "missing.env")]) == 1


def test_env_example_lists_every_token_variable_empty() -> None:
    root = next(p for p in Path(__file__).resolve().parents if (p / "uv.lock").exists())
    env = read_env((root / ".env.example").read_text(encoding="utf-8"))
    for name in (
        "TOKEN_SIGNING_KEY",
        "TOKEN_SIGNING_KID",
        "TOKEN_TTL_SECONDS",
        "TOKEN_VERIFY_KEYS",
        "DEV_ADAPTER_SIGNING_KEY",
        "DEV_WORKER_SIGNING_KEY",
    ):
        assert env[name] == "", name
    assert "TOKEN_VERIFY_KEY" not in env
