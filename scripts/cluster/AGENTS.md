# scripts/cluster

## Overview

Bash scripts that prove the cluster baseline on the live cluster, and the offline sealing script. They are how spec 0007's acceptance criteria are checked again after each install step in features 9 to 11.

## Key files

| File | Owns |
|---|---|
| `lib.sh` | Shared helpers (sourced, never run): the context guard `require_context`, `kc`, pinned proof images, restricted namespace labels, leftover namespace cleanup |
| `netpol-proof.sh` | AC-6 and AC-7: pod to pod deny, DNS under default deny, hostname egress through the chart's CiliumNetworkPolicy, strict sealed secret scope |
| `ingress-smoke.sh` | AC-9: wildcard DNS, ingress-nginx and a cert-manager certificate for `smoke.tessaro.toyintest.org` |
| `seal.sh` | AC-10: dotenv file to `deploy/secrets/<namespace>/<name>.sealed.yaml`, offline, with the committed certificate |
| `crd_schemas.py` | Turns CRDs into the kubeconform schemas in `charts/schemas/` (`just schemas`) |
| `fixtures/` | Values files the proofs render charts with, and `fence-cluster-kind/` (a ClusterRole for the AppProject fence check) |
| `tests/seal_test.sh` | Offline tests for `seal.sh` |

## Commands

```bash
just netpol-proof           # live cluster; append its output to docs/environment-report.md under Proof history after each install step
just ingress-smoke          # live cluster, letsencrypt-staging
just ingress-smoke --prod   # letsencrypt-prod; 5 identical certificates a week, so run it rarely
just cluster-scripts        # shellcheck everything here and run tests/seal_test.sh (part of `just check`)
```

## Conventions

- Every script is `set -euo pipefail` and shellcheck clean. Live scripts call `require_context` first, which refuses to run unless `kubectl config current-context` equals `TESSARO_KUBE_CONTEXT` (environment, else `.env`), then pin every call to that context with `kc`.
- Live scripts write only into their own temporary namespaces (`tessaro-netpol-proof`, `tessaro-netpol-proof-b`, `tessaro-ingress-smoke`) and delete them in an `EXIT` trap. Nothing else on the shared cluster is touched.
- Proof images are pinned by version and digest in `lib.sh` and meet Pod Security `restricted`.
- A probe counts as reachable on any HTTP status and blocked on a timeout or refusal; after a policy change `netpol-proof.sh` polls and requires 3 matching probes in a row.
- The proofs render the real charts (`helm template` with a values file from `fixtures/`), so they test what ships, not a copy.
- `seal.sh` accepts only the 16 namespaces (from `charts/tessaro-baseline/ci/expected-namespaces.txt`) plus the two proof namespaces, refuses an env file inside the repo unless git ignores it, needs kubeseal 0.40.x, and leaves nothing behind on failure.
- Root `AGENTS.md` rules apply.

## Gotchas

- busybox `nslookup` ignores the resolv.conf search list, so look up fully qualified names (`kubernetes.default.svc.cluster.local`).
- `seal.sh` needs bash 4 or newer; macOS ships 3.2, so use Homebrew bash.
- `ingress-smoke.sh` needs kubectl 1.31 or newer (`kubectl wait --for=create`).
- The tailnet check of AC-9 is manual: from a tailnet device away from the LAN, `https://smoke.tessaro.toyintest.org` must get any answer from ingress-nginx.

## Related specs

- [0007 cluster baseline](../../docs/specs/0007-cluster-baseline/index.md): AC-6 to AC-10 define what these scripts prove

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
