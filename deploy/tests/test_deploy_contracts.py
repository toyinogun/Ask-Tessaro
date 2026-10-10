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

# Kubernetes objects are arbitrary nested mappings, so Any is the honest type here.
Manifest = dict[str, Any]


def docs(path: Path) -> list[Manifest]:
    """Every YAML document in one file."""
    return [doc for doc in yaml.safe_load_all(path.read_text()) if doc]


def all_docs(folder: Path) -> Iterator[tuple[Path, Manifest]]:
    """Every YAML document under a folder, with the file it came from."""
    for path in sorted(folder.rglob("*.yaml")):
        for doc in docs(path):
            yield path, doc


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
        source = app["spec"]["source"]
        if source["repoURL"] == THIS_REPO:
            assert source["targetRevision"] == "main"

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

    def test_the_project_accepts_this_repo_as_a_source(
        self, cluster_repo: dict[str, Manifest]
    ) -> None:
        assert THIS_REPO in cluster_repo["AppProject"]["spec"]["sourceRepos"]

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
