# charts

## Overview

The two local Helm charts and the vendored CRD schemas that let `just check` validate them offline. `tessaro-service` is the one chart every Ask Tessaro service is released with; `tessaro-baseline` lays down the 16 namespaces and their guards. Release values live in `deploy/values/`, never here.

## Key files

| File | Owns |
|---|---|
| `tessaro-service/values.yaml` | Defaults for every service: port 8080, probes, restricted security contexts, the optional OPA sidecar, the `network` block |
| `tessaro-service/values.schema.json` | The validated shape of release values, including `network.ingress[]`, `network.egress[]`, `network.egressFQDNs[]` |
| `tessaro-service/templates/networkpolicy.yaml` | Per pod default deny plus the allows listed in `network`; DNS when `network.dns` is true |
| `tessaro-service/templates/ciliumnetworkpolicy.yaml` | `<release>-egress-fqdn`, rendered only when `network.egressFQDNs` is not empty |
| `tessaro-service/ci/test-values.yaml` | Values `just charts` lints and renders on top of every release file |
| `tessaro-baseline/templates/` | Per namespace: Namespace, NetworkPolicy `default-deny` and `allow-dns`, LimitRange `defaults`, ResourceQuota `budget` |
| `tessaro-baseline/ci/expected-namespaces.txt` | The exact 16 names the baseline must render; `seal.sh` reads it too |
| `schemas/` | JSON schemas for CiliumNetworkPolicy, SealedSecret, Application and AppProject, generated from the cluster's CRDs |

## Commands

```bash
just charts      # lint and kubeconform both charts, every deploy/values file, deploy/argocd, deploy/cluster-repo, deploy/secrets
just baseline    # the baseline alone (part of `just charts`)
just schemas     # regenerate schemas/ from the live CRDs after a Cilium, Sealed Secrets or Argo CD upgrade, then update schemas/README.md
helm template privacy-proxy charts/tessaro-service -f deploy/values/privacy-proxy.yaml   # see what one release renders
```

## Conventions

- `tessaro-service` never creates a Namespace; `namespace` is a required value and the baseline owns the Namespace objects.
- Internet egress only through `network.egressFQDNs`, and only the privacy proxy sets it. Its CiliumNetworkPolicy must keep the DNS rule (`rules.dns: matchPattern "*"`) beside the `toFQDNs` rule: Cilium learns the allowed addresses only from DNS answers it sees.
- Our own namespaces enforce Pod Security `restricted`, so service pods keep `runAsNonRoot`, all capabilities dropped, `seccompProfile: RuntimeDefault` and a read only root filesystem.
- Baseline tiers: `own` enforces `restricted`; `system` enforces `baseline` and audits and warns `restricted`. Every Namespace carries `Prune=false,Delete=false`.
- LimitRange sets a default request and a 4Gi maximum but no default limit and no CPU limit. A container that needs more than 4Gi gets its namespace's maximum raised in `deploy/values/baseline.yaml` first.
- Root `AGENTS.md` rules apply.

## Gotchas

- Adding or removing a namespace means editing `deploy/values/baseline.yaml` and `tessaro-baseline/ci/expected-namespaces.txt` together, or `just baseline` fails. Removing one on the cluster drops its guards but leaves the namespace.
- `just check` validates against Kubernetes `kube_version` in the `justfile` (1.33.0), older than the cluster (1.36.5).
- A CRD kind with no schema in `schemas/` fails `kubeconform -strict`; add the CRD to `just schemas` before using a new kind.

## Related specs

- [0001 stack and architecture](../docs/specs/0001-stack-architecture/index.md): the shared service chart
- [0007 cluster baseline](../docs/specs/0007-cluster-baseline/index.md): the baseline chart, `egressFQDNs`, the vendored schemas

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
