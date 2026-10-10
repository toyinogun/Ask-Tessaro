# Environment report: the k3s cluster

The step 0 report from PRD 14.2: what the cluster runs, what Ask Tessaro reuses, and the decisions every later install (features 9 to 16) builds on. Spec [0007](specs/0007-cluster-baseline/index.md) holds the reasoning; this file holds the facts. It is a living document: the network proof runs again after each install step in features 9 to 11, and its output is appended under *Proof history*.

**How it was checked.** `kubectl` through the Tailscale operator proxy (context `k3sprox-operator.tail62ceef.ts.net`, a `system:masters` identity). The inventory used only `get`, `describe`, `top` and `auth`. The proofs (`just netpol-proof`, `just ingress-smoke`) write only into their own temporary namespaces and delete them on exit.

**Status.** Sections marked _pending_ wait on the wildcard DNS record (an engineer action in Cloudflare) or on a first CI job on the resized runner.

## Cluster

_Checked 2026-10-10._

- k3s `v1.36.5+k3s1` on four nodes (the PRD assumed three): one control plane and three workers on two Proxmox hosts (`pve1`, `pve2`). Ubuntu 24.04.4, amd64, containerd 2.3.4.
- The control plane carries `control-plane:NoSchedule`, so only the three workers run workloads.

Before the resize (first inventory):

| Node | Role | CPU | Memory | Allocatable memory | Memory in use (`kubectl top`) |
|---|---|---|---|---|---|
| `k3sprox-cp-0` | control plane, etcd | 2 | 3.8 GiB | 3.8 GiB | 2.3 GiB (60%) |
| `k3sprox-wkr-pve1-0` | worker | 4 | 7.8 GiB | 7.8 GiB | 3.4 GiB (44%) |
| `k3sprox-wkr-pve2-0` | worker | 4 | 7.8 GiB | 7.8 GiB | 3.1 GiB (40%) |
| `k3sprox-wkr-pve2-1` | worker | 4 | 7.8 GiB | 7.8 GiB | 3.1 GiB (39%) |

After the resize (AC-2, 2026-10-10, workers at `memory_mb = 12288` with `system-reserved=memory=1Gi`):

| Node | Role | CPU | Memory | Allocatable memory | Memory in use (`kubectl top`) |
|---|---|---|---|---|---|
| `k3sprox-cp-0` | control plane, etcd | 2 | 3.8 GiB | 3.8 GiB | 2.2 GiB (58%) |
| `k3sprox-wkr-pve1-0` | worker | 4 | 11.7 GiB | 10.7 GiB | 1.7 GiB (15%) |
| `k3sprox-wkr-pve2-0` | worker | 4 | 11.7 GiB | 10.7 GiB | 2.9 GiB (26%) |
| `k3sprox-wkr-pve2-1` | worker | 4 | 11.7 GiB | 10.7 GiB | 2.9 GiB (27%) |

Each worker's kubelet `configz` (`kubectl get --raw /api/v1/nodes/<node>/proxy/configz`) shows `systemReserved: {memory: 1Gi}` with image GC thresholds 70 and 50. The reservation comes from a Terraform managed drop-in `/etc/rancher/k3s/config.yaml.d/60-system-reserved.yaml` (`terraform_data.kubelet_system_reserved` in `terraform-proxmox-k3s`, workers only, no k3s restart: each worker picked it up on its resize reboot). A full `terraform plan` showed no changes after the last worker.

## Workloads

_Checked 2026-10-10._

