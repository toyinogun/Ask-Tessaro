# 0007. Rationale: cluster baseline

The decision record behind [index.md](index.md). `/develop` builds from the index; this file explains why, and keeps the inventory the decisions rest on.

## Context

Ask Tessaro moves from the laptop to a real k3s cluster. PRD 14.2 says nothing is installed until a read only investigation is written down, and that the report must end with decisions for ingress, storage, hostnames, certificates and capacity. Every later feature (9 to 16) installs into whatever this baseline lays down, so a wrong call here is paid for a dozen times.

The cluster is not empty and not dedicated. It is a shared homelab cluster running other projects (n8n, solutio, the deployer platform and its test apps, provic, mool, site) and its own platform tooling, managed from a separate GitOps repo. Anything Ask Tessaro does must not disturb those tenants, and anything it adds becomes something the engineer operates for all of them.

The forces: the PRD stack is heavy (Zammad with Elasticsearch, Frappe with ERPNext, Temporal, Langfuse with ClickHouse, Zulip, Authentik) and the cluster's memory is small; team isolation (PRD 14.4) depends on NetworkPolicies actually being enforced, and on exactly one pod reaching the internet by host name; the demo runs on fake data but should still look like something a security reviewer would accept; and this is a solo build, so every extra controller is time not spent on the product.

Not deciding means features 9 to 11 each pick their own ingress, storage, secret and hostname approach, and the isolation proof (demo step 8) has nothing solid to stand on.

## Options considered

### Option 1: Reuse the existing platform, grow the workers, fence Ask Tessaro in

Use the cluster's Cilium, ingress-nginx, MetalLB, cert-manager, Longhorn, CNPG, Argo CD and Sealed Secrets as they are. Close the memory gap by growing the three worker VMs to 16 GiB. Deliver namespaces, policies and guards from this repo through one Argo CD Application inside a dedicated AppProject defined in the cluster repo. Keep the UIs private on a new wildcard hostname.

**Pros**:
- Nothing new to install, upgrade or learn before the first system goes in.
- Cilium's `toFQDNs` solves the proxy's host name egress cleanly.
- The AppProject fence limits what a mistake in this repo can do to the other tenants.
- Capacity fits the full PRD stack without cutting systems.

**Cons**:
- Ask Tessaro inherits the shared tools' upgrade schedule and failures, including the retired ingress-nginx.
- Sealed Secrets is not what PRD 14.3 and spec 0001 named, and sealed files cannot be decrypted locally.
- Two repos change, and the resize is manual Proxmox work.

### Option 2: Follow the PRD and spec 0001 to the letter

Add KSOPS to the shared Argo CD repo server with an age key, use CIDR egress for DeepSeek, expose the UIs through the existing cloudflared tunnel, and slim the stack (defer Seatsurfing and Snipe-IT, small heaps) instead of resizing.

**Pros**:
- Matches the written documents exactly; secrets can be decrypted on the laptop with SOPS.
- No Proxmox work.
- Public URLs make a demo possible from anywhere without the tailnet.

**Cons**:
- Patching the shared Argo CD repo server changes cluster wide tooling for one project.
- A CIDR list for DeepSeek breaks silently when its addresses change, and a plain NetworkPolicy cannot express a host name.
- Public sign in pages for six systems widen the attack surface for no demo benefit.
- Slimming still leaves the cluster at its limit, with no room to spread heavy services across nodes.

### Option 3: A separate environment for Ask Tessaro

Run a dedicated virtual cluster (for example vcluster) or a second small k3s cluster on new VMs, with its own ingress, certificates, storage and GitOps.

**Pros**:
- Total isolation from the other tenants; Ask Tessaro owns every tool version.
- A clean story: "the whole environment is in this repo."

**Cons**:
- Rebuilds everything the cluster already has, which is weeks of platform work before feature 9.
- A virtual cluster still shares the host's CNI and storage, so the isolation proof depends on the host anyway; a second real cluster needs hardware the homelab does not have spare.
- Doubles the operational load for a solo build.

## Rationale

