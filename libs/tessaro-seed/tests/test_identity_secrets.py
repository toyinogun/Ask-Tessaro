"""`just identity-secrets`: fill only the missing values, copy shared ones, never rotate (AC-8)."""

from pathlib import Path

import pytest

from tessaro_seed.envfile import read_env
from tessaro_seed.identity_secrets import (
    ADAPTER_FILE,
    AUTHENTIK_FILE,
    VALUES,
    ZULIP_FILE,
    SecretsConflict,
    ensure,
    main,
)

ENV = "# local settings\nLOG_LEVEL=DEBUG\nTESSARO_DEMO_PASSWORD=\n"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A repo root with only a `.env`."""
    (tmp_path / ".env").write_text(ENV, encoding="utf-8")
    return tmp_path


def env_of(root: Path, rel: str) -> dict[str, str]:
    return read_env((root / rel).read_text(encoding="utf-8"))


def always_ignored(path: Path) -> bool:
    return True


class TestEnsure:
    """ensure(): one pass over every value and every place it lives."""

    def test_a_first_run_writes_every_file_and_value(self, root: Path) -> None:
        ensure(root)
        authentik = env_of(root, AUTHENTIK_FILE)
        zulip = env_of(root, ZULIP_FILE)
        adapter = env_of(root, ADAPTER_FILE)
        env = env_of(root, ".env")
        assert set(authentik) == {
            "AUTHENTIK_SECRET_KEY",
            "AUTHENTIK_BOOTSTRAP_PASSWORD",
            "AUTHENTIK_BOOTSTRAP_TOKEN",
            "TESSARO_ADMIN_PASSWORD",
            "TESSARO_SEED_TOKEN",
            "ZULIP_ADAPTER_AUTHENTIK_TOKEN",
            "ZULIP_OIDC_CLIENT_SECRET",
        }
        assert set(zulip) == {
            "ZULIP_SECRET_KEY",
            "ZULIP_OIDC_CLIENT_SECRET",
            "REDIS_PASSWORD",
            "RABBITMQ_PASSWORD",
        }
        assert set(adapter) == {"AUTHENTIK_URL", "AUTHENTIK_API_TOKEN"}
        assert env["AUTHENTIK_URL"] == "https://auth.tessaro.toyintest.org"
        assert env["ZULIP_SITE"] == "https://chat.tessaro.toyintest.org"
        assert adapter["AUTHENTIK_URL"] == "http://authentik-server.identity.svc.cluster.local"
        assert all(value for value in [*authentik.values(), *zulip.values(), *env.values()])

    def test_shared_values_are_copied_never_generated_twice(self, root: Path) -> None:
        ensure(root)
        authentik = env_of(root, AUTHENTIK_FILE)
        env = env_of(root, ".env")
        oidc = env_of(root, ZULIP_FILE)["ZULIP_OIDC_CLIENT_SECRET"]
        assert oidc == authentik["ZULIP_OIDC_CLIENT_SECRET"]
        assert env["AUTHENTIK_SEED_TOKEN"] == authentik["TESSARO_SEED_TOKEN"]
        assert env["AUTHENTIK_BOOTSTRAP_TOKEN"] == authentik["AUTHENTIK_BOOTSTRAP_TOKEN"]
        adapter_token = authentik["ZULIP_ADAPTER_AUTHENTIK_TOKEN"]
        assert env["ZULIP_ADAPTER_AUTHENTIK_TOKEN"] == adapter_token
        assert env_of(root, ADAPTER_FILE)["AUTHENTIK_API_TOKEN"] == adapter_token

    def test_generated_values_differ_from_each_other(self, root: Path) -> None:
        ensure(root)
        authentik = env_of(root, AUTHENTIK_FILE)
        assert len(set(authentik.values())) == len(authentik)

    def test_a_second_run_changes_nothing(self, root: Path) -> None:
        ensure(root)
        before = {p: p.read_text() for p in root.rglob("*.env")} | {
            root / ".env": (root / ".env").read_text()
        }
        assert ensure(root) == []
        after = {p: p.read_text() for p in before}
        assert after == before

    def test_an_existing_value_is_kept_and_copied(self, root: Path) -> None:
        kept = "kept-token"
        (root / ".env").write_text(ENV + f"AUTHENTIK_SEED_TOKEN={kept}\n", encoding="utf-8")
        ensure(root)
        assert env_of(root, AUTHENTIK_FILE)["TESSARO_SEED_TOKEN"] == kept

    def test_a_missing_value_is_added_without_touching_the_rest(self, root: Path) -> None:
        ensure(root)
        path = root / ZULIP_FILE
        kept = env_of(root, ZULIP_FILE)
        path.write_text(
            "\n".join(f"{k}={v}" for k, v in kept.items() if k != "REDIS_PASSWORD") + "\n"
        )
        changed = ensure(root)
        assert changed == [f"{ZULIP_FILE}: REDIS_PASSWORD"]
        assert {k: v for k, v in env_of(root, ZULIP_FILE).items() if k != "REDIS_PASSWORD"} == {
            k: v for k, v in kept.items() if k != "REDIS_PASSWORD"
        }

    def test_other_lines_in_env_survive(self, root: Path) -> None:
        ensure(root)
        text = (root / ".env").read_text()
        assert text.startswith("# local settings\nLOG_LEVEL=DEBUG\n")

    def test_copies_that_disagree_are_refused_and_nothing_is_written(self, root: Path) -> None:
        ensure(root)
        auth_text = (root / AUTHENTIK_FILE).read_text()
        (root / ".env").write_text(ENV + "AUTHENTIK_SEED_TOKEN=stale\n", encoding="utf-8")
        (root / ZULIP_FILE).unlink()
        with pytest.raises(SecretsConflict, match="TESSARO_SEED_TOKEN"):
            ensure(root)
        assert not (root / ZULIP_FILE).exists()
        assert (root / AUTHENTIK_FILE).read_text() == auth_text

    def test_new_secret_files_are_private(self, root: Path) -> None:
        ensure(root)
        assert (root / AUTHENTIK_FILE).stat().st_mode & 0o777 == 0o600
        assert (root / AUTHENTIK_FILE).parent.stat().st_mode & 0o777 == 0o700


def test_every_value_has_a_primary_place() -> None:
    """The first place of each value is where `just seal` or the operator reads it."""
    names = [value.places[0] for value in VALUES]
    assert len(names) == len(set(names))


class TestMain:
    """main(): refuse unsafe states, report what changed."""

    def test_refuses_when_secrets_are_not_git_ignored(
        self, root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--root", str(root)], ignored=lambda path: False) == 1
        assert "not git ignored" in capsys.readouterr().err
        assert not (root / ".secrets").exists()

    def test_refuses_without_env(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--root", str(tmp_path)], ignored=always_ignored) == 1
        assert "just init" in capsys.readouterr().err

    def test_reports_what_it_wrote_then_unchanged(
        self, root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--root", str(root)], ignored=always_ignored) == 0
        first = capsys.readouterr().out
        assert f"{ZULIP_FILE}: REDIS_PASSWORD" in first
        assert main(["--root", str(root)], ignored=always_ignored) == 0
        assert "unchanged" in capsys.readouterr().out

    def test_a_conflict_exits_1_with_the_reason(
        self, root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["--root", str(root)], ignored=always_ignored)
        (root / ".env").write_text(ENV + "AUTHENTIK_SEED_TOKEN=stale\n", encoding="utf-8")
        assert main(["--root", str(root)], ignored=always_ignored) == 1
        assert "TESSARO_SEED_TOKEN" in capsys.readouterr().err

    def test_the_real_repo_ignores_secrets(self) -> None:
        """This repo's .gitignore covers .secrets/ (checked with git itself)."""
        from tessaro_seed.identity_secrets import git_ignored

        repo = Path(__file__).resolve().parents[3]
        assert git_ignored(repo / AUTHENTIK_FILE)
        assert not git_ignored(repo / "justfile")
