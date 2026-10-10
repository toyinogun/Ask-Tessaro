# 0007. Cluster baseline: reuse the existing platform, grow the workers, fence Ask Tessaro in

**Date**: 2026-10-10
**Status**: In Progress

## Summary

The k3s cluster already runs most of what Ask Tessaro needs: Cilium (the network layer, which enforces NetworkPolicies and can allow a hostname), ingress-nginx behind MetalLB, cert-manager with Let's Encrypt over Cloudflare DNS, Longhorn storage, the CNPG Postgres operator, Argo CD and Sealed Secrets. So the baseline reuses all of it instead of adding new tools. The real gap is memory, and the Proxmox hosts have little to spare, so the runner VM on `pve1` shrinks from 8 to 4 GiB and the three workers grow from 8 to 12 GiB (through the Terraform that manages them) before anything is installed. Then one Argo CD Application from this repo lays down the 16 Ask Tessaro namespaces, each with default deny, a DNS allow, Pod Security labels and resource guards, all inside an Argo CD project that cannot touch anything else. The UIs stay private (LAN and tailnet) under `*.tessaro.toyintest.org` with real certificates.

## Requirements

**User stories**:
- As the engineer, I want a written environment report before anything is installed, so that every later install (features 9 to 16) builds on facts, not guesses (PRD 14.2 step 0).
- As the security reviewer, I want proof that NetworkPolicies are enforced and that only the privacy proxy can reach the internet, so that the team isolation story (PRD 14.4) holds.
- As the engineer, I want Ask Tessaro fenced off from the other workloads on this shared cluster, so that a bad values file can never touch n8n, solutio, the deployer apps or the cluster's own tooling.
- As the engineer, I want enough memory for the full PRD stack, so that no system has to be cut for capacity.

**Acceptance criteria** (the contract, each criterion is IDed and independently checkable):

