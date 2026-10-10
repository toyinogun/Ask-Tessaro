"""The shared chart's internet egress by host name (spec 0007 AC-11).

`network.egressFQDNs` renders one CiliumNetworkPolicy that pairs a DNS rule (so Cilium's DNS proxy
learns the allowed addresses) with one `toFQDNs` rule per name. An empty list renders nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_VALUES = REPO_ROOT / "charts" / "tessaro-service" / "ci" / "test-values.yaml"

# Rendered Kubernetes objects are arbitrary nested mappings, so Any is the honest type here.
Manifest = dict[str, Any]
Render = Callable[..., list[Manifest]]

DNS_RULE = {
    "toEndpoints": [
        {
            "matchLabels": {
                "k8s:io.kubernetes.pod.namespace": "kube-system",
                "k8s:k8s-app": "kube-dns",
            }
        }
    ],
    "toPorts": [
        {
            "ports": [{"port": "53", "protocol": "UDP"}, {"port": "53", "protocol": "TCP"}],
            "rules": {"dns": [{"matchPattern": "*"}]},
        }
    ],
}


def network(**overrides: Any) -> dict[str, Any]:
    """The test release's network block with overrides applied."""
    values: dict[str, Any] = yaml.safe_load(TEST_VALUES.read_text())
    return {"network": {**values["network"], **overrides}}


def fqdn_policies(manifests: list[Manifest]) -> list[Manifest]:
    """Every CiliumNetworkPolicy in a render."""
    return [m for m in manifests if m["kind"] == "CiliumNetworkPolicy"]


class TestRendering:
    """What the chart renders for a given egressFQDNs list."""

    def test_an_empty_list_renders_no_cilium_policy(self, render: Render) -> None:
        manifests = render("tessaro-service", TEST_VALUES, values=network(egressFQDNs=[]))
        assert fqdn_policies(manifests) == []

    def test_one_name_renders_one_policy_named_after_the_release(self, render: Render) -> None:
        manifests = render(
            "tessaro-service",
            TEST_VALUES,
            release="proxy",
            values=network(egressFQDNs=[{"name": "api.deepseek.com"}]),
        )
        [policy] = fqdn_policies(manifests)
        assert policy["apiVersion"] == "cilium.io/v2"
        assert policy["metadata"]["name"] == "proxy-egress-fqdn"

    def test_the_policy_selects_only_the_release_pods(self, render: Render) -> None:
        manifests = render(
            "tessaro-service",
            TEST_VALUES,
            release="proxy",
            values=network(egressFQDNs=[{"name": "api.deepseek.com"}]),
        )
        [policy] = fqdn_policies(manifests)
        assert policy["spec"]["endpointSelector"] == {
            "matchLabels": {"app.kubernetes.io/name": "proxy"}
        }

    def test_the_policy_lives_in_the_release_namespace(self, render: Render) -> None:
        values = network(egressFQDNs=[{"name": "api.deepseek.com"}]) | {"namespace": "assistant"}
        [policy] = fqdn_policies(render("tessaro-service", TEST_VALUES, values=values))
        assert policy["metadata"]["namespace"] == "assistant"

    def test_the_dns_rule_comes_first_and_lets_cilium_see_every_lookup(
        self, render: Render
    ) -> None:
        manifests = render(
            "tessaro-service", TEST_VALUES, values=network(egressFQDNs=[{"name": "a.example.com"}])
        )
        [policy] = fqdn_policies(manifests)
        assert policy["spec"]["egress"][0] == DNS_RULE

    def test_a_name_without_ports_opens_tcp_443_only(self, render: Render) -> None:
        manifests = render(
            "tessaro-service", TEST_VALUES, values=network(egressFQDNs=[{"name": "a.example.com"}])
        )
        [policy] = fqdn_policies(manifests)
        assert policy["spec"]["egress"][1] == {
            "toFQDNs": [{"matchName": "a.example.com"}],
            "toPorts": [{"ports": [{"port": "443", "protocol": "TCP"}]}],
        }

    def test_explicit_ports_replace_the_default(self, render: Render) -> None:
        entry = {"name": "a.example.com", "ports": [443, 8443]}
        [policy] = fqdn_policies(
            render("tessaro-service", TEST_VALUES, values=network(egressFQDNs=[entry]))
        )
        ports = policy["spec"]["egress"][1]["toPorts"][0]["ports"]
        assert ports == [{"port": "443", "protocol": "TCP"}, {"port": "8443", "protocol": "TCP"}]

    def test_each_name_gets_its_own_rule_after_the_dns_rule(self, render: Render) -> None:
        names = [{"name": "a.example.com"}, {"name": "b.example.com"}]
        [policy] = fqdn_policies(
            render("tessaro-service", TEST_VALUES, values=network(egressFQDNs=names))
        )
        egress = policy["spec"]["egress"]
        assert len(egress) == 3
        assert [rule["toFQDNs"] for rule in egress[1:]] == [
            [{"matchName": "a.example.com"}],
            [{"matchName": "b.example.com"}],
        ]

    def test_the_plain_network_policy_never_opens_the_internet(self, render: Render) -> None:
        manifests = render(
            "tessaro-service", TEST_VALUES, values=network(egressFQDNs=[{"name": "a.example.com"}])
        )
        [policy] = [m for m in manifests if m["kind"] == "NetworkPolicy"]
        for rule in policy["spec"]["egress"]:
            for peer in rule["to"]:
                assert "ipBlock" not in peer


class TestValuesSchema:
    """The chart refuses egress values outside the AC-11 shape."""

    def test_the_removed_egress_cidrs_key_is_refused(self, render: Render) -> None:
        with pytest.raises(ValueError, match="egressCIDRs"):
            render("tessaro-service", TEST_VALUES, values=network(egressCIDRs=["0.0.0.0/0"]))

    def test_an_entry_without_a_name_is_refused(self, render: Render) -> None:
        with pytest.raises(ValueError, match="name"):
            render("tessaro-service", TEST_VALUES, values=network(egressFQDNs=[{"ports": [443]}]))

    @pytest.mark.parametrize("name", ["*.example.com", "localhost", "https://a.example.com"])
    def test_a_wildcard_bare_or_url_name_is_refused(self, render: Render, name: str) -> None:
        with pytest.raises(ValueError, match="helm template failed"):
            render("tessaro-service", TEST_VALUES, values=network(egressFQDNs=[{"name": name}]))


class TestPrivacyProxyRelease:
    """deploy/values/privacy-proxy.yaml is the one release with internet egress."""

    def test_the_privacy_proxy_may_reach_only_deepseek_on_443(self, render: Render) -> None:
        values = REPO_ROOT / "deploy" / "values" / "privacy-proxy.yaml"
        [policy] = fqdn_policies(render("tessaro-service", values, release="privacy-proxy"))
        assert policy["metadata"] == policy["metadata"] | {
            "name": "privacy-proxy-egress-fqdn",
            "namespace": "assistant",
        }
        assert policy["spec"]["egress"] == [
            DNS_RULE,
            {
                "toFQDNs": [{"matchName": "api.deepseek.com"}],
                "toPorts": [{"ports": [{"port": "443", "protocol": "TCP"}]}],
            },
        ]
