# 0007. Rationale: cluster baseline

The decision record behind [index.md](index.md). `/develop` builds from the index; this file explains why, and keeps the inventory the decisions rest on.

## Context

Ask Tessaro moves from the laptop to a real k3s cluster. PRD 14.2 says nothing is installed until a read only investigation is written down, and that the report must end with decisions for ingress, storage, hostnames, certificates and capacity. Every later feature (9 to 16) installs into whatever this baseline lays down, so a wrong call here is paid for a dozen times.

The cluster is not empty and not dedicated. It is a shared homelab cluster running other projects (n8n, solutio (retired 2026-10-10, see *Build findings*), the deployer platform and its test apps, provic, mool, site) and its own platform tooling, managed from a separate GitOps repo. Anything Ask Tessaro does must not disturb those tenants, and anything it adds becomes something the engineer operates for all of them.

The forces: the PRD stack is heavy (Zammad with Elasticsearch, Frappe with ERPNext, Temporal, Langfuse with ClickHouse, Zulip, Authentik) and the cluster's memory is small; team isolation (PRD 14.4) depends on NetworkPolicies actually being enforced, and on exactly one pod reaching the internet by host name; the demo runs on fake data but should still look like something a security reviewer would accept; and this is a solo build, so every extra controller is time not spent on the product.

Not deciding means features 9 to 11 each pick their own ingress, storage, secret and hostname approach, and the isolation proof (demo step 8) has nothing solid to stand on.

## Options considered

### Option 1: Reuse the existing platform, grow the workers, fence Ask Tessaro in

Use the cluster's Cilium, ingress-nginx, MetalLB, cert-manager, Longhorn, CNPG, Argo CD and Sealed Secrets as they are. Close the memory gap by growing the three worker VMs (first planned at 16 GiB, revised to 12 GiB once the hosts were checked; see *Capacity revision*). Deliver namespaces, policies and guards from this repo through one Argo CD Application inside a dedicated AppProject defined in the cluster repo. Keep the UIs private on a new wildcard hostname.

**Pros**:
- Nothing new to install, upgrade or learn before the first system goes in.
- Cilium's `toFQDNs` solves the proxy's host name egress cleanly.
- The AppProject fence limits what a mistake in this repo can do to the other tenants.
- Capacity fits the full PRD stack without cutting systems.

**Cons**:
- Ask Tessaro inherits the shared tools' upgrade schedule and failures, including the retired ingress-nginx.
- Sealed Secrets is not what PRD 14.3 and spec 0001 named, and sealed files cannot be decrypted locally.
- Three repos change (this one, `k3sprox-gitops` and `terraform-proxmox-k3s`), and the hosts leave only modest headroom.

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

Option 1 wins because the cluster already has the right building blocks, and they are the boring, proven ones: Cilium for policy, cert-manager for certificates, Longhorn for replicated storage, CNPG for Postgres, Argo CD for GitOps. The single real gap the investigation found is memory, about 12 GiB free against roughly 21 GiB of planned requests, and that is cheaper to fix with RAM than with architecture. Growing the workers fits the whole PRD stack and leaves headroom to keep the heavy stateful services on different nodes, which PRD 14.2 asks for. The first plan said 16 GiB; checking the Proxmox hosts during the build cut that to 12 GiB (see *Capacity revision*).

The isolation requirement shaped the two choices that depart from earlier documents. Cilium's `toFQDNs` is the only clean way to say "the proxy may reach `api.deepseek.com` and nothing else"; a CIDR list would be correct on the day it is written and wrong later. Sealed Secrets keeps PRD 14.3's intent (encrypted in git, decrypted only in the cluster) without patching a repo server every other tenant depends on. Losing local decryption is acceptable because local development already runs on `.env` and fakes.

Option 2's public exposure buys nothing a demo on the tailnet does not already give, and costs a larger attack surface. Option 3 is the right call only if the other tenants were hostile or the cluster were about to be rebuilt; neither is true, and it would delay feature 9 by weeks. The AppProject fence gets most of Option 3's safety at a tiny fraction of the cost: Ask Tessaro's Applications cannot write outside their 16 namespaces, and because the fence lives in the cluster repo, this repo cannot widen it.

