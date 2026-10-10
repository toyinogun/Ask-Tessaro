"""The context guard every live cluster script runs first (spec 0007 AC-6, AC-9).

`require_context` in lib.sh must refuse unless `kubectl config current-context` equals
`TESSARO_KUBE_CONTEXT`, and the live scripts must call it before anything else touches the cluster.
A stub `kubectl` on PATH records every call, so no cluster is needed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

CLUSTER_DIR = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash") or "/bin/bash"

STUB = """#!/usr/bin/env bash
echo "$*" >> "$KUBECTL_LOG"
if [ "$*" = "config current-context" ]; then
    [ -n "${STUB_CONTEXT:-}" ] || exit 1
    echo "$STUB_CONTEXT"
fi
"""


@dataclass(frozen=True)
class Result:
    """One run of a script under the stub kubectl."""

    code: int
    stdout: str
    stderr: str
    kubectl_calls: list[str]


@pytest.fixture
def stub_path(tmp_path: Path) -> Path:
    """A bin folder holding the recording kubectl stub."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "kubectl"
    stub.write_text(STUB)
    stub.chmod(0o755)
    return bin_dir


def run(
    stub_path: Path,
    command: list[str],
    *,
    current: str | None,
    wanted: str | None,
) -> Result:
    """Run a command with the stub first on PATH and the given contexts."""
    log = stub_path.parent / "kubectl.log"
    log.write_text("")
    env = {
        "PATH": f"{stub_path}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(stub_path.parent),
        "KUBECTL_LOG": str(log),
    }
    if current is not None:
        env["STUB_CONTEXT"] = current
    if wanted is not None:
        env["TESSARO_KUBE_CONTEXT"] = wanted
    # Our own bash and scripts with temp paths, no outside input.
    done = subprocess.run(  # noqa: S603
        command, capture_output=True, text=True, check=False, env=env
    )
    return Result(done.returncode, done.stdout, done.stderr, log.read_text().splitlines())


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A repo root holding only lib.sh, so the guard's .env fallback is under test control."""
    root = tmp_path / "repo"
    (root / "scripts" / "cluster").mkdir(parents=True)
    shutil.copy(CLUSTER_DIR / "lib.sh", root / "scripts" / "cluster" / "lib.sh")
    return root


def guard(fake_repo: Path) -> list[str]:
    """Source lib.sh from the fake repo, run the guard, print the pinned context."""
    lib = fake_repo / "scripts" / "cluster" / "lib.sh"
    return [BASH, "-c", f'source "{lib}"; require_context; echo "pinned $KUBE_CONTEXT"']


class TestRequireContext:
    """require_context() in lib.sh."""

    def test_a_matching_context_passes_and_is_pinned(
        self, stub_path: Path, fake_repo: Path
    ) -> None:
        result = run(stub_path, guard(fake_repo), current="lab", wanted="lab")
        assert result.code == 0
        assert result.stdout.strip() == "pinned lab"

    def test_a_different_context_is_refused(self, stub_path: Path, fake_repo: Path) -> None:
        result = run(stub_path, guard(fake_repo), current="prod", wanted="lab")
        assert result.code == 1
        assert "current context is 'prod', expected 'lab'; refusing to run" in result.stderr
        assert "pinned" not in result.stdout

    def test_no_current_context_is_refused(self, stub_path: Path, fake_repo: Path) -> None:
        result = run(stub_path, guard(fake_repo), current=None, wanted="lab")
        assert result.code == 1
        assert "current context is 'none'" in result.stderr

    def test_the_wanted_context_falls_back_to_dot_env(
        self, stub_path: Path, fake_repo: Path
    ) -> None:
        (fake_repo / ".env").write_text("OTHER=1\nTESSARO_KUBE_CONTEXT=lab\n")
        result = run(stub_path, guard(fake_repo), current="lab", wanted=None)
        assert result.code == 0
        assert result.stdout.strip() == "pinned lab"

    def test_the_last_dot_env_line_wins(self, stub_path: Path, fake_repo: Path) -> None:
        (fake_repo / ".env").write_text("TESSARO_KUBE_CONTEXT=old\nTESSARO_KUBE_CONTEXT=lab\n")
        result = run(stub_path, guard(fake_repo), current="lab", wanted=None)
        assert result.code == 0

    def test_the_environment_wins_over_dot_env(self, stub_path: Path, fake_repo: Path) -> None:
        (fake_repo / ".env").write_text("TESSARO_KUBE_CONTEXT=prod\n")
        result = run(stub_path, guard(fake_repo), current="prod", wanted="lab")
        assert result.code == 1
        assert "expected 'lab'" in result.stderr

    def test_no_wanted_context_anywhere_is_refused(self, stub_path: Path, fake_repo: Path) -> None:
        result = run(stub_path, guard(fake_repo), current="lab", wanted=None)
        assert result.code == 1
        assert "TESSARO_KUBE_CONTEXT is not set" in result.stderr

    def test_an_empty_dot_env_value_counts_as_not_set(
        self, stub_path: Path, fake_repo: Path
    ) -> None:
        (fake_repo / ".env").write_text("TESSARO_KUBE_CONTEXT=\n")
        result = run(stub_path, guard(fake_repo), current="", wanted=None)
        assert result.code == 1
        assert "TESSARO_KUBE_CONTEXT is not set" in result.stderr


@pytest.mark.parametrize("script", ["netpol-proof.sh", "ingress-smoke.sh"])
class TestLiveScriptsAbortFirst:
    """The live scripts touch nothing on a wrong context (AC-6: abort before touching anything)."""

    def test_a_wrong_context_exits_before_any_other_kubectl_call(
        self, stub_path: Path, script: str
    ) -> None:
        result = run(stub_path, [BASH, str(CLUSTER_DIR / script)], current="prod", wanted="lab")
        assert result.code == 1
        assert "refusing to run" in result.stderr
        assert result.kubectl_calls == ["config current-context"]
        assert result.stdout == ""