Option 1 wins because the cluster already has the right building blocks, and they are the boring, proven ones: Cilium for policy, cert-manager for certificates, Longhorn for replicated storage, CNPG for Postgres, Argo CD for GitOps. The single real gap the investigation found is memory, about 12 GiB free against roughly 21 GiB of planned requests, and that is cheaper to fix with RAM than with architecture. Growing the workers to 16 GiB fits the whole PRD stack and leaves headroom to keep the heavy stateful services on different nodes, which PRD 14.2 asks for.

The isolation requirement shaped the two choices that depart from earlier documents. Cilium's `toFQDNs` is the only clean way to say "the proxy may reach `api.deepseek.com` and nothing else"; a CIDR list would be correct on the day it is written and wrong later. Sealed Secrets keeps PRD 14.3's intent (encrypted in git, decrypted only in the cluster) without patching a repo server every other tenant depends on. Losing local decryption is acceptable because local development already runs on `.env` and fakes.

Option 2's public exposure buys nothing a demo on the tailnet does not already give, and costs a larger attack surface. Option 3 is the right call only if the other tenants were hostile or the cluster were about to be rebuilt; neither is true, and it would delay feature 9 by weeks. The AppProject fence gets most of Option 3's safety at a tiny fraction of the cost: Ask Tessaro's Applications cannot write outside their 16 namespaces, and because the fence lives in the cluster repo, this repo cannot widen it.

Smaller calls made while writing the spec:

- **Baseline as a small Helm chart** rather than Kustomize: 16 namespaces of nearly identical objects come out of one values file, and the repo already lints and validates charts in `just check`. The runner up, Kustomize with one overlay per namespace, repeats the same four files sixteen times.
- **No CPU limits, memory requests always set**: on four small nodes, CPU limits cause throttling without protecting anything, while memory requests drive scheduling and quotas. The LimitRange gives every container a memory request even when a third party chart forgets.
- **Quota on `requests.memory` only**: it stops one system from crowding the cluster without blocking rollouts the way a tight limits quota would. The runner up, quotas on CPU and limits too, adds failures with little benefit at this size.
- **Namespaces never deleted by Argo CD**: an accidental Application deletion with cascade would otherwise wipe every database in that namespace.
- **The root `ask-tessaro` Application stays in project `default`**: it must create Application objects in `argocd`, which the `tessaro` project deliberately cannot.
- **Kube API egress through `toEntities: [kube-apiserver]`**: with Cilium replacing kube proxy, an `ipBlock` rule for the API server is unreliable; the entity rule is the documented Cilium way.

## Cluster inventory (read only, 2026-10-10)

Collected with `kubectl` through the Tailscale operator proxy (`k3sprox-operator.tail62ceef.ts.net`). The identity was a `system:masters` user, so the agent had full admin; only `get`, `describe`, `top` and `auth` commands were used.

**Cluster**
- Server `v1.36.5+k3s1`, client `v1.36.1`.
- Four nodes, not the three the PRD assumed:

| Node | Role | CPU | Memory | Ephemeral disk | Taints | Memory in use | Requests (CPU / memory) |
|---|---|---|---|---|---|---|---|
| `k3sprox-cp-0` | control plane, etcd | 2 | 3.8 GiB | 28 GiB | `control-plane:NoSchedule` | 2.0 GiB (51%) | 10% / 2% |
| `k3sprox-wkr-pve1-0` | worker | 4 | 7.8 GiB | 57 GiB | none | 3.4 GiB (43%) | 80% / 44% |
| `k3sprox-wkr-pve2-0` | worker | 4 | 7.8 GiB | 57 GiB | none | 3.1 GiB (40%) | 32% / 4% |
| `k3sprox-wkr-pve2-1` | worker | 4 | 7.8 GiB | 57 GiB | none | 3.5 GiB (44%) | 34% / 9% |

- Allocatable equals capacity on every node (no `system-reserved`). All nodes run Ubuntu 24.04.4 on amd64 with containerd 2.3.4. Node names suggest workers on two Proxmox hosts (`pve1`, `pve2`).