### Capacity revision (2026-10-10, during the build)

The first plan grew each worker to 16 GiB. When the build reached that step, a read only look at the two Proxmox hosts showed it cannot fit:

| Host | RAM | VMs (memory) | Available | Notes |
|---|---|---|---|---|
| `pve1` | 31 GiB | `k3sprox-cp-0` 4, `homeassistant` 4, `k3sprox-wkr-pve1-0` 8, `gh-runner-1` 8 (each using 90% or more) | 6 GiB | 1.3 GiB of swap in use; KSM sharing about 740 MiB |
| `pve2` | 31 GiB | `k3sprox-wkr-pve2-0` 8, `k3sprox-wkr-pve2-1` 8 | 12.5 GiB | no swap; host overhead about 2.5 GiB |

The first plan also overstated the other tenants: about 10 GiB was their working set (including page cache), while their memory requests, which the scheduler and the quotas count, are about 4.5 GiB (`k3sprox-wkr-pve1-0` 3.4 GiB, `k3sprox-wkr-pve2-0` 0.4 GiB, `k3sprox-wkr-pve2-1` 0.7 GiB).

Options weighed: leave `pve1` alone and grow only the `pve2` workers (about 29 GiB allocatable, about 3.5 GiB of headroom on requests); slim the stack to fit today's 8 GiB workers (cuts systems the PRD names); buy RAM (keeps 16 GiB but waits on hardware); or shrink `gh-runner-1` from 8 to 4 GiB and grow all three workers to 12 GiB. You chose the last: it keeps `pve1`'s committed total at today's 24 GiB, leaves about 3 GiB free on `pve2` (12 GiB rather than 13 GiB per worker, for QEMU overhead and spikes), and gives about 32 GiB allocatable, roughly 6 GiB above the other tenants' requests plus the 21 GiB budget. The quotas were trimmed from 35 to 31 GiB; they remain ceilings, deliberately larger in sum than the roughly 27.5 GiB left after the other tenants, while the 21 GiB of expected requests fits with room to spare. A cross check during the revision added the rollout safety rules now in AC-2 and build step 1 (the drop-in written without a restart, `kubelet-arg+`, the steady state host check, targeted plans that must show an in place update, drain flags and rollback order). It also offered growing only the `pve2` workers; that leaves about 2.4 GiB of headroom, too thin for this stack. The resize also moved from "manual Proxmox work" to the Terraform in `terraform-proxmox-k3s` that already manages the VMs, so the sizes live in code.

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

### Build findings (2026-10-10)

What the build found that the investigation did not, kept here so features 9 to 11 do not rediscover it. The facts and outputs are in `docs/environment-report.md`.

- **The tailnet had no route to the cluster.** The investigation assumed tailnet devices reached `172.16.70.0/24`. They did not: pfSense, the only subnet router, advertised `172.16.42.0/24` and `172.16.60.0/24`. pfSense now advertises `172.16.70.40/32`, the ingress IP alone, which is all the private UIs need and keeps the Proxmox hosts and nodes off the tailnet.
- **`argocd-cm` is owned by Terraform.** The Argo CD release is installed by `terraform-proxmox-k3s`, so the Application health check went into its Helm values, not into `k3sprox-gitops`.
- **`solutio` is gone.** Its CNPG WAL archive to R2 had returned 403 since 2026-10-09 (last good backup 2026-09-17), so after the drain its former primaries could not rejoin as replicas. Its owner retired it and it was removed with its volumes, which also frees about 60 GiB of Longhorn space (3 replicas each) and about 0.3 GiB of memory requests.
- **Draining needs care on this cluster.** Single instance CNPG clusters (`n8n-db`, `provic-pg`) block a drain through their primary PodDisruptionBudget, and draining the worker that runs the Tailscale operator cuts `kubectl`'s own connection. Both are now failure modes in `index.md`.
- **The runner job check moved to a follow up.** `toyinogun/pdf2` had not run since 2026-09-22, and forcing a run would also trigger its dev deploy, so AC-2 now requires the runners back `online` and the first real job is tracked as a follow up.