- **AC-1**: `docs/environment-report.md` exists and covers every area in PRD 14.2 step 0 (cluster, workloads, ingress, load balancing, storage, networking, certificates and DNS, images, tooling, outbound access), each with what was found and the date it was checked. It ends with a `## Decisions` section that names the ingress class, the storage class per workload kind, the hostname scheme, the certificate approach, the internet egress mechanism, the capacity plan and the gaps still open, and it embeds the output of `just netpol-proof` (AC-6) and `just ingress-smoke` (AC-9).
- **AC-2**: Before any Ask Tessaro system (feature 9 onward) is installed: first `gh-runner-1` (VMID 300 on `pve1`) is shrunk from 8 to 4 GiB and has run at least one job since; then each of the three workers (`k3sprox-wkr-pve1-0`, `k3sprox-wkr-pve2-0`, `k3sprox-wkr-pve2-1`) has 12 GiB of memory, set as `memory_mb = 12288` in `~/k3sprox/terraform-proxmox-k3s/examples/homelab/main.tf` and applied one worker at a time, with a full `terraform plan` showing no changes at the end; runs k3s with `system-reserved=memory=1Gi` from a Terraform managed drop-in `/etc/rancher/k3s/config.yaml.d/60-system-reserved.yaml` (key `kubelet-arg+`, workers only), visible together with the image GC thresholds in each node's kubelet `configz` (`kubectl get --raw /api/v1/nodes/<node>/proxy/configz`); and reports at least 10.4 GiB of allocatable memory per worker in `kubectl get nodes`. Measured 30 minutes after every Longhorn volume is `healthy` again: each Proxmox host shows at least 3 GiB `available` in `free -m`, `pve2` uses no swap, and `pve1` uses no more swap than its 1.3 GiB baseline. The report's capacity table compares the per namespace budget (see *Capacity budget*) with the new allocatable total and with the other tenants' memory requests.
- **AC-3**: In `toyinogun/k3sprox-gitops`, an AppProject `tessaro` and an Application `ask-tessaro` exist (see *GitOps layout*). `ask-tessaro` is `Synced` and `Healthy` (`kubectl -n argocd get application ask-tessaro tessaro-baseline`), pointing at this repo's `deploy/argocd/` on `main`. The AppProject carries sync wave `-1` so it exists before the Application. A reference copy of both manifests lives in `deploy/cluster-repo/ask-tessaro.yaml` (not synced by anything) and must match what is committed to `k3sprox-gitops`. An Application in project `tessaro` whose destination namespace is outside the 16 namespaces (for example `default`) fails with Argo CD's "not permitted in project" error, and one that renders any cluster scoped kind other than `Namespace` fails the same way.
- **AC-4**: All 16 namespaces in *Namespaces* exist, each labelled `app.kubernetes.io/part-of: ask-tessaro` and with the Pod Security labels of its tier: `own` namespaces enforce, audit and warn `restricted`; `system` namespaces enforce `baseline` and audit and warn `restricted`; all at `enforce-version: latest`. Each Namespace object carries the Argo CD sync options `Prune=false` and `Delete=false`, so deleting or pruning an Application never deletes a namespace.
- **AC-5**: Every one of the 16 namespaces contains exactly these baseline objects: NetworkPolicy `default-deny` (empty pod selector, `policyTypes: [Ingress, Egress]`, no rules), NetworkPolicy `allow-dns` (all pods may send to pods labelled `k8s-app: kube-dns` in `kube-system` on UDP and TCP 53), a LimitRange `defaults` and a ResourceQuota `budget`, with the values in *Capacity budget*.
- **AC-6**: `just netpol-proof` runs against the live cluster and exits 0 only if every step below gives the expected result, printing one line per step. It aborts before touching anything unless `kubectl config current-context` equals `TESSARO_KUBE_CONTEXT`. It creates a namespace `tessaro-netpol-proof` (labelled like a `restricted` tier namespace) with a `server` pod (`nginxinc/nginx-unprivileged`, port 8080, with a Service) and a `client` pod (`curlimages/curl`, uid 100, sleeping), both pinned by version and digest and meeting `restricted` (`runAsNonRoot`, all capabilities dropped, `seccompProfile: RuntimeDefault`, no privilege escalation). A probe is `curl -sS -m 5 -o /dev/null -w '%{http_code}' <url>`: "reachable" means it printed any HTTP status (a 401 or 404 from DeepSeek counts), "blocked" means a connect timeout or refusal. After each policy change the script polls every 2 seconds for up to 30 seconds until the expected state appears, then requires 3 matching probes in a row. Steps: (a) with no policy, the client reaches the server (HTTP 200); (b) after the baseline chart's `default-deny` and `allow-dns` (rendered with `helm template`), the server is blocked and `nslookup kubernetes.default.svc.cluster.local` and `nslookup example.com` both still resolve (fully qualified, because busybox `nslookup` ignores the resolv.conf search list); (c) after applying the CiliumNetworkPolicy that `helm template charts/tessaro-service` renders from a fixture values file with `egressFQDNs: [{name: api.deepseek.com}]` and a pod label matching the client, `https://api.deepseek.com` is reachable, `example.com` still resolves, and `https://example.com` is blocked; (d) a SealedSecret sealed for `tessaro-netpol-proof` with the committed certificate (AC-10) becomes a Secret with the expected key, and the same sealed file applied under a second namespace `tessaro-netpol-proof-b` produces no Secret (strict scope). An `EXIT` trap deletes both namespaces, success or failure. Any unexpected result is a blocking finding (PRD 14.2).
- **AC-7**: Outbound access is recorded: in step (a) of AC-6, before any policy, the client also reaches `https://api.deepseek.com` and `https://ghcr.io`, so the report shows that pods have internet egress and that default deny is what removes it. Image pulls from GHCR by the nodes are recorded from the running `ghcr.io/cloudnative-pg/cloudnative-pg` pod.
- **AC-8**: Pod Security is proven with server side dry runs: a pod running as root with no `securityContext` is rejected in `assistant` (restricted) and admitted with a warning in `chat` (baseline). The two commands and their output go in the report.
- **AC-9**: A wildcard DNS record `*.tessaro.toyintest.org` (A, `172.16.70.40`, not proxied by Cloudflare) resolves from a LAN device and from a tailnet device away from the LAN. `just ingress-smoke` (same context guard as AC-6) deploys an unprivileged nginx and an Ingress for `smoke.tessaro.toyintest.org` (class `nginx`) in a temporary namespace `tessaro-ingress-smoke` that has `default-deny`, `allow-dns` and the ingress controller allow from *Network conventions*. By default it uses `cert-manager.io/cluster-issuer: letsencrypt-staging` and checks only that the Certificate is Ready within 5 minutes and the URL returns 200 with `curl -k`; `just ingress-smoke --prod` uses `letsencrypt-prod` and also checks the certificate is trusted by the system store, and is run once for the report (Let's Encrypt allows 5 identical certificates per week). DNS01 runs in `cert-manager`, so the namespace needs no solver allow. It deletes the namespace on exit. The tailnet check (the same URL from a tailnet device away from the LAN) is a manual step whose result is written into the report.
- **AC-10**: `deploy/secrets/sealed-secrets.pem` holds the Sealed Secrets controller's public certificate (fetched from `sealed-secrets-controller` in `kube-system`). `just seal <namespace> <name> <env-file>` writes `deploy/secrets/<namespace>/<name>.sealed.yaml` with `strict` scope (bound to that namespace and that exact Secret name, so a rename means resealing), using only the committed certificate (no cluster access needed). The env file is dotenv style: one `KEY=value` per line, `#` comments and blank lines ignored, optional matching single or double quotes stripped, no multiline values; a duplicate key, a key that is not `[A-Z_][A-Z0-9_]*` or an empty value is an error. It refuses a namespace outside the 16 namespaces plus the two proof namespaces; refuses an env file inside the repo unless `git check-ignore -q` says it is ignored; fails if `kubeseal` is missing or not version 0.40.x; and writes through a temporary file renamed on success, so a failed run leaves nothing behind.
- **AC-11**: The shared chart `charts/tessaro-service` drops `network.egressCIDRs` and gains `network.egressFQDNs[]` (each `{name, ports}`; `ports` default `[443]`). When the list is not empty, the chart renders one CiliumNetworkPolicy (`cilium.io/v2`) `<release>-egress-fqdn` with `endpointSelector.matchLabels` `app.kubernetes.io/name: <release>` and two egress rules: `toEndpoints` `{k8s:io.kubernetes.pod.namespace: kube-system, k8s:k8s-app: kube-dns}` on port 53 UDP and TCP with `rules.dns: [{matchPattern: "*"}]` (so Cilium's DNS proxy sees every lookup and learns the allowed addresses), and `toFQDNs: [{matchName: <name>}]` for each name on its ports over TCP. When the list is empty, no CiliumNetworkPolicy is rendered. `deploy/values/privacy-proxy.yaml` sets `egressFQDNs: [{name: api.deepseek.com}]`; no other values file sets it. `just check` validates every rendered or committed CiliumNetworkPolicy, SealedSecret, Argo CD Application and AppProject (including `deploy/argocd/`, `deploy/secrets/` and `deploy/cluster-repo/`) against JSON schemas vendored in `charts/schemas/` (generated from the CRDs of Cilium 1.20.2, Sealed Secrets 0.40.0 and the cluster's Argo CD version), so the check needs no network.
- **AC-12**: `charts/tessaro-baseline` renders everything in AC-4 and AC-5 from one values file, `deploy/values/baseline.yaml`, and `just check` lints and validates it like the service chart. Removing a namespace from the values file removes its LimitRange, ResourceQuota and NetworkPolicies on the next sync but leaves the namespace itself (AC-4); because that silently drops isolation, `just check` fails unless the baseline renders exactly the 16 namespace names in *Namespaces*.

## Decision

**Chosen option**: Option 1: Reuse the cluster's existing platform, grow the workers, and fence Ask Tessaro in with its own Argo CD project.

Build the baseline on what the cluster already runs (Cilium, ingress-nginx, MetalLB, cert-manager, Longhorn, CNPG, Argo CD, Sealed Secrets), shrink the runner VM on `pve1` and raise the three workers to 12 GiB, and deliver namespaces and guards from this repo through one Argo CD Application in a fenced project.

**Implementation skills**: `helm-chart-scaffolding` (`wshobson/agents`, `.claude/skills/helm-chart-scaffolding/`) · `gitops-workflow` (`wshobson/agents`, `.claude/skills/gitops-workflow/`)

## Rationale

Reasoning, options and the full cluster inventory: see [rationale.md](rationale.md).

## Proposed stack

| Layer | Choice | Reason |
|---|---|---|
| Capacity | Shrink `gh-runner-1` on `pve1` from 8 to 4 GiB, then grow each worker VM from 8 to 12 GiB through `terraform-proxmox-k3s`, one node at a time | The hosts set the ceiling: `pve1` is full (and swapping) and `pve2` has about 12.5 GiB free. 12 GiB workers keep `pve1` at today's total and leave at least 3 GiB free on each host. With 1 GiB reserved per worker that gives about 32 GiB allocatable, against about 4.5 GiB of memory requests from the other tenants and 21 GiB for the PRD stack at rest |
| Ingress | Existing ingress-nginx, class `nginx`, on MetalLB `172.16.70.40` | Already serving every other tenant; no new controller to run |
| Exposure | Private: LAN, and tailnet through the existing route to `172.16.70.0/24` | Fake data, demo only; nothing public means no public attack surface on the sign in pages |
| Hostnames | `<system>.tessaro.toyintest.org` (see *Hostnames*) | Own wildcard on the zone the cluster already proves through Cloudflare DNS; no clash with `*.deploy.toyintest.org` |
| DNS | One public record `*.tessaro.toyintest.org` A `172.16.70.40`, not proxied | Works on any device that routes to the LAN, with no resolver to run |
| Certificates | One certificate per Ingress from the existing ClusterIssuer `letsencrypt-prod` (DNS01 through Cloudflare) | About a dozen names, no wildcard key copied across namespaces, no extra controller |
| Network policy engine | Cilium 1.20.2 (already the CNI, `enable-k8s-networkpolicy: true`) | Enforces plain NetworkPolicy and adds hostname rules (`toFQDNs`) |
| Internet egress | Only the privacy proxy, through a CiliumNetworkPolicy `toFQDNs: api.deepseek.com` rendered by the shared chart | A plain NetworkPolicy cannot allow a hostname, and DeepSeek's addresses change; this settles spec 0001's open `egressCIDRs` question |
| Storage | `longhorn` (3 replicas) for databases and Redis with AOF; `longhorn-1r` for data you can rebuild (Elasticsearch, ClickHouse, Loki, Langfuse blob store, RabbitMQ) | Durability where it matters, about half the disk where it does not |
| Postgres | One small single instance CNPG cluster in each system's namespace | The operator already runs; isolation matches default deny and per namespace secrets |
| Secrets | Existing Sealed Secrets controller (0.40.0, `kube-system`); sealed files in `deploy/secrets/<namespace>/` | Encrypted in git, decrypted only in the cluster (PRD 14.3's intent) with no new plugin in the shared Argo CD; replaces KSOPS from spec 0001 |
| GitOps | Existing Argo CD; AppProject `tessaro` and Application `ask-tessaro` live in `k3sprox-gitops`, everything else in this repo's `deploy/argocd/` | The cluster repo stays the one entry point and owns the fence, so this repo cannot widen its own permissions |
| Baseline delivery | A small local Helm chart `charts/tessaro-baseline`, synced first (wave `-10`) | 16 namespaces times 4 objects from one values file, checked by the same `helm lint` and kubeconform step as the service chart |
| Pod Security | `restricted` for our own namespaces, `baseline` (warn `restricted`) for off the shelf systems | Our chart already meets restricted; Zulip, Zammad and Frappe charts often run as root |
| Resource guards | LimitRange default memory request, a 4Gi per container maximum (which Kubernetes also uses as the default limit), and a ResourceQuota on `requests.memory` per namespace; no CPU limits; kubelet `system-reserved=memory=1Gi` on the workers | Every container gets requests even if a chart forgets them (PRD 14.2 resources); CPU limits only cause throttling on a cluster this size |
| Image registry | GHCR for our images (public repo, nodes pull without credentials) | Confirmed: nodes already pull `ghcr.io/cloudnative-pg/cloudnative-pg` |

## Feature design

### Namespaces

| Namespace | Tier | Holds (PRD 14.2, spec 0001) |
|---|---|---|
| `identity` | system | Authentik |
| `chat` | system | Zulip |
| `it` | system | Zammad, Snipe-IT |
| `hr-finance` | system | Frappe HR with ERPNext |
| `workplace` | system | Seatsurfing |
| `handbook` | system | BookStack |
| `platform` | system | OpenFGA, Temporal (server, UI), Presidio analyzer |
| `observability` | system | Langfuse, Grafana, Loki |
| `assistant` | own | zulip-adapter, master-agent, privacy-proxy, tool-gateway with OPA sidecar, Redis |
| `tools-it`, `tools-people`, `tools-finance`, `tools-workplace`, `tools-handbook`, `tools-identity` | own | one tool server each |
| `workflows` | own | jml-intake, jml-worker |

Redis sits in `assistant`, not `platform` (spec 0001). The Redis and Presidio images are third party, but Redis runs in an `own` namespace, so its manifests must meet `restricted` (the official image runs fine as a non root user with a read only root filesystem and a writable data volume).

### Capacity budget

Estimates at rest, from each system's documented minimums sized down for about 30 users. Quota is a ceiling on the sum of memory requests, not a target.

| Namespace | Expected requests (memory) | ResourceQuota `requests.memory` | Heavy pods (spread across nodes) |
|---|---|---|---|
| `identity` | 1.2 GiB | 2Gi | |
| `chat` | 2.5 GiB | 3Gi | Zulip |
| `it` | 4.1 GiB | 5Gi | Elasticsearch |
| `hr-finance` | 2.8 GiB | 4Gi | MariaDB |
| `workplace` | 0.4 GiB | 1Gi | |
| `handbook` | 0.5 GiB | 1Gi | |
| `platform` | 3.0 GiB | 4Gi | Presidio analyzer |
| `observability` | 4.3 GiB | 5Gi | ClickHouse |
| `assistant` | 1.4 GiB | 2Gi | |
| each `tools-*` | 0.13 GiB | 512Mi | |
| `workflows` | 0.4 GiB | 1Gi | |
| **Total** | **about 21 GiB** | **31 GiB** | |

Against about 32 GiB allocatable on the grown workers (12 GiB each, about 11.6 GiB as the guest sees it, minus the 1 GiB reservation and the kubelet's 100Mi eviction threshold, so about 10.5 GiB per worker), with the other tenants requesting about 4.5 GiB today, that leaves roughly 6 GiB of headroom on requests. The other tenants' working set is larger (about 9.7 GiB including page cache), which is why each worker keeps the 1 GiB reservation and each host keeps 3 GiB free. The quotas add up to 31 GiB on purpose: they are ceilings per namespace (about 20 to 40% above the expected requests), not a promise that all of them fill at once. Together they are deliberately larger than the roughly 27.5 GiB left after the other tenants; the expected requests (about 21 GiB) are what must fit, and the quotas only stop one system from crowding the rest. LimitRange `defaults` in every namespace: default request `memory: 128Mi, cpu: 50m`, maximum `memory: 4Gi` per container, and no explicit default limit, so a container without a limit gets the 4Gi maximum as its limit (a small default limit would reject any chart that requests more memory than it without setting a limit). No CPU limit. Any container that needs more than 4Gi must be raised in that namespace's LimitRange first; nothing in the budget does today.

**Disk budget.** Longhorn on each worker has about 105 GB, 135 GiB already scheduled, a 200% overprovisioning limit and 25% kept free, so roughly 75 GiB more can be scheduled per node. Keep the sum of `longhorn` (3 replica) claims under 45 GiB and `longhorn-1r` claims under 40 GiB across Ask Tessaro, which comes to about 58 GiB per node if Longhorn spreads the single replica volumes evenly; it does not guarantee that, so the report lists where each `longhorn-1r` volume landed. Features 9 to 11 size their claims inside this and list them in the report.

### Hostnames

| Host | System (feature) |
|---|---|
| `auth.tessaro.toyintest.org` | Authentik (9) |
| `chat.tessaro.toyintest.org` | Zulip (9) |
| `helpdesk.tessaro.toyintest.org` | Zammad (11) |
| `assets.tessaro.toyintest.org` | Snipe-IT (11) |
| `hr.tessaro.toyintest.org` | Frappe HR with ERPNext (11) |
| `desks.tessaro.toyintest.org` | Seatsurfing (11) |
| `handbook.tessaro.toyintest.org` | BookStack (11) |
| `temporal.tessaro.toyintest.org` | Temporal UI (10) |
| `langfuse.tessaro.toyintest.org` | Langfuse (10) |
| `grafana.tessaro.toyintest.org` | Grafana (10) |
| `smoke.tessaro.toyintest.org` | the ingress smoke test only (AC-9) |

Argo CD keeps its existing hosts. Our own services expose no UI and get no Ingress; webhooks use cluster DNS (PRD 14.3).

### Network conventions (the contract features 9 to 16 follow)

Every namespace starts from `default-deny` plus `allow-dns`. Each system adds its own allow policies, kept with its install (`deploy/platform/<system>/` for off the shelf systems, the chart's `network` values for our own services):

- **From the ingress controller to a UI**: ingress from namespace `ingress-nginx`, pods `app.kubernetes.io/name: ingress-nginx`, to the UI port only.
- **To the Kubernetes API** (CNPG instances, anything that watches resources): a CiliumNetworkPolicy with `toEntities: [kube-apiserver]`. A NetworkPolicy `ipBlock` for the API server is not reliable under Cilium's kube proxy replacement.
- **CNPG clusters**: ingress from namespace `cnpg-system`, pods `app.kubernetes.io/name: cloudnative-pg`, on 8000 (status) and 5432; plus the API egress above; plus the app's own pods to 5432.
- **Internet**: only the privacy proxy, through `egressFQDNs` (AC-11). Any other system that wants the internet (update checks, push notification relays, plugin stores) keeps it switched off in its config instead of getting an exception.
- **Heavy pods**: label `tessaro.io/heavy: "true"` and add a preferred pod anti affinity on that label, so the pods marked in *Capacity budget* land on different nodes.

### GitOps layout

```
k3sprox-gitops (your cluster repo)
  apps/ask-tessaro.yaml        AppProject tessaro (sync wave -1) + Application ask-tessaro (project
                               default, source github.com/toyinogun/Ask-Tessaro, path deploy/argocd,
                               main, destination namespace argocd, automated sync with selfHeal,
                               prune off, ServerSideApply, no resources finalizer)

Ask-Tessaro (this repo)
  deploy/argocd/
    tessaro-baseline.yaml      Application, project tessaro, sync wave -10, chart charts/tessaro-baseline,
                               values deploy/values/baseline.yaml, automated sync with prune and selfHeal,
                               ServerSideApply, no resources finalizer
  deploy/cluster-repo/
    ask-tessaro.yaml           reference copy of the k3sprox-gitops file above (never synced, validated)
    (later features add one Application per release here)
  charts/tessaro-baseline/     Namespace, NetworkPolicy x2, LimitRange, ResourceQuota per namespace
  charts/schemas/              vendored JSON schemas for the CRD kinds kubeconform checks
  scripts/cluster/             netpol-proof.sh, ingress-smoke.sh, seal.sh (set -euo pipefail, shellcheck
                               clean, context guard on TESSARO_KUBE_CONTEXT)
  deploy/values/baseline.yaml  the 16 namespaces with tier and quota
  deploy/secrets/              sealed-secrets.pem, <namespace>/<name>.sealed.yaml
```

AppProject `tessaro`: `sourceRepos` is this repo plus the pinned upstream chart repositories that features 9 to 11 add; `destinations` are exactly the 16 namespaces on the in cluster server; `clusterResourceWhitelist` is only `Namespace`. Sync wave `-10` orders the baseline before every sibling Application that later features add under `ask-tessaro`. Waves between child Applications only wait if Argo CD can judge an Application's health, so the cluster's `argocd-cm` needs the standard `resource.customizations.health.argoproj.io_Application` health check (add it in `k3sprox-gitops` if missing). No Application carries the `resources-finalizer.argocd.argoproj.io` finalizer, so deleting one never deletes what it deployed. The `ask-tessaro` Application itself sits in project `default` like your other root entries, because it creates Application objects in `argocd`, which the `tessaro` project must not be able to do.

### Value sourcing

| Action | Value | Source |
|---|---|---|
| Baseline chart | namespace names and tiers | PRD 14.2, spec 0001 (Redis in `assistant`), this spec's *Namespaces* |
| Baseline chart | quota and LimitRange numbers | this spec's *Capacity budget* |
| `allow-dns` | DNS pod selector | cluster: `kube-system` pods labelled `k8s-app: kube-dns` |
| Ingress allow | controller selector | cluster: namespace `ingress-nginx`, label `app.kubernetes.io/name: ingress-nginx` |
| CNPG allow | operator selector | cluster: namespace `cnpg-system`, label `app.kubernetes.io/name: cloudnative-pg` (check the label when feature 9 writes the first one) |
| DNS record | target address | `ingress-nginx-controller` Service external IP, `172.16.70.40` |
| Certificates | issuer | existing ClusterIssuer `letsencrypt-prod` |
| Privacy proxy egress | host name | PRD 14.3 `PROXY_UPSTREAM_URL` (`https://api.deepseek.com`) |
| `just seal` | public certificate | `kubeseal --fetch-cert --controller-namespace kube-system --controller-name sealed-secrets-controller`, committed |
| Capacity check | allocatable memory | `kubectl get nodes` after the resize |
| Capacity check | other tenants' memory requests | `kubectl describe node` (Allocated resources) on the three workers, minus anything in the 16 namespaces |
| Capacity check | host headroom | `free -m` on `pve1` and `pve2` (`available` column, swap used) |
| Worker memory | VM size | `worker_nodepools[*].memory_mb` in `~/k3sprox/terraform-proxmox-k3s/examples/homelab/main.tf` |
| Proof and smoke scripts | the kube context allowed to run them | env var `TESSARO_KUBE_CONTEXT` (today `k3sprox-operator.tail62ceef.ts.net`), added to `.env.example` |
| Proof | FQDN policy under test | `helm template charts/tessaro-service` with a fixture values file in `scripts/cluster/fixtures/` |

### Key invariants

- Nothing outside the 16 namespaces changes, except: the AppProject and Application in `k3sprox-gitops`, the one DNS record, and the temporary proof namespaces (deleted on exit).
- No Namespace is ever deleted by Argo CD (AC-4 sync options).
- No pod in an Ask Tessaro namespace has internet egress except the privacy proxy.
- No plain Secret is committed; every secret in git is a SealedSecret with `strict` scope.
- The proof (AC-6) runs again after each install step in features 9 to 11 (PRD 14.4) and its output is appended to the report.

### Security model

- Ask Tessaro's Argo CD Applications can only write into their own namespaces and can only create Namespaces at cluster scope; the fence lives in the cluster repo.
- Nothing is reachable from the internet. Sign in pages are only on the LAN and tailnet.
- The kube context used today is `system:masters` (full admin). The baseline needs it only to run the proofs; installs go through Argo CD. See Follow-up for a narrower context.
- Sealed secrets can only be decrypted by the controller in this cluster. Losing its private key means resealing every secret, so its backup matters (Follow-up).

### Configuration required

No new service environment variables. One new local variable, `TESSARO_KUBE_CONTEXT`, read only by the cluster scripts. Changes outside this repo: shrink `gh-runner-1` (not managed by `terraform-proxmox-k3s`, so `qm set 300 --memory 4096` on `pve1` and a reboot of that VM, or wherever that VM is defined); in `~/k3sprox/terraform-proxmox-k3s`, the worker `memory_mb`, a `kubelet_system_reserved_memory` variable (default `1Gi`) and a workers only drop-in resource modelled on `terraform_data.kubelet_image_gc`; add the DNS record in Cloudflare; commit `apps/ask-tessaro.yaml` to `k3sprox-gitops`.

### Failure modes

- **A worker resize takes a node down**: drain one worker, apply the memory change for that VM only (`terraform apply -target` on its `proxmox_virtual_environment_vm.node` entry; the provider reboots the VM to change memory), wait for Ready, uncordon, and wait until every Longhorn volume is `healthy` before the next. Never apply the memory change to all workers at once: the provider would reboot them together. Longhorn's 3 replicas survive one node down; `longhorn-1r` volumes of other tenants (none today) would not.
- **A host runs out of memory**: `pve1` already swaps a little at today's total. Shrink `gh-runner-1` before growing `k3sprox-wkr-pve1-0`, never after, so `pve1`'s total never rises above today's 24 GiB. If either host drops under 3 GiB available (measured as in AC-2) after a step, stop and roll that VM back: revert its `memory_mb` in Terraform and apply under drain. On `pve1`, shrink the worker back before growing the runner back.
- **Longhorn rebuilds after each reboot**: three rounds of replica rebuilds (including `solutio`'s two 20 GiB volumes) add disk and memory load, and the last round lands on `pve1`, which swaps. Wait for every volume to be `healthy` before the next node, and do the rollout at a quiet time.
- **A big JVM pod hits the 4Gi container maximum**: Elasticsearch in `it` uses heap plus memory outside the heap. Feature 11 raises `it`'s LimitRange maximum first if its sizing needs more than 4Gi.
- **DNS rebinding protection**: some home routers and resolvers refuse a public name that answers with a private address. If the record does not resolve on the LAN, add an exception for `tessaro.toyintest.org` in the router or resolver.
- **FQDN rule without its DNS rule**: Cilium learns the addresses for `toFQDNs` only from DNS answers it sees, so the DNS rule must be in the same policy (AC-11). Without it the proxy gets no egress at all, which fails closed but looks like an outage.
- **Quota blocks a rollout**: a rolling update briefly runs old and new pods; if `requests.memory` hits the quota the new pod stays pending. Raise that namespace's quota in `deploy/values/baseline.yaml`.
- **The cluster changed today**: Cilium, Argo CD's own policies, Sealed Secrets and the CNPG databases all restarted about 4 to 5 hours before the investigation. Run the proof only once the cluster is stable, and record the Cilium version again in the report.

### Critical test scenarios

- Happy path: grow the workers, sync `ask-tessaro`, the 16 namespaces appear with their 4 objects, verifies **AC-2**, **AC-3**, **AC-4**, **AC-5**, **AC-12**
- Enforcement: `just netpol-proof` shows allow, then deny, then FQDN only egress, then a sealed secret unsealed, verifies **AC-6**, **AC-7**, **AC-10**, **AC-11**
- Fence: an Application in project `tessaro` aimed at `default` is refused, verifies **AC-3**
- Pod Security: a root pod is rejected in `assistant` and admitted with a warning in `chat`, verifies **AC-8**
- TLS and DNS: `https://smoke.tessaro.toyintest.org` returns 200 with a trusted certificate from the LAN and the tailnet, verifies **AC-9**
- Report: every PRD step 0 area is present with its decision, verifies **AC-1**

## Build plan

Tracer Bullet: prove the whole path (git, Argo CD, one namespace, its policies, the proof) on `assistant` first, then widen to all 16.

1. Grow the workers, satisfies **AC-2**:
   - (a) Pre checks: record each host's `free -m` and swap; list Longhorn volumes by replica count and stop if any other tenant has a single replica volume; confirm the pods on each worker could fit (by memory requests) on the other two.
   - (b) In `terraform-proxmox-k3s`, add a `kubelet_system_reserved_memory` variable (default `1Gi`) and a workers only `terraform_data` that writes `60-system-reserved.yaml` with `kubelet-arg+:` and does **not** restart k3s; each worker picks it up on its memory reboot in (d). Apply it.
   - (c) Shrink `gh-runner-1`: pause it in GitHub and wait for running jobs, then on `pve1` run `qm shutdown 300`, `qm set 300 --memory 4096`, `qm start 300`; confirm it picks up a job. If it cannot cope at 4 GiB, move its jobs to GitHub hosted runners rather than growing it back.
   - (d) Set worker `memory_mb = 12288`. For each worker in turn (`k3sprox-wkr-pve2-0`, then `k3sprox-wkr-pve2-1`, then `k3sprox-wkr-pve1-0`): `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=10m` (never `--force`; a stalled drain means stop and look, usually a PodDisruptionBudget or a Longhorn volume still attached); `terraform plan -target` on that VM, which must show an in place memory update only, never a replace; apply it (the provider reboots the VM); wait for Ready and check `configz`; `kubectl uncordon`; wait until every Longhorn volume is `healthy`.
   - (e) Run a full `terraform plan` (it must show no changes), wait 30 minutes, then record allocatable memory, host `free -m` and swap, and the other tenants' requests in the report.
2. Write `scripts/cluster/netpol-proof.sh` (context guard, pinned images, polling probe) and the `just netpol-proof` recipe; until step 7 lands, step (c) uses a fixture CiliumNetworkPolicy in `scripts/cluster/fixtures/`. Run it and keep its output, satisfies **AC-6**, **AC-7**
3. Fetch and commit `deploy/secrets/sealed-secrets.pem`; add `just seal` with its namespace and git ignore guards; extend the proof with step (d), satisfies **AC-10**, **AC-6**
4. Create `charts/tessaro-baseline` and `deploy/values/baseline.yaml` with `assistant` only; vendor the CRD schemas into `charts/schemas/`; add the chart, the namespace count check and shellcheck on `scripts/cluster/` to `just check`, satisfies **AC-12**, **AC-5**, **AC-11**
5. Add `deploy/argocd/tessaro-baseline.yaml` and the reference copy `deploy/cluster-repo/ask-tessaro.yaml`; in `k3sprox-gitops`, add the same AppProject and Application (and the Application health check if `argocd-cm` lacks it); sync, check `assistant` and its objects, and check the project refuses a `default` destination, satisfies **AC-3**, **AC-4**, **AC-5**
6. Widen `deploy/values/baseline.yaml` to all 16 namespaces and sync; run the Pod Security dry runs, satisfies **AC-4**, **AC-5**, **AC-8**
7. Replace `egressCIDRs` with `egressFQDNs` in `charts/tessaro-service` (template, schema, tests) and set it in the privacy proxy values; switch the proof's step (c) from the fixture to the chart's rendered policy, satisfies **AC-11**, **AC-6**
8. Add the Cloudflare record; write `scripts/cluster/ingress-smoke.sh` and `just ingress-smoke`; run it with staging, then once with `--prod`; check the URL by hand from the tailnet, satisfies **AC-9**
9. Write `docs/environment-report.md` from the inventory in [rationale.md](rationale.md), refreshed on the day, with the proof outputs and the `## Decisions` section, satisfies **AC-1**
10. Update spec 0001 in the same PR: Secrets in the cluster (Sealed Secrets, not KSOPS), Deploy (root entry in `k3sprox-gitops`, project `tessaro`), NetworkPolicy values (`egressFQDNs`), Image registry (confirmed), and tick its feature 8 follow up, satisfies **AC-11**, **AC-3**

## Consequences

**Positive**:
- Nothing new to install or operate before feature 9: every layer reuses a tool that already runs here.
- The fence keeps the blast radius of Ask Tessaro's GitOps inside its own namespaces on a shared cluster.
- Hostname egress for the proxy replaces a brittle IP list and closes spec 0001's open question.
- The whole PRD stack fits, so Seatsurfing and Snipe-IT do not need to wait for capacity.

**Negative / tradeoffs**:
- Ask Tessaro now depends on tools it does not own: ingress-nginx, Longhorn, cert-manager, Argo CD and Sealed Secrets are upgraded (or broken) for every tenant at once. Upstream ingress-nginx is retired, so the cluster will need to move to another controller or Gateway API, and Ask Tessaro's Ingresses move with it.
- Sealed Secrets departs from PRD 14.3's letter (SOPS) and you cannot decrypt a sealed file on the laptop, only reseal it; local secrets stay in `.env`.
- Two repos change for one feature: the fence and root entry live in `k3sprox-gitops`.
- The resize touches a third repo (`terraform-proxmox-k3s`) and briefly runs Longhorn with one replica missing per volume.
- `gh-runner-1` drops to 4 GiB, so heavy CI jobs on that runner may need GitHub hosted runners.
- The headroom is about 6 GiB on requests, not the 14 GiB first planned. A heavier system, or a second copy of one, means raising a quota and checking the nodes first, or retiring `gh-runner-1` to give `pve1` slack.
- A per namespace CNPG cluster costs about 150 to 250 MiB each, more than one shared Postgres.
- Private only hostnames mean a demo away from home needs the tailnet.

**Neutral**:
- Spec 0001's Deploy, Secrets in the cluster, NetworkPolicy values and Image registry rows are updated to point here (build step 10).
- The kubelet memory reservation applies to every pod on the workers, including your other tenants: about 1 GiB per worker stops being schedulable.
- `docs/environment-report.md` becomes a living document: the proof is appended after each install step.

## Follow-up

- [ ] Zulip's chart ships its own Postgres image with full text search dictionaries; feature 9 decides whether to build a CNPG compatible image with them or keep Zulip's bundled Postgres as the one exception.
- [ ] Frappe's chart wants a shared (RWX) volume for sites; feature 11 checks that Longhorn RWX works on these nodes (it needs the NFS client on each worker) or runs Frappe with a single writer.
- [ ] Confirm the Sealed Secrets private key is backed up outside the cluster; without it a rebuilt cluster cannot read any sealed secret.
- [ ] Create a narrower kube context for agent work (read only cluster wide, plus create and delete in `tessaro-netpol-proof`), so day to day sessions stop using `system:masters`.
- [ ] Plan the cluster's move off ingress-nginx (retired upstream); Cilium's Gateway API support is the obvious target since Cilium is already the CNI.
- [ ] Consider retiring `gh-runner-1` in favour of GitHub hosted runners; it would give `pve1` real slack (it swaps today) and room to grow its worker later.
- [ ] `solutio` has restarted about 3,500 times; not Ask Tessaro's concern, but it holds two 20 GiB volumes and some CPU on a shared cluster.