**Workloads**
- Namespaces in use: `argocd`, `cert-manager`, `cilium-secrets`, `cloudflared`, `cnpg-system`, `deployer-*` (4), `app-*` (12 deployer test apps, each with default deny), `ingress-nginx`, `longhorn-system`, `metallb-system`, `mool`, `n8n`, `provic`, `site`, `solutio`, `tailscale`, plus the Kubernetes defaults.
- None of the 16 planned Ask Tessaro namespaces exists, so there are no name clashes.
- `solutio` runs an ITSM app with Zitadel and two CNPG databases; its app pods show about 3,500 restarts (last 27 days ago).

**Ingress and load balancing**
- IngressClasses: `nginx` (ingress-nginx controller 1.15.1, chart 4.15.1, two replicas) and `tailscale`.
- `ingress-nginx-controller` is a LoadBalancer Service at `172.16.70.40` (ports 80 and 443) from MetalLB pool `k3sprox-pool` (`172.16.70.40` to `172.16.70.79`, L2 advertisement). Cilium's LB IPAM is also enabled.
- A remotely managed cloudflared tunnel (token based) runs in `cloudflared` and `deployer-edge`.
- Existing hosts: `*.deploy.toyintest.org` (deployer apps), `argocd.k3s.local`, `longhorn.k3s.local`, `*.itsm.toyinog.com` (solutio), and several `*.tail62ceef.ts.net` Tailscale ingresses.

**Storage**
- StorageClasses: `longhorn` (default, 3 replicas), `longhorn-1r` (1 replica), `longhorn-static`; all `Immediate` binding, expansion allowed, reclaim `Delete`.
- Longhorn disks on the three workers: about 105 GB each, about 94 GB free, 135 GiB scheduled per node (every existing volume has 3 replicas), overprovisioning limit 200%, minimum free 25%.
- Ten existing volumes (n8n, solutio, zitadel, provic, mool, deployer), all 3 replicas, from 1 to 20 GiB.
- The CNPG operator (`ghcr.io/cloudnative-pg/cloudnative-pg:1.30.1`) runs in `cnpg-system`.

**Networking**
- CNI: Cilium 1.20.2 with cilium envoy, kube proxy replacement on, tunnel routing, Kubernetes NetworkPolicy enabled, policy mode `default`, L7 proxy and transparent DNS proxy on (so `toFQDNs` works), Hubble off.
- Existing policies: default deny in each deployer app namespace, and Argo CD's own policies (created about 4 hours before the inventory).
- Enforcement has not been tested yet; that is AC-6.
- `cilium-secrets`, CoreDNS, Sealed Secrets, ingress-nginx and the CNPG database pods were all recreated 4 to 5 hours before the inventory, so the cluster changed earlier the same day.

**Certificates and DNS**
- cert-manager with ClusterIssuers `letsencrypt-prod` and `letsencrypt-staging`, both using the ACME DNS01 solver through Cloudflare (`cloudflare-api-token`).
- A wildcard Certificate `*.deploy.toyintest.org` issued by `letsencrypt-prod`, so the token can write the `toyintest.org` zone.
- There is no external DNS controller, so DNS records are added by hand.

**Images**
- Nodes pull from `docker.io`, `quay.io`, `ghcr.io` and `registry.k8s.io` with no pull secrets in sight.
- An in cluster registry, `deployer-registry.deployer-system.svc:5000`, belongs to the deployer platform; Ask Tessaro does not use it.

**Tooling and GitOps**
- kubectl access through Tailscale with full admin. Helm is available locally.
- Argo CD runs an app of apps: `root` from `git@github.com:toyinogun/k3sprox-gitops.git` (path `apps`), with children for cert-manager, cloudflared, n8n, mool, provic, site, the CNPG operator, deployer and solutio. Argo CD Image Updater is installed.
- Secrets: Bitnami Sealed Secrets controller 0.40.0 in `kube-system`. KSOPS is not installed in the repo server.

**Outbound access**
- Nodes clearly reach the internet (public image pulls). Pod egress is checked by AC-7, because it needs a temporary pod, which is a write.
