"""platform_render.py renders and checks the platform Applications (spec 0008 AC-18)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "platform_render.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("platform_render", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses look their module up in sys.modules while the class is built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


platform_render = _load()

# Applications and rendered objects are arbitrary nested mappings, so Any is the honest type here.
Node = Any

THIS_REPO = "https://github.com/toyinogun/Ask-Tessaro.git"
DIGEST = "sha256:" + "a" * 64


def application(
    name: str = "authentik",
    namespace: str = "identity",
    repo: str = "https://charts.goauthentik.io",
    chart: str = "authentik",
    version: str = "2026.8.3",
    values: str = "$values/deploy/platform/authentik/values.yaml",
) -> Node:
    """A four source platform Application shaped like spec 0008 AC-1."""
    return {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Application",
        "metadata": {"name": name, "namespace": "argocd"},
        "spec": {
            "project": "tessaro",
            "destination": {"server": "https://kubernetes.default.svc", "namespace": namespace},
            "sources": [
                {
                    "repoURL": repo,
                    "chart": chart,
                    "targetRevision": version,
                    "helm": {"releaseName": name, "valueFiles": [values]},
                },
                {"repoURL": THIS_REPO, "targetRevision": "main", "ref": "values"},
                {
                    "repoURL": THIS_REPO,
                    "targetRevision": "main",
                    "path": f"deploy/platform/{name}/manifests",
                },
                {
                    "repoURL": THIS_REPO,
                    "targetRevision": "main",
                    "path": f"deploy/secrets/{namespace}",
                },
            ],
        },
    }


def write_apps(root: Path, *apps: Node) -> Path:
    """Write Applications into ``<root>/deploy/argocd`` and return that folder."""
    folder = root / "deploy" / "argocd"
    folder.mkdir(parents=True)
    for app in apps:
        (folder / f"{app['metadata']['name']}.yaml").write_text(yaml.safe_dump(app))
    return folder


def deployment(image: str, namespace: str | None = None, chart: str = "authentik-2026.8.3") -> Node:
    """A Deployment with one container and the chart label helm puts on it."""
    meta: Node = {"name": "server", "labels": {"helm.sh/chart": chart}}
    if namespace is not None:
        meta["namespace"] = namespace
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": meta,
        "spec": {"template": {"spec": {"containers": [{"name": "c", "image": image}]}}},
    }


@pytest.fixture
def app(tmp_path: Path) -> Node:
    """The parsed PlatformApp for the default Application."""
    folder = write_apps(tmp_path, application())
    (found,) = platform_render.platform_apps(folder, tmp_path)
    return found


class TestPlatformApps:
    """platform_apps(): find the Applications that install an upstream chart."""

    def test_a_platform_application_is_read_with_every_source(self, tmp_path: Path) -> None:
        folder = write_apps(tmp_path, application())
        (app,) = platform_render.platform_apps(folder, tmp_path)
        assert app.name == "authentik"
        assert app.namespace == "identity"
        assert app.repo == "https://charts.goauthentik.io"
        assert app.chart == "authentik"
        assert app.version == "2026.8.3"
        assert app.release == "authentik"
        assert app.value_files == (tmp_path / "deploy/platform/authentik/values.yaml",)
        assert app.manifests == tmp_path / "deploy/platform/authentik/manifests"

    def test_an_application_without_a_chart_source_is_skipped(self, tmp_path: Path) -> None:
        baseline = {
            "kind": "Application",
            "metadata": {"name": "tessaro-baseline"},
            "spec": {
                "destination": {"namespace": "assistant"},
                "source": {"repoURL": THIS_REPO, "path": "charts/tessaro-baseline"},
            },
        }
        folder = write_apps(tmp_path, baseline)
        assert platform_render.platform_apps(folder, tmp_path) == ()

    def test_no_applications_means_no_platform_apps(self, tmp_path: Path) -> None:
        folder = write_apps(tmp_path)
        assert platform_render.platform_apps(folder, tmp_path) == ()

    def test_applications_are_sorted_by_name(self, tmp_path: Path) -> None:
        zulip = application(name="zulip", namespace="chat", chart="zulip", values="$values/z.yaml")
        folder = write_apps(tmp_path, zulip, application())
        names = [a.name for a in platform_render.platform_apps(folder, tmp_path)]
        assert names == ["authentik", "zulip"]

    def test_a_value_file_outside_the_values_ref_is_refused(self, tmp_path: Path) -> None:
        folder = write_apps(tmp_path, application(values="values.yaml"))
        with pytest.raises(ValueError, match=r"\$values/"):
            platform_render.platform_apps(folder, tmp_path)

    def test_an_application_without_manifests_has_none(self, tmp_path: Path) -> None:
        bare = application()
        bare["spec"]["sources"] = bare["spec"]["sources"][:2]
        folder = write_apps(tmp_path, bare)
        (app,) = platform_render.platform_apps(folder, tmp_path)
        assert app.manifests is None


class TestHelmArgs:
    """helm_args(): the same chart, version, release and namespace Argo CD renders."""

    def test_an_https_repository_is_passed_with_repo(self, app: Node) -> None:
        args = platform_render.helm_args(app, "1.33.0")
        assert args[:4] == ["helm", "template", "authentik", "authentik"]
        assert args[args.index("--repo") + 1] == "https://charts.goauthentik.io"
        assert args[args.index("--version") + 1] == "2026.8.3"
        assert args[args.index("--namespace") + 1] == "identity"
        assert args[args.index("--kube-version") + 1] == "1.33.0"
        assert args[args.index("--values") + 1].endswith("deploy/platform/authentik/values.yaml")

    def test_an_oci_repository_becomes_an_oci_reference(self, tmp_path: Path) -> None:
        zulip = application(
            name="zulip", namespace="chat", repo="ghcr.io/zulip/helm-charts", chart="zulip"
        )
        (app,) = platform_render.platform_apps(write_apps(tmp_path, zulip), tmp_path)
        args = platform_render.helm_args(app, "1.33.0")
        assert args[3] == "oci://ghcr.io/zulip/helm-charts/zulip"
        assert "--repo" not in args


class TestRender:
    """render(): helm template of the chart plus kustomize build of the manifests folder."""

    def test_both_outputs_are_parsed_and_joined(self, app: Node) -> None:
        calls: list[list[str]] = []

        def run(args: list[str]) -> str:
            calls.append(args)
            kind = "ConfigMap" if args[0] == "helm" else "Service"
            return yaml.safe_dump({"kind": kind}) + "---\n"

        docs = platform_render.render(app, "1.33.0", run=run)
        assert [d["kind"] for d in docs] == ["ConfigMap", "Service"]
        assert calls[1] == ["kustomize", "build", str(app.manifests)]

    def test_no_manifests_folder_means_helm_only(self, tmp_path: Path) -> None:
        bare = application()
        bare["spec"]["sources"] = bare["spec"]["sources"][:2]
        (app,) = platform_render.platform_apps(write_apps(tmp_path, bare), tmp_path)
        calls: list[list[str]] = []

        def run(args: list[str]) -> str:
            calls.append(args)
            return "kind: ConfigMap\n"

        assert len(platform_render.render(app, "1.33.0", run=run)) == 1
        assert [c[0] for c in calls] == ["helm"]

    def test_a_failing_command_raises_with_its_message(self) -> None:
        with pytest.raises(RuntimeError, match="boom"):
            platform_render.run_command(["sh", "-c", "echo boom >&2; exit 3"])

    def test_a_command_returns_its_output(self) -> None:
        assert platform_render.run_command(["echo", "ok"]) == "ok\n"


class TestProblems:
    """problems(): the AC-18 assertions over one rendered Application."""

    def ok(self, **overrides: Any) -> list[Node]:
        return [deployment(f"ghcr.io/goauthentik/server:2026.8.3@{DIGEST}", **overrides)]

    def test_a_clean_render_has_no_problems(self, app: Node) -> None:
        assert platform_render.problems(app, self.ok()) == []

    def test_a_cluster_scoped_kind_is_a_problem(self, app: Node) -> None:
        role = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRole",
            "metadata": {"name": "x"},
        }
        assert any("ClusterRole" in p for p in platform_render.problems(app, [*self.ok(), role]))

    def test_a_cnpg_cluster_is_namespaced_and_allowed(self, app: Node) -> None:
        db = {
            "apiVersion": "postgresql.cnpg.io/v1",
            "kind": "Cluster",
            "metadata": {"name": "authentik-db", "namespace": "identity"},
            "spec": {"imageName": f"ghcr.io/cloudnative-pg/postgresql:17.6@{DIGEST}"},
        }
        assert platform_render.problems(app, [*self.ok(), db]) == []

    def test_a_bitnami_image_is_a_problem(self, app: Node) -> None:
        bad = deployment(f"docker.io/bitnami/redis:8.0@{DIGEST}")
        assert any("bitnami" in p for p in platform_render.problems(app, [*self.ok(), bad]))

    @pytest.mark.parametrize(
        "image",
        ["ghcr.io/goauthentik/server:2026.8.3", f"ghcr.io/goauthentik/server@{DIGEST}", "redis"],
    )
    def test_an_image_without_tag_and_digest_is_a_problem(self, app: Node, image: str) -> None:
        found = platform_render.problems(app, [*self.ok(), deployment(image)])
        assert any("pinned" in p for p in found)

    def test_an_image_from_a_registry_with_a_port_is_read(self, app: Node) -> None:
        image = f"registry.local:5000/team/app:1.0@{DIGEST}"
        assert platform_render.problems(app, [*self.ok(), deployment(image)]) == []

    def test_an_object_in_another_namespace_is_a_problem(self, app: Node) -> None:
        other = deployment(f"ghcr.io/x/y:1@{DIGEST}", namespace="chat")
        found = platform_render.problems(app, [*self.ok(), other])
        assert any("namespace chat" in p for p in found)

    def test_an_object_in_the_destination_namespace_is_fine(self, app: Node) -> None:
        assert platform_render.problems(app, self.ok(namespace="identity")) == []

    @pytest.mark.parametrize("field", ["data", "stringData"])
    def test_a_secret_with_values_is_a_problem(self, app: Node, field: str) -> None:
        secret = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "s"},
            field: {"k": "x"},
        }
        assert any("Secret/s" in p for p in platform_render.problems(app, [*self.ok(), secret]))

    def test_an_empty_secret_is_fine(self, app: Node) -> None:
        secret = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "s"}, "data": {}}
        assert platform_render.problems(app, [*self.ok(), secret]) == []

    def test_a_chart_label_with_another_version_is_a_problem(self, app: Node) -> None:
        stale = self.ok(chart="authentik-2026.8.2")
        assert any("2026.8.3" in p for p in platform_render.problems(app, stale))

    def test_a_render_without_any_chart_label_is_a_problem(self, app: Node) -> None:
        unlabelled = self.ok()
        del unlabelled[0]["metadata"]["labels"]
        assert any("helm.sh/chart" in p for p in platform_render.problems(app, unlabelled))


class TestMain:
    """main(): render every platform Application to --out and fail on any problem."""

    def test_no_platform_applications_succeeds_and_says_so(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_apps(tmp_path)
        code = platform_render.main(["--repo-root", str(tmp_path), "--out", str(tmp_path / "out")])
        assert code == 0
        assert "no platform Applications" in capsys.readouterr().out

    def test_a_clean_application_is_written_to_out(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_apps(tmp_path, application())
        clean = yaml.safe_dump(deployment(f"ghcr.io/goauthentik/server:2026.8.3@{DIGEST}"))
        monkeypatch.setattr(platform_render, "run_command", lambda args: clean)
        out = tmp_path / "out"
        code = platform_render.main(["--repo-root", str(tmp_path), "--out", str(out)])
        assert code == 0
        assert len(list(yaml.safe_load_all((out / "authentik.yaml").read_text()))) == 2

    def test_a_problem_fails_with_the_application_named(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_apps(tmp_path, application())
        unpinned = yaml.safe_dump(deployment("redis"))
        monkeypatch.setattr(platform_render, "run_command", lambda args: unpinned)
        code = platform_render.main(["--repo-root", str(tmp_path), "--out", str(tmp_path / "out")])
        assert code == 1
        assert "authentik:" in capsys.readouterr().err

    def test_a_render_failure_fails_with_the_application_named(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_apps(tmp_path, application())

        def broken(args: list[str]) -> str:
            raise RuntimeError("helm template failed: no chart")

        monkeypatch.setattr(platform_render, "run_command", broken)
        code = platform_render.main(["--repo-root", str(tmp_path), "--out", str(tmp_path / "out")])
        assert code == 1
        assert "authentik: helm template failed" in capsys.readouterr().err


def test_the_real_argocd_folder_parses() -> None:
    """Every Application this repo ships parses, so a malformed source fails the check early."""
    root = SCRIPT.parents[2]
    for app in platform_render.platform_apps(root / "deploy" / "argocd", root):
        assert app.value_files, app.name
