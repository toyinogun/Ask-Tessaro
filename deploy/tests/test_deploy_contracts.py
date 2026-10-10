"""The contracts deploy/ must keep (spec 0007 AC-3, AC-10, AC-11).

Argo CD syncs this folder from main, so a wrong line here goes live on merge. kubeconform in
`just charts` checks the shapes; these tests check the fence, the sync behaviour and the secrets.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY = REPO_ROOT / "deploy"
NAMESPACES = frozenset(
    (REPO_ROOT / "charts" / "tessaro-baseline" / "ci" / "expected-namespaces.txt")
    .read_text()
    .split()
)
PROOF_NAMESPACES = frozenset({"tessaro-netpol-proof", "tessaro-netpol-proof-b"})
IN_CLUSTER = "https://kubernetes.default.svc"
THIS_REPO = "https://github.com/toyinogun/Ask-Tessaro.git"
FINALIZER = "resources-finalizer.argocd.argoproj.io"
# The upstream chart repositories the fence allows (spec 0008 AC-1), each with the one chart and
# pinned version an Application may install from it.
UPSTREAM_CHARTS = {
    "https://charts.goauthentik.io": ("authentik", "2026.8.3"),
    "ghcr.io/zulip/helm-charts": ("zulip", "2.3.0"),
}

# Kubernetes objects are arbitrary nested mappings, so Any is the honest type here.
Manifest = dict[str, Any]


class _Tolerant(yaml.SafeLoader):
    """SafeLoader that reads custom tags (Authentik blueprints' `!Env X`) as their plain value."""


def _plain(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> object:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)  # type: ignore[arg-type]


_Tolerant.add_multi_constructor("!", _plain)


def docs(path: Path) -> list[Manifest]:
    """Every YAML document in one file (custom tags read as plain values)."""
    loaded = yaml.load_all(path.read_text(), Loader=_Tolerant)
    return [doc for doc in loaded if doc]


def all_docs(folder: Path) -> Iterator[tuple[Path, Manifest]]:
    """Every YAML document under a folder, with the file it came from."""
    for path in sorted(folder.rglob("*.yaml")):
        for doc in docs(path):
            yield path, doc


def sources(app: Manifest) -> list[Manifest]:
    """An Application's sources, whether it has one (`source`) or several (`sources`)."""
    spec = app["spec"]
    return list(spec["sources"]) if "sources" in spec else [spec["source"]]


def child_applications() -> list[Manifest]:
    """The Applications that ask-tessaro syncs from deploy/argocd/."""
    return [doc for _, doc in all_docs(DEPLOY / "argocd") if doc["kind"] == "Application"]


@pytest.fixture(scope="module")
def cluster_repo() -> dict[str, Manifest]:
    """The reference copy of k3sprox-gitops apps/ask-tessaro.yaml, by kind."""
    return {doc["kind"]: doc for doc in docs(DEPLOY / "cluster-repo" / "ask-tessaro.yaml")}


class TestChildApplications:
    """AC-3: every Application in deploy/argocd/ stays inside the tessaro fence."""

    def test_there_is_at_least_the_baseline(self) -> None:
        names = {app["metadata"]["name"] for app in child_applications()}
        assert "tessaro-baseline" in names

    @pytest.mark.parametrize("app", child_applications(), ids=lambda a: a["metadata"]["name"])
    def test_each_sits_in_project_tessaro(self, app: Manifest) -> None:
        assert app["spec"]["project"] == "tessaro"

    @pytest.mark.parametrize("app", child_applications(), ids=lambda a: a["metadata"]["name"])
    def test_each_targets_one_of_the_sixteen_namespaces_in_cluster(self, app: Manifest) -> None:
        destination = app["spec"]["destination"]
        assert destination["server"] == IN_CLUSTER
        assert destination["namespace"] in NAMESPACES

    @pytest.mark.parametrize("app", child_applications(), ids=lambda a: a["metadata"]["name"])
    def test_each_lives_in_argocd_and_has_no_resources_finalizer(self, app: Manifest) -> None:
        assert app["metadata"]["namespace"] == "argocd"
        assert FINALIZER not in app["metadata"].get("finalizers", [])

    @pytest.mark.parametrize("app", child_applications(), ids=lambda a: a["metadata"]["name"])
    def test_each_syncs_server_side(self, app: Manifest) -> None:
        assert "ServerSideApply=true" in app["spec"]["syncPolicy"]["syncOptions"]

    @pytest.mark.parametrize("app", child_applications(), ids=lambda a: a["metadata"]["name"])
    def test_each_from_this_repo_tracks_main(self, app: Manifest) -> None:
        for source in sources(app):
            if source["repoURL"] == THIS_REPO:
                assert source["targetRevision"] == "main"

    @pytest.mark.parametrize("app", child_applications(), ids=lambda a: a["metadata"]["name"])
    def test_each_uses_only_this_repo_or_an_allowed_chart_repo(self, app: Manifest) -> None:
        assert {s["repoURL"] for s in sources(app)} <= {THIS_REPO, *UPSTREAM_CHARTS}

    def test_the_baseline_syncs_first_and_heals_itself(self) -> None:
        [baseline] = [
            a for a in child_applications() if a["metadata"]["name"] == "tessaro-baseline"
        ]
        assert baseline["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"] == "-10"
        assert baseline["spec"]["syncPolicy"]["automated"] == {"prune": True, "selfHeal": True}
        source = baseline["spec"]["source"]
        assert source["path"] == "charts/tessaro-baseline"
        assert source["helm"]["valueFiles"] == ["../../deploy/values/baseline.yaml"]


class TestClusterRepoCopy:
    """AC-3: the fence itself, as committed in k3sprox-gitops."""

    def test_the_project_exists_before_the_application(
        self, cluster_repo: dict[str, Manifest]
    ) -> None:
        project = cluster_repo["AppProject"]
        assert project["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"] == "-1"

    def test_the_project_allows_exactly_the_sixteen_namespaces(
        self, cluster_repo: dict[str, Manifest]
    ) -> None:
        destinations = cluster_repo["AppProject"]["spec"]["destinations"]
        assert {d["server"] for d in destinations} == {IN_CLUSTER}
        assert sorted(d["namespace"] for d in destinations) == sorted(NAMESPACES)

    def test_the_project_allows_only_namespace_at_cluster_scope(
        self, cluster_repo: dict[str, Manifest]
    ) -> None:
        whitelist = cluster_repo["AppProject"]["spec"]["clusterResourceWhitelist"]
        assert whitelist == [{"group": "", "kind": "Namespace"}]

    def test_the_project_accepts_this_repo_and_exactly_the_upstream_charts(
        self, cluster_repo: dict[str, Manifest]
    ) -> None:
        source_repos = cluster_repo["AppProject"]["spec"]["sourceRepos"]
        assert sorted(source_repos) == sorted([THIS_REPO, *UPSTREAM_CHARTS])

    def test_the_project_never_allows_every_source_or_destination(
        self, cluster_repo: dict[str, Manifest]
    ) -> None:
        spec = cluster_repo["AppProject"]["spec"]
        assert "*" not in spec["sourceRepos"]
        assert all(d["namespace"] != "*" for d in spec["destinations"])

    def test_the_root_application_syncs_deploy_argocd_from_main(
        self, cluster_repo: dict[str, Manifest]
    ) -> None:
        app = cluster_repo["Application"]
        assert app["metadata"]["name"] == "ask-tessaro"
        assert app["spec"]["project"] == "default"
        assert app["spec"]["source"] == app["spec"]["source"] | {
            "repoURL": THIS_REPO,
            "path": "deploy/argocd",
            "targetRevision": "main",
        }
        assert app["spec"]["destination"] == {"server": IN_CLUSTER, "namespace": "argocd"}

    def test_the_root_application_heals_but_never_prunes(
        self, cluster_repo: dict[str, Manifest]
    ) -> None:
        policy = cluster_repo["Application"]["spec"]["syncPolicy"]
        assert policy["automated"] == {"prune": False, "selfHeal": True}
        assert "ServerSideApply=true" in policy["syncOptions"]
        assert FINALIZER not in cluster_repo["Application"]["metadata"].get("finalizers", [])


class TestSecrets:
    """AC-10: secrets in git are only strict scope SealedSecrets, filed by namespace."""

    def test_no_plain_secret_is_committed_anywhere_in_deploy(self) -> None:
        plain = [str(path) for path, doc in all_docs(DEPLOY) if doc.get("kind") == "Secret"]
        assert plain == []

    def test_every_file_under_secrets_is_a_sealed_secret(self) -> None:
        for path, doc in all_docs(DEPLOY / "secrets"):
            assert doc["kind"] == "SealedSecret", path

    def test_each_sealed_secret_is_filed_under_its_namespace_and_name(self) -> None:
        for path, doc in all_docs(DEPLOY / "secrets"):
            meta = doc["metadata"]
            assert path.parent.name == meta["namespace"], path
            assert path.name == f"{meta['name']}.sealed.yaml", path

    def test_each_sealed_secret_targets_an_ask_tessaro_or_proof_namespace(self) -> None:
        for path, doc in all_docs(DEPLOY / "secrets"):
            assert doc["metadata"]["namespace"] in NAMESPACES | PROOF_NAMESPACES, path

    def test_each_sealed_secret_has_strict_scope(self) -> None:
        wider = {
            "sealedsecrets.bitnami.com/namespace-wide",
            "sealedsecrets.bitnami.com/cluster-wide",
        }
        for path, doc in all_docs(DEPLOY / "secrets"):
            for meta in (doc["metadata"], doc["spec"]["template"]["metadata"]):
                assert wider.isdisjoint(meta.get("annotations") or {}), path

    def test_the_sealing_certificate_is_a_single_public_certificate(self) -> None:
        pem = (DEPLOY / "secrets" / "sealed-secrets.pem").read_text()
        assert pem.count("-----BEGIN CERTIFICATE-----") == 1
        assert "PRIVATE KEY" not in pem


class TestInternetEgress:
    """AC-11: only the privacy proxy release asks for internet egress."""

    def test_only_the_privacy_proxy_sets_egress_fqdns(self) -> None:
        with_egress = sorted(
            path.name
            for path in (DEPLOY / "values").glob("*.yaml")
            if (yaml.safe_load(path.read_text()) or {}).get("network", {}).get("egressFQDNs")
        )
        assert with_egress == ["privacy-proxy.yaml"]

    def test_no_release_uses_the_removed_egress_cidrs(self) -> None:
        for path in (DEPLOY / "values").glob("*.yaml"):
            values = yaml.safe_load(path.read_text()) or {}
            assert "egressCIDRs" not in values.get("network", {}), path


def platform_applications() -> list[Manifest]:
    """The Applications that install an upstream chart (spec 0008)."""
    return [app for app in child_applications() if any("chart" in s for s in sources(app))]


class TestPlatformApplications:
    """Spec 0008 AC-1 and AC-8: four sources, pinned charts, wave 0, sealed secrets first."""

    @pytest.mark.parametrize("app", platform_applications(), ids=lambda a: a["metadata"]["name"])
    def test_four_sources_chart_values_manifests_and_secrets(self, app: Manifest) -> None:
        name = app["metadata"]["name"]
        namespace = app["spec"]["destination"]["namespace"]
        chart, values, manifests, secrets = sources(app)
        assert (chart["chart"], chart["targetRevision"]) == UPSTREAM_CHARTS[chart["repoURL"]]
        assert chart["helm"]["releaseName"] == name
        assert chart["helm"]["valueFiles"] == [f"$values/deploy/platform/{name}/values.yaml"]
        assert values == {"repoURL": THIS_REPO, "targetRevision": "main", "ref": "values"}
        assert manifests["path"] == f"deploy/platform/{name}/manifests"
        assert secrets["path"] == f"deploy/secrets/{namespace}"
        assert (DEPLOY / "platform" / name / "values.yaml").is_file()

    @pytest.mark.parametrize("app", platform_applications(), ids=lambda a: a["metadata"]["name"])
    def test_wave_zero_and_automated_with_prune(self, app: Manifest) -> None:
        assert app["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"] == "0"
        assert app["spec"]["syncPolicy"]["automated"] == {"prune": True, "selfHeal": True}

    @pytest.mark.parametrize("app", platform_applications(), ids=lambda a: a["metadata"]["name"])
    def test_the_manifests_folder_targets_the_destination(self, app: Manifest) -> None:
        name = app["metadata"]["name"]
        kustomization = docs(DEPLOY / "platform" / name / "manifests" / "kustomization.yaml")[0]
        assert kustomization["namespace"] == app["spec"]["destination"]["namespace"]

    @pytest.mark.parametrize("app", platform_applications(), ids=lambda a: a["metadata"]["name"])
    def test_its_sealed_secrets_sync_before_the_rest(self, app: Manifest) -> None:
        folder = DEPLOY / "secrets" / app["spec"]["destination"]["namespace"]
        for _, secret in all_docs(folder):
            assert secret["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"] == "-2"
