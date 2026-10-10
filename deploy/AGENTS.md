# deploy

## Overview

Everything the cluster's Argo CD reads from this repo, plus the sealed secrets and release values. The root entry `ask-tessaro` and the AppProject `tessaro` live in `toyinogun/k3sprox-gitops`, not here, so this repo cannot widen its own permissions.

## Key files

| File | Owns |
|---|---|
| `argocd/` | One Argo CD Application per release, all in project `tessaro`; `ask-tessaro` syncs this folder from `main` |
| `argocd/tessaro-baseline.yaml` | The baseline chart release, sync wave `-10` so it lands before every sibling |
| `cluster-repo/ask-tessaro.yaml` | Reference copy of `apps/ask-tessaro.yaml` in `k3sprox-gitops`; nothing syncs it |
| `values/<service>.yaml` | Release values for `charts/tessaro-service`, one per service (stamped by `just new-service`) |
| `values/baseline.yaml` | The 16 namespaces with tier and memory quota |
| `secrets/sealed-secrets.pem` | The Sealed Secrets controller's public certificate (valid until 2036) |
| `secrets/<namespace>/<name>.sealed.yaml` | Strict scope SealedSecrets, written by `just seal` |
| `platform/` | Install files for off the shelf systems, one folder per system (features 9 to 11) |

## Commands

```bash
just seal <namespace> <name> <env-file>   # seal a dotenv file kept outside the repo or git ignored
just charts                                # validates every file here against charts/schemas/
kubectl -n argocd get application ask-tessaro tessaro-baseline   # Synced and Healthy after a merge to main
```

## Conventions

- Argo CD syncs `main`, so a change here goes live when it merges. Every Application sets `project: tessaro`, a destination namespace from the 16, `ServerSideApply=true`, and no `resources-finalizer.argocd.argoproj.io` finalizer.
- The `tessaro` project accepts only this repo as a source (plus pinned upstream chart repositories that later features add in `k3sprox-gitops`), only the 16 namespaces as destinations, and only `Namespace` at cluster scope.
- Never commit a plain Secret. Every secret is a SealedSecret bound to one namespace and one Secret name; renaming means sealing again.
- Each system's allow policies sit with its install (`platform/<system>/`, or the chart's `network` values); follow *Network conventions* in spec 0007.
- Editing `cluster-repo/ask-tessaro.yaml` means making the same change in `k3sprox-gitops` (and the other way round); nothing checks they match.
- Root `AGENTS.md` rules apply.

## Gotchas

- Image repositories in `values/` still say `ghcr.io/REPLACE_OWNER/...` with tag `scaffold`; CI sets the real tag once image builds land.
- Losing the controller's private key means sealing every secret again (backup is a spec 0007 follow up).

## Related specs

- [0007 cluster baseline](../docs/specs/0007-cluster-baseline/index.md): GitOps layout, the fence, sealed secrets, network conventions
- Cluster facts and decisions: [docs/environment-report.md](../docs/environment-report.md)

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
