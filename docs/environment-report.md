# Environment report: the k3s cluster

The step 0 report from PRD 14.2: what the cluster runs, what Ask Tessaro reuses, and the decisions every later install (features 9 to 16) builds on. Spec [0007](specs/0007-cluster-baseline/index.md) holds the reasoning; this file holds the facts. It is a living document: the network proof runs again after each install step in features 9 to 11, and its output is appended under *Proof history*.

**How it was checked.** `kubectl` through the Tailscale operator proxy (context `k3sprox-operator.tail62ceef.ts.net`, a `system:masters` identity). The inventory used only `get`, `describe`, `top` and `auth`. The proofs (`just netpol-proof`, `just ingress-smoke`) write only into their own temporary namespaces and delete them on exit.

**Status.** Sections marked _pending_ wait on an engineer action outside this repo: the worker resize, the `k3sprox-gitops` commit and the DNS record.

## Cluster

_Checked 2026-10-10._

- k3s `v1.36.5+k3s1` on four nodes (the PRD assumed three): one control plane and three workers on two Proxmox hosts (`pve1`, `pve2`). Ubuntu 24.04.4, amd64, containerd 2.3.4.
- The control plane carries `control-plane:NoSchedule`, so only the three workers run workloads.

| Node | Role | CPU | Memory | Allocatable memory | Memory in use (`kubectl top`) |
|---|---|---|---|---|---|
| `k3sprox-cp-0` | control plane, etcd | 2 | 3.8 GiB | 3.8 GiB | 2.3 GiB (60%) |
| `k3sprox-wkr-pve1-0` | worker | 4 | 7.8 GiB | 7.8 GiB | 3.4 GiB (44%) |
| `k3sprox-wkr-pve2-0` | worker | 4 | 7.8 GiB | 7.8 GiB | 3.1 GiB (40%) |
| `k3sprox-wkr-pve2-1` | worker | 4 | 7.8 GiB | 7.8 GiB | 3.1 GiB (39%) |

Allocatable equals capacity on every node today: no `system-reserved` is set.

## Workloads

_Checked 2026-10-10._

- Tenants: `argocd`, `cert-manager`, `cloudflared`, `cnpg-system`, four `deployer-*` namespaces and twelve `app-*` test apps, `ingress-nginx`, `longhorn-system`, `metallb-system`, `mool`, `n8n`, `provic`, `site`, `solutio`, `tailscale`, plus the Kubernetes defaults.
- None of the 16 Ask Tessaro namespaces existed before this feature, so there are no name clashes.
- `solutio` app pods and its Zitadel show about 3,500 restarts (the last 27 days ago), and `n8n` about 2,000. Not Ask Tessaro's concern, but they share the workers.

## Ingress

_Checked 2026-10-10._

- IngressClasses `nginx` (ingress-nginx controller 1.15.1, chart 4.15.1, two replicas) and `tailscale`.
- Existing hosts: `*.deploy.toyintest.org`, `argocd.k3s.local`, `longhorn.k3s.local`, `*.itsm.toyinog.com` and several `*.tail62ceef.ts.net` Tailscale ingresses.
- A remotely managed cloudflared tunnel runs in `cloudflared`, and a second one in `deployer-edge`. Ask Tessaro uses neither.
- Upstream ingress-nginx is retired, so the cluster will move to another controller or Gateway API at some point (spec 0007 follow up).

## Load balancing

_Checked 2026-10-10._

- MetalLB pool `k3sprox-pool` (`172.16.70.40` to `172.16.70.79`, L2 advertisement). `ingress-nginx-controller` is a LoadBalancer Service on `172.16.70.40`, ports 80 and 443. Cilium's LB IPAM is also on.

## Storage

_Checked 2026-10-10._

- StorageClasses `longhorn` (default, 3 replicas), `longhorn-1r` (1 replica) and `longhorn-static`; all `Immediate` binding, expansion allowed, reclaim `Delete`.
- Longhorn disks: about 105 GB on each worker, 135 GiB already scheduled per node, overprovisioning limit 200%, 25% kept free. That leaves roughly 75 GiB more to schedule per node.
- Ten existing volumes, all 3 replicas, 1 to 20 GiB, all `healthy`.
- The CNPG operator `ghcr.io/cloudnative-pg/cloudnative-pg:1.30.1` runs in `cnpg-system`.