- Tenants: `argocd`, `cert-manager`, `cloudflared`, `cnpg-system`, four `deployer-*` namespaces and twelve `app-*` test apps, `ingress-nginx`, `longhorn-system`, `metallb-system`, `mool`, `n8n`, `provic`, `site`, `solutio`, `tailscale`, plus the Kubernetes defaults.
- None of the 16 Ask Tessaro namespaces existed before this feature, so there are no name clashes.
- `solutio` app pods and its Zitadel show about 3,500 restarts (the last 27 days ago), and `n8n` about 2,000. Not Ask Tessaro's concern, but they share the workers.
- Update, same day: `solutio` (and its Zitadel) was retired by its owner during the resize and removed with its Argo CD Application and four volumes. Its CNPG WAL archiving to R2 had been failing with 403 since 2026-10-09, which left its former primaries unable to rejoin as replicas after the drain.

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
- `*.tessaro.toyintest.org` A `172.16.70.40` (DNS only) added by hand on 2026-10-10 and resolving on the LAN; see *Ingress smoke*.

## Images

_Checked 2026-10-10._

- Nodes pull from `docker.io`, `quay.io`, `ghcr.io` and `registry.k8s.io` with no pull secrets.
- GHCR pulls by the nodes are confirmed: the running CNPG operator uses `ghcr.io/cloudnative-pg/cloudnative-pg@sha256:923c267ec29636db3bee20f993d0ec4973fa22998e1adad37da79e4d32b5bc07`.
- The in cluster registry `deployer-registry.deployer-system.svc:5000` belongs to the deployer platform; Ask Tessaro does not use it.

## Tooling

_Checked 2026-10-10._

