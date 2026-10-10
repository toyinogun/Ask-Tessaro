"""What charts/tessaro-baseline renders from deploy/values/baseline.yaml (spec 0007 AC-4, 5, 12).

`just baseline` already checks the namespace names and that each one gets the four objects; these
tests pin their contents to the spec's *Namespaces* and *Capacity budget* tables.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_VALUES = REPO_ROOT / "deploy" / "values" / "baseline.yaml"

# Spec 0007 *Namespaces* (tier) and *Capacity budget* (ResourceQuota requests.memory).
OWN = {
    "assistant": "2Gi",
    "tools-it": "512Mi",
    "tools-people": "512Mi",
    "tools-finance": "512Mi",
    "tools-workplace": "512Mi",
    "tools-handbook": "512Mi",
    "tools-identity": "512Mi",
    "workflows": "1Gi",
}
SYSTEM = {
    "identity": "2Gi",
    "chat": "3Gi",
    "it": "5Gi",
    "hr-finance": "4Gi",
    "workplace": "1Gi",
    "handbook": "1Gi",
    "platform": "4Gi",
    "observability": "5Gi",
}
QUOTAS = OWN | SYSTEM

# Rendered Kubernetes objects are arbitrary nested mappings, so Any is the honest type here.
Manifest = dict[str, Any]
Render = Callable[..., list[Manifest]]


@pytest.fixture(scope="module")
def rendered(render: Render) -> list[Manifest]:
    """The baseline release exactly as Argo CD renders it."""
    return render("tessaro-baseline", BASELINE_VALUES, release="tessaro-baseline")


def by_kind(manifests: list[Manifest], kind: str) -> dict[str, Manifest]:
    """Objects of one kind, keyed by namespace (by name for Namespaces)."""
    picked = [m for m in manifests if m["kind"] == kind]
    key = "name" if kind == "Namespace" else "namespace"
    return {m["metadata"][key]: m for m in picked}


def mib(quantity: str) -> int:
    """A Mi or Gi quantity in MiB."""
    return int(quantity[:-2]) * (1024 if quantity.endswith("Gi") else 1)


class TestNamespaces:
    """AC-4: labels, Pod Security tier and Argo CD sync options."""

    def test_renders_the_sixteen_namespaces_of_the_spec(self, rendered: list[Manifest]) -> None:
        assert set(by_kind(rendered, "Namespace")) == set(QUOTAS)

    def test_every_namespace_is_labelled_part_of_ask_tessaro(
        self, rendered: list[Manifest]
    ) -> None:
        for name, ns in by_kind(rendered, "Namespace").items():
            assert ns["metadata"]["labels"]["app.kubernetes.io/part-of"] == "ask-tessaro", name

    @pytest.mark.parametrize("name", sorted(OWN))
    def test_own_namespaces_enforce_audit_and_warn_restricted(
        self, rendered: list[Manifest], name: str
    ) -> None:
        labels = by_kind(rendered, "Namespace")[name]["metadata"]["labels"]
        for mode in ("enforce", "audit", "warn"):
            assert labels[f"pod-security.kubernetes.io/{mode}"] == "restricted"
            assert labels[f"pod-security.kubernetes.io/{mode}-version"] == "latest"

    @pytest.mark.parametrize("name", sorted(SYSTEM))
    def test_system_namespaces_enforce_baseline_and_audit_and_warn_restricted(
        self, rendered: list[Manifest], name: str
    ) -> None:
        labels = by_kind(rendered, "Namespace")[name]["metadata"]["labels"]
        assert labels["pod-security.kubernetes.io/enforce"] == "baseline"
        assert labels["pod-security.kubernetes.io/audit"] == "restricted"
        assert labels["pod-security.kubernetes.io/warn"] == "restricted"
        assert labels["pod-security.kubernetes.io/enforce-version"] == "latest"

    def test_argo_cd_never_prunes_or_deletes_a_namespace(self, rendered: list[Manifest]) -> None:
        for name, ns in by_kind(rendered, "Namespace").items():
            options = ns["metadata"]["annotations"]["argocd.argoproj.io/sync-options"]
            assert set(options.split(",")) == {"Prune=false", "Delete=false"}, name


class TestGuards:
    """AC-5: exactly default-deny, allow-dns, LimitRange defaults and ResourceQuota budget."""

    def test_default_deny_selects_every_pod_and_allows_nothing(
        self, rendered: list[Manifest]
    ) -> None:
        policies = [
            m
            for m in rendered
            if m["kind"] == "NetworkPolicy" and m["metadata"]["name"] == "default-deny"
        ]
        assert len(policies) == len(QUOTAS)
        for policy in policies:
            assert policy["spec"] == {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}

    def test_allow_dns_opens_only_kube_dns_on_port_53(self, rendered: list[Manifest]) -> None:
        policies = [
            m
            for m in rendered
            if m["kind"] == "NetworkPolicy" and m["metadata"]["name"] == "allow-dns"
        ]
        assert len(policies) == len(QUOTAS)
        expected_peer = {
            "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
            "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
        }
        for policy in policies:
            spec = policy["spec"]
            assert spec["podSelector"] == {}
            assert spec["policyTypes"] == ["Egress"]
            assert "ingress" not in spec
            assert spec["egress"] == [
                {
                    "to": [expected_peer],
                    "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}],
                }
            ]

    def test_limitrange_sets_requests_and_a_4gi_maximum_but_no_default_limit(
        self, rendered: list[Manifest]
    ) -> None:
        for name, limitrange in by_kind(rendered, "LimitRange").items():
            assert limitrange["metadata"]["name"] == "defaults"
            assert limitrange["spec"]["limits"] == [
                {
                    "type": "Container",
                    "defaultRequest": {"memory": "128Mi", "cpu": "50m"},
                    "max": {"memory": "4Gi"},
                }
            ], name

    @pytest.mark.parametrize(("name", "quota"), sorted(QUOTAS.items()))
    def test_resourcequota_matches_the_capacity_budget(
        self, rendered: list[Manifest], name: str, quota: str
    ) -> None:
        budget = by_kind(rendered, "ResourceQuota")[name]
        assert budget["metadata"]["name"] == "budget"
        assert budget["spec"]["hard"] == {"requests.memory": quota}

    def test_quotas_add_up_to_31_gib(self, rendered: list[Manifest]) -> None:
        total = sum(
            mib(q["spec"]["hard"]["requests.memory"])
            for q in by_kind(rendered, "ResourceQuota").values()
        )
        assert total == 31 * 1024

    def test_nothing_else_is_rendered(self, rendered: list[Manifest]) -> None:
        kinds = {m["kind"] for m in rendered}
        assert kinds == {"Namespace", "NetworkPolicy", "LimitRange", "ResourceQuota"}
        assert len(rendered) == 5 * len(QUOTAS)


class TestValuesSchema:
    """The chart refuses values that would quietly weaken a namespace."""

    def base(self) -> dict[str, Any]:
        values: dict[str, Any] = yaml.safe_load(BASELINE_VALUES.read_text())
        return values

    def test_an_unknown_tier_is_refused(self, render: Render) -> None:
        values = self.base()
        values["namespaces"] = [{"name": "assistant", "tier": "trusted", "quota": "2Gi"}]
        with pytest.raises(ValueError, match="tier"):
            render("tessaro-baseline", values=values)

    def test_a_namespace_without_a_quota_is_refused(self, render: Render) -> None:
        values = self.base()
        values["namespaces"] = [{"name": "assistant", "tier": "own"}]
        with pytest.raises(ValueError, match="quota"):
            render("tessaro-baseline", values=values)

    def test_a_quota_in_bytes_or_cpu_units_is_refused(self, render: Render) -> None:
        values = self.base()
        values["namespaces"] = [{"name": "assistant", "tier": "own", "quota": "2G"}]
        with pytest.raises(ValueError, match="quota"):
            render("tessaro-baseline", values=values)

    def test_an_unknown_key_is_refused(self, render: Render) -> None:
        values = self.base()
        values["namespaces"] = [{"name": "assistant", "tier": "own", "quota": "2Gi", "x": 1}]
        with pytest.raises(ValueError, match="additional properties"):
            render("tessaro-baseline", values=values)

    def test_removing_a_namespace_drops_only_its_own_objects(self, render: Render) -> None:
        values = self.base()
        values["namespaces"] = [n for n in values["namespaces"] if n["name"] != "workplace"]
        manifests = render("tessaro-baseline", values=values)
        namespaces = {m["metadata"].get("namespace", m["metadata"]["name"]) for m in manifests}
        assert namespaces == set(QUOTAS) - {"workplace"}
        assert len(manifests) == 5 * (len(QUOTAS) - 1)
