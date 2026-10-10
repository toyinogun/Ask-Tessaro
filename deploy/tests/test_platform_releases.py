"""What each platform Application really applies (spec 0008 AC-2, AC-3, AC-6, AC-9, AC-10, AC-17).

Renders every platform Application the way `just platform` does (the pinned upstream chart with
its values, plus `kustomize build` of its manifests folder), so these tests check what ships, not
the values file alone. Needs network access for `helm template` to pull the pinned charts.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cluster" / "platform_render.py"
KUBE_VERSION = "1.33.0"

# Rendered objects are arbitrary nested mappings, so Any is the honest type here.
Manifest = dict[str, Any]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("platform_render", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


platform_render = _load()
APPS = {
    a.name: a for a in platform_render.platform_apps(REPO_ROOT / "deploy" / "argocd", REPO_ROOT)
}
QUOTAS = {
    ns["name"]: ns["quota"]
    for ns in yaml.safe_load((REPO_ROOT / "deploy" / "values" / "baseline.yaml").read_text())[
        "namespaces"
    ]
}
UNITS = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30}


@pytest.fixture(scope="module")
def rendered() -> dict[str, list[Manifest]]:
    """Every platform Application rendered once for this module."""
    return {name: platform_render.render(app, KUBE_VERSION) for name, app in APPS.items()}


def objects(manifests: list[Manifest], kind: str) -> dict[str, Manifest]:
    """Objects of one kind, by name."""
    return {m["metadata"]["name"]: m for m in manifests if m["kind"] == kind}


def containers(workload: Manifest) -> list[Manifest]:
    """The containers of a Deployment or StatefulSet."""
    return list(workload["spec"]["template"]["spec"]["containers"])


def env_of(container: Manifest) -> dict[str, Any]:
    """A container's env as name to value (or to its valueFrom)."""
    return {e["name"]: e.get("value", e.get("valueFrom")) for e in container.get("env", [])}


def memory(quantity: str) -> int:
    """Bytes in a Kubernetes memory quantity such as 512Mi."""
    match = re.fullmatch(r"(\d+)(Ki|Mi|Gi)?", quantity)
    assert match, quantity
    return int(match[1]) * UNITS.get(match[2] or "", 1)


def requested_memory(manifests: list[Manifest]) -> int:
    """Memory requests of every workload's containers and every CNPG instance."""
    total = 0
    for doc in manifests:
        if doc["kind"] in {"Deployment", "StatefulSet"}:
            replicas = doc["spec"].get("replicas", 1)
            for container in containers(doc):
                request = container.get("resources", {}).get("requests", {}).get("memory", "128Mi")
                total += replicas * memory(request)
        elif doc["kind"] == "Cluster":
            total += doc["spec"]["instances"] * memory(
                doc["spec"]["resources"]["requests"]["memory"]
            )
    return total


@pytest.mark.parametrize("name", sorted(APPS))
def test_memory_requests_fit_the_namespace_quota(
    name: str, rendered: dict[str, list[Manifest]]
) -> None:
    """AC-17: the release's memory requests stay inside its namespace's ResourceQuota."""
    assert requested_memory(rendered[name]) <= memory(QUOTAS[APPS[name].namespace])


@pytest.mark.parametrize("name", sorted(APPS))
def test_only_one_ingress_and_no_load_balancer(
    name: str, rendered: dict[str, list[Manifest]]
) -> None:
    """AC-6: one Ingress of class nginx with a letsencrypt-prod certificate; no LoadBalancer."""
    (ingress,) = objects(rendered[name], "Ingress").values()
    assert ingress["spec"]["ingressClassName"] == "nginx"
    annotations = ingress["metadata"]["annotations"]
    assert annotations["cert-manager.io/cluster-issuer"] == "letsencrypt-prod"
    hosts = {rule["host"] for rule in ingress["spec"]["rules"]}
    assert hosts == {h for tls in ingress["spec"]["tls"] for h in tls["hosts"]}
    services = objects(rendered[name], "Service").values()
    assert all(s["spec"].get("type", "ClusterIP") != "LoadBalancer" for s in services)