## Networking

_Checked 2026-10-10._

- Cilium 1.20.2 is the CNI: kube proxy replacement on, tunnel routing, Kubernetes NetworkPolicy enforcement on, L7 proxy and transparent DNS proxy on (so `toFQDNs` rules work), Hubble off.
- Existing policies: default deny in each deployer app namespace, and Argo CD's own policies.
- Enforcement is proven by `just netpol-proof` (below): plain NetworkPolicy blocks pod traffic, DNS still resolves under default deny, and a CiliumNetworkPolicy opens exactly one host name.
- Cilium, CoreDNS, Sealed Secrets, ingress-nginx and the CNPG databases had all restarted 4 to 5 hours before the first inventory. The proof ran later the same day, after the cluster settled; Cilium was still 1.20.2.

## Certificates and DNS

_Checked 2026-10-10._

- cert-manager with ClusterIssuers `letsencrypt-prod` and `letsencrypt-staging`, both ACME DNS01 through Cloudflare. A wildcard `*.deploy.toyintest.org` from `letsencrypt-prod` shows the token can write the `toyintest.org` zone.
- No external DNS controller: records are added by hand in Cloudflare.
- `*.tessaro.toyintest.org` does not resolve yet. _Pending: the A record (see Decisions)._

## Images

_Checked 2026-10-10._

- Nodes pull from `docker.io`, `quay.io`, `ghcr.io` and `registry.k8s.io` with no pull secrets.
- GHCR pulls by the nodes are confirmed: the running CNPG operator uses `ghcr.io/cloudnative-pg/cloudnative-pg@sha256:923c267ec29636db3bee20f993d0ec4973fa22998e1adad37da79e4d32b5bc07`.
- The in cluster registry `deployer-registry.deployer-system.svc:5000` belongs to the deployer platform; Ask Tessaro does not use it.

## Tooling

_Checked 2026-10-10._

- kubectl through Tailscale with full admin; Helm 4.2 locally.
- Argo CD 3.5.4 runs an app of apps: `root` from `git@github.com:toyinogun/k3sprox-gitops.git` (path `apps`) in project `default`. One other AppProject exists, `deployer`. Argo CD Image Updater is installed.
- `argocd-cm` has no health check for `argoproj.io_Application`, so sync waves between child Applications would not wait on each other. It does not matter while `tessaro-baseline` is the only child; it must be added before feature 9 adds siblings.
- Bitnami Sealed Secrets 0.40.0 in `kube-system` (controller `sealed-secrets-controller`). Its public certificate is committed at `deploy/secrets/sealed-secrets.pem` (valid until 2036-04-28). KSOPS is not installed.

## Outbound access

_Checked 2026-10-10 by `just netpol-proof` step a._

- With no policy, a pod reaches `https://api.deepseek.com` (HTTP 401) and `https://ghcr.io` (HTTP 301). So pods have internet egress by default, and `default-deny` is what removes it (step b4).

## Capacity

_Pending: the worker resize (spec 0007 AC-2)._

Per namespace budget against the workers, before and after the resize:

| Namespace | Expected requests (memory) | ResourceQuota `requests.memory` |
|---|---|---|
| `identity` | 1.2 GiB | 2Gi |
| `chat` | 2.5 GiB | 4Gi |
| `it` | 4.1 GiB | 6Gi |
| `hr-finance` | 2.8 GiB | 5Gi |
| `workplace` | 0.4 GiB | 1Gi |
| `handbook` | 0.5 GiB | 1Gi |
| `platform` | 3.0 GiB | 4Gi |
| `observability` | 4.3 GiB | 6Gi |
| `assistant` | 1.4 GiB | 2Gi |
| six `tools-*` | 0.13 GiB each | 512Mi each |
| `workflows` | 0.4 GiB | 1Gi |
| **Total** | **about 21 GiB** | **35 GiB** |

| | Allocatable on the three workers | Other tenants in use | Left for Ask Tessaro |
|---|---|---|---|
| Before (2026-10-10) | 23.3 GiB | about 9.7 GiB | about 13.6 GiB, short of the 21 GiB budget |
| After the resize | _pending_ (expect about 45 GiB) | _pending_ | _pending_ |