- kubectl through Tailscale with full admin; Helm 4.2 locally.
- Argo CD 3.5.4 runs an app of apps: `root` from `git@github.com:toyinogun/k3sprox-gitops.git` (path `apps`) in project `default`. One other AppProject exists, `deployer`. Argo CD Image Updater is installed.
- `argocd-cm` had no health check for `argoproj.io_Application`, so sync waves between child Applications would not wait on each other. It is now set through the Argo CD Helm values in `terraform-proxmox-k3s` (`configs.cm`), so waves wait before feature 9 adds siblings.
- AppProject `tessaro` and root Application `ask-tessaro` are committed in `k3sprox-gitops` (`apps/ask-tessaro.yaml`, toyinogun/k3sprox-gitops#36). `ask-tessaro` and `tessaro-baseline` are `Synced` and `Healthy`. The fence holds: an Application in project `tessaro` aimed at `default` is refused with "application destination server 'https://kubernetes.default.svc' and namespace 'default' do not match any of the allowed destinations in project 'tessaro'".
- Bitnami Sealed Secrets 0.40.0 in `kube-system` (controller `sealed-secrets-controller`). Its public certificate is committed at `deploy/secrets/sealed-secrets.pem` (valid until 2036-04-28). KSOPS is not installed.

## Outbound access

_Checked 2026-10-10 by `just netpol-proof` step a._

- With no policy, a pod reaches `https://api.deepseek.com` (HTTP 401) and `https://ghcr.io` (HTTP 301). So pods have internet egress by default, and `default-deny` is what removes it (step b4).

## Capacity

_Checked 2026-10-10 (AC-2)._

**The resize.** The Proxmox hosts set the ceiling (`pve1` was full and swapping, `pve2` had about 12.5 GiB free), so 16 GiB workers did not fit. Done in this order, one node at a time:

1. `gh-runner-1` (VMID 300 on `pve1`, three runner services for `toyinogun/pdf2`), idle at the time, shut down and set to 4 GiB with `qm set 300 --memory 4096`. All three runners came back `online` in GitHub. _Pending: its first job at 4 GiB; the repository has had no runs since 2026-09-22._
2. The `60-system-reserved.yaml` drop-in written to all three workers by Terraform, with no k3s restart.
3. Each worker set to `memory_mb = 12288` and applied with `terraform apply -target` on its VM alone (an in place memory update; the provider reboots the VM), drained first and uncordoned after Ready, then held until every Longhorn volume was `healthy`: `k3sprox-wkr-pve2-0`, then `k3sprox-wkr-pve2-1`, then `k3sprox-wkr-pve1-0`.

What the rollout ran into:

- Draining `pve2-0` made CNPG switch the two-instance `solutio-db` and `zitadel-db` over to their replicas cleanly. The former primaries could not rejoin, because rejoining archives WAL first and their R2 archive returned 403 (broken since 2026-10-09). `solutio` was retired and removed instead (see *Workloads*).
- `n8n-db` and `provic-pg` are single-instance clusters, so their primary PDBs never allow an eviction. `pve2-1` was drained without the CNPG pods, then those pods were deleted (a clean Postgres shutdown) so CNPG recreated them on `pve2-0` with their Longhorn volumes, about a minute of downtime each.
- The drain of `pve2-1` evicted the Tailscale operator, the API proxy `kubectl` uses, which left that drain hanging on a dead connection; rerunning the drain finished it. Drain the node that holds the operator from a LAN kubeconfig next time, or expect this.
- A full `terraform plan` afterwards showed no changes.

**Hosts**, measured at 09:38 UTC, 30 minutes after every Longhorn volume was `healthy` again (`free -m`):

| Host | Memory available | Swap used | Assigned to VMs (worst case) |
|---|---|---|---|
| `pve1` (30.9 GiB) | 15.7 GiB (before: 6.0 GiB) | 1.24 GiB (baseline 1.3 GiB) | 24 GiB: cp 4, homeassistant 4, worker 12, runner 4 (unchanged from before) |
| `pve2` (31.1 GiB) | 8.6 GiB (before: 12.5 GiB) | 0 | 24 GiB: two workers at 12 |

`available` is high on `pve1` because the guests have not touched their new memory yet. The fixed figure is the last column: with every VM fully used, each host keeps about 7 GiB for Proxmox itself, above the 3 GiB floor.

**Per namespace budget** (spec 0007 *Capacity budget*):

| Namespace | Expected requests (memory) | ResourceQuota `requests.memory` |
|---|---|---|
| `identity` | 1.2 GiB | 2Gi |
| `chat` | 2.5 GiB | 3Gi |
| `it` | 4.1 GiB | 5Gi |
| `hr-finance` | 2.8 GiB | 4Gi |
| `workplace` | 0.4 GiB | 1Gi |
| `handbook` | 0.5 GiB | 1Gi |
| `platform` | 3.0 GiB | 4Gi |
| `observability` | 4.3 GiB | 5Gi |
| `assistant` | 1.4 GiB | 2Gi |
| six `tools-*` | 0.13 GiB each | 512Mi each |
| `workflows` | 0.4 GiB | 1Gi |
| **Total** | **about 21 GiB** | **31 GiB** |

**Against the workers:**

| | Allocatable on the three workers | Other tenants' memory requests | Left for Ask Tessaro (requests) |
|---|---|---|---|
| Before (2026-10-10) | 23.3 GiB | about 4.5 GiB (about 9.7 GiB in use) | about 18.8 GiB, short of the 21 GiB budget once usage is counted |
| After the resize (2026-10-10, `solutio` removed) | 32.0 GiB (10.7 GiB per worker) | 4.2 GiB (about 7.4 GiB in use) | about 27.9 GiB, so the 21 GiB budget fits with about 7 GiB to spare |

The quotas add up to 31 GiB on purpose: they are ceilings per namespace, not a promise that every one fills at once (spec 0007).

## Namespaces

_Checked 2026-10-10, after `tessaro-baseline` synced._

All 16 namespaces exist, labelled `app.kubernetes.io/part-of: ask-tessaro`, with sync options `Prune=false,Delete=false`. Each holds exactly `default-deny`, `allow-dns`, LimitRange `defaults` and ResourceQuota `budget` (AC-4, AC-5).

| Tier | Namespaces | Pod Security |
|---|---|---|
| own | `assistant`, `tools-it`, `tools-people`, `tools-finance`, `tools-workplace`, `tools-handbook`, `tools-identity`, `workflows` | enforce, audit and warn `restricted`, version `latest` |
| system | `identity`, `chat`, `it`, `hr-finance`, `workplace`, `handbook`, `platform`, `observability` | enforce `baseline`, audit and warn `restricted`, version `latest` |

## Pod Security

_Checked 2026-10-10 (AC-8)._ A pod running as root with no `securityContext`, as a server side dry run:

```
$ kubectl -n assistant run psa-root-test --image=busybox:1.37 --restart=Never --dry-run=server -- sleep 1
Error from server (Forbidden): pods "psa-root-test" is forbidden: violates PodSecurity "restricted:latest": allowPrivilegeEscalation != false (container "psa-root-test" must set securityContext.allowPrivilegeEscalation=false), unrestricted capabilities (container "psa-root-test" must set securityContext.capabilities.drop=["ALL"]), runAsNonRoot != true (pod or container "psa-root-test" must set securityContext.runAsNonRoot=true), seccompProfile (pod or container "psa-root-test" must set securityContext.seccompProfile.type to "RuntimeDefault" or "Localhost")

$ kubectl -n chat run psa-root-test --image=busybox:1.37 --restart=Never --dry-run=server -- sleep 1
Warning: would violate PodSecurity "restricted:latest": allowPrivilegeEscalation != false (container "psa-root-test" must set securityContext.allowPrivilegeEscalation=false), unrestricted capabilities (container "psa-root-test" must set securityContext.capabilities.drop=["ALL"]), runAsNonRoot != true (pod or container "psa-root-test" must set securityContext.runAsNonRoot=true), seccompProfile (pod or container "psa-root-test" must set securityContext.seccompProfile.type to "RuntimeDefault" or "Localhost")
pod/psa-root-test created (server dry run)
```

Rejected in `assistant` (restricted), admitted with a warning in `chat` (baseline).

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

_Checked 2026-10-10 (AC-9)._ The Cloudflare record `*.tessaro.toyintest.org` A `172.16.70.40` (DNS only) was added by hand, and `dig +short smoke.tessaro.toyintest.org` on a LAN device gives `172.16.70.40`.

`just ingress-smoke` (staging):

```
ingress smoke on context k3sprox-operator.tail62ceef.ts.net with letsencrypt-staging, 2026-10-10T09:30:59Z
DNS: smoke.tessaro.toyintest.org -> 172.16.70.40
PASS certificate smoke-tls Ready from letsencrypt-staging in 77s
PASS https://smoke.tessaro.toyintest.org/ answers 200 (curl -k)
ingress smoke: every step passed
```

`just ingress-smoke --prod` (run once; Let's Encrypt allows 5 identical certificates per week):

```
ingress smoke on context k3sprox-operator.tail62ceef.ts.net with letsencrypt-prod, 2026-10-10T09:32:44Z
DNS: smoke.tessaro.toyintest.org -> 172.16.70.40
PASS certificate smoke-tls Ready from letsencrypt-prod in 78s
PASS https://smoke.tessaro.toyintest.org/ answers 200 (curl -k)
PASS https://smoke.tessaro.toyintest.org/ answers 200 with a certificate the system store trusts
issuer=C=US, O=Let's Encrypt, CN=YR1
notAfter=Jan  8 08:35:31 2027 GMT
ingress smoke: every step passed
```

Tailnet: _pending, the manual check from a tailnet device away from the LAN._

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
| Capacity plan | Shrink `gh-runner-1` from 8 to 4 GiB, then grow the three workers from 8 to 12 GiB with kubelet `system-reserved=memory=1Gi`, one node at a time, before feature 9. Done 2026-10-10 |

**Gaps still open**

- The tailnet check of `https://smoke.tessaro.toyintest.org` from a device away from the LAN (AC-9).
- A first CI job on `gh-runner-1` at 4 GiB (AC-2); its repository has had no runs since 2026-09-22.
- From spec 0007's follow ups: Zulip's Postgres image, Longhorn RWX for Frappe, the Sealed Secrets private key backup, a narrower kube context for agent work, and the move off ingress-nginx.

## Proof history

Append the `just netpol-proof` output here after each install step in features 9 to 11.