@pytest.mark.parametrize("name", sorted(APPS))
def test_no_service_account_or_rbac(name: str, rendered: dict[str, list[Manifest]]) -> None:
    """AC-2: no RBAC of any kind; the pods use the namespace default account without a token."""
    kinds = {m["kind"] for m in rendered[name]}
    assert not kinds & {
        "ServiceAccount",
        "Role",
        "RoleBinding",
        "ClusterRole",
        "ClusterRoleBinding",
    }


@pytest.mark.parametrize("name", sorted(APPS))
def test_one_cnpg_cluster_per_system(name: str, rendered: dict[str, list[Manifest]]) -> None:
    """AC-3: one small CNPG instance on longhorn, PostgreSQL 17, no PDB, wave -1."""
    (cluster,) = objects(rendered[name], "Cluster").values()
    spec = cluster["spec"]
    assert cluster["metadata"]["name"] == f"{name}-db"
    assert cluster["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"] == "-1"
    assert spec["instances"] == 1
    assert spec["enablePDB"] is False
    assert spec["storage"]["storageClass"] == "longhorn"
    assert spec["imageName"].startswith("ghcr.io/cloudnative-pg/postgresql:17.")
    assert spec["bootstrap"]["initdb"] == {"database": name, "owner": name}


class TestAuthentik:
    """The Authentik release specifically."""

    @pytest.fixture
    def manifests(self, rendered: dict[str, list[Manifest]]) -> list[Manifest]:
        return rendered["authentik"]

    def test_server_and_worker_read_the_cnpg_database_over_tls(
        self, manifests: list[Manifest]
    ) -> None:
        """AC-3: host, name, user and password from CNPG; sslmode=require."""
        for deployment in objects(manifests, "Deployment").values():
            env = env_of(containers(deployment)[0])
            assert env["AUTHENTIK_POSTGRESQL__HOST"] == "authentik-db-rw"
            assert env["AUTHENTIK_POSTGRESQL__SSLMODE"] == "require"
            secret_ref = env["AUTHENTIK_POSTGRESQL__PASSWORD"]["secretKeyRef"]
            assert secret_ref == {"name": "authentik-db-app", "key": "password"}

    def test_nothing_calls_out_to_the_internet(self, manifests: list[Manifest]) -> None:
        """AC-10: update check, startup analytics and error reporting off; initials avatars."""
        for deployment in objects(manifests, "Deployment").values():
            env = env_of(containers(deployment)[0])
            assert env["AUTHENTIK_DISABLE_UPDATE_CHECK"] == "true"
            assert env["AUTHENTIK_DISABLE_STARTUP_ANALYTICS"] == "true"
            assert env["AUTHENTIK_ERROR_REPORTING__ENABLED"] == "false"
            assert env["AUTHENTIK_AVATARS"] == "initials"

    def test_secrets_come_only_from_the_sealed_secret(self, manifests: list[Manifest]) -> None:
        """AC-8: the chart renders no Secret; the pods load authentik-secrets with envFrom."""
        assert objects(manifests, "Secret") == {}
        for deployment in objects(manifests, "Deployment").values():
            env_from = containers(deployment)[0]["envFrom"]
            assert {"secretRef": {"name": "authentik-secrets"}} in env_from

    def test_the_blueprints_are_mounted_from_the_generated_config_map(
        self, manifests: list[Manifest]
    ) -> None:
        """AC-9: one ConfigMap with every blueprint file, mounted into the worker."""
        config_map = objects(manifests, "ConfigMap")["authentik-blueprints"]
        blueprints = REPO_ROOT / "deploy/platform/authentik/manifests/blueprints"
        assert set(config_map["data"]) == {p.name for p in blueprints.glob("*.yaml")}
        worker = objects(manifests, "Deployment")["authentik-worker"]
        volumes = worker["spec"]["template"]["spec"]["volumes"]
        assert any(v.get("configMap", {}).get("name") == "authentik-blueprints" for v in volumes)

    def test_the_ingress_serves_auth(self, manifests: list[Manifest]) -> None:
        """AC-6: auth.tessaro.toyintest.org to the server."""
        (ingress,) = objects(manifests, "Ingress").values()
        assert [r["host"] for r in ingress["spec"]["rules"]] == ["auth.tessaro.toyintest.org"]