## Pod Security

_Pending: runs once `tessaro-baseline` has synced the namespaces (spec 0007 AC-8)._

## Network proof

`just netpol-proof`, 2026-10-10. The first run failed step b2 only because busybox `nslookup` ignores the resolv.conf search list (`kubernetes.default` gave NXDOMAIN even with no policy at all); the step now looks up the fully qualified name. Second run:

```
netpol proof on context k3sprox-operator.tail62ceef.ts.net, 2026-10-10T07:52:25Z
# a: no policy
PASS a1   http://server.tessaro-netpol-proof.svc.cluster.local:8080/ is reachable 200
PASS a2   https://api.deepseek.com is reachable 401
PASS a3   https://ghcr.io is reachable 301
# b: the baseline chart's default-deny and allow-dns
PASS b1   http://server.tessaro-netpol-proof.svc.cluster.local:8080/ is blocked
PASS b2   kubernetes.default.svc.cluster.local resolves
PASS b3   example.com resolves
PASS b4   https://api.deepseek.com is blocked
# c: the shared chart's CiliumNetworkPolicy for egressFQDNs [api.deepseek.com]
PASS c1   https://api.deepseek.com is reachable 401
PASS c2   example.com resolves
PASS c3   https://example.com is blocked
PASS c4   http://server.tessaro-netpol-proof.svc.cluster.local:8080/ is blocked
# d: a SealedSecret is bound to its namespace
PASS d1   SealedSecret became Secret netpol-proof with key PROOF_VALUE in tessaro-netpol-proof
PASS d2   the same sealed file gives no Secret in tessaro-netpol-proof-b (strict scope)
netpol proof: every step passed
```

## Ingress smoke

_Pending: the DNS record. Then `just ingress-smoke`, once `just ingress-smoke --prod`, and the tailnet check by hand (spec 0007 AC-9)._

## Decisions

| Area | Decision |
|---|---|
| Ingress class | `nginx` (existing ingress-nginx on MetalLB `172.16.70.40`) |
| Storage class | `longhorn` (3 replicas) for databases and Redis with AOF; `longhorn-1r` for data you can rebuild (Elasticsearch, ClickHouse, Loki, Langfuse blob store, RabbitMQ). Ask Tessaro keeps `longhorn` claims under 45 GiB and `longhorn-1r` claims under 40 GiB in total |
| Hostnames | `<system>.tessaro.toyintest.org`: `auth`, `chat`, `helpdesk`, `assets`, `hr`, `desks`, `handbook`, `temporal`, `langfuse`, `grafana`, plus `smoke` for the smoke test. Private: LAN and tailnet only |
| DNS | One Cloudflare record `*.tessaro.toyintest.org` A `172.16.70.40`, not proxied |
| Certificates | One certificate per Ingress from ClusterIssuer `letsencrypt-prod` (DNS01 through Cloudflare) |
| Internet egress | Only the privacy proxy, through the CiliumNetworkPolicy the shared chart renders from `network.egressFQDNs` (`api.deepseek.com`). Proven by the network proof, step c |
| Secrets | Sealed Secrets with `strict` scope, sealed by `just seal` into `deploy/secrets/<namespace>/` |
| GitOps | AppProject `tessaro` and root Application `ask-tessaro` in `k3sprox-gitops`; `tessaro-baseline` and later Applications in this repo's `deploy/argocd/` |
| Pod Security | `restricted` for our own namespaces; `baseline` enforced (audit and warn `restricted`) for off the shelf systems |
| Capacity plan | Grow the three workers from 8 to 16 GiB with kubelet `system-reserved=memory=1Gi`, one node at a time, before feature 9 |

**Gaps still open**

- The worker resize and kubelet reservation (AC-2).
- The `k3sprox-gitops` commit for AppProject `tessaro` and Application `ask-tessaro` (AC-3), plus the Application health check in `argocd-cm` before feature 9.
- The DNS record and the ingress smoke results (AC-9).
- From spec 0007's follow ups: Zulip's Postgres image, Longhorn RWX for Frappe, the Sealed Secrets private key backup, a narrower kube context for agent work, and the move off ingress-nginx.

## Proof history

Append the `just netpol-proof` output here after each install step in features 9 to 11.
