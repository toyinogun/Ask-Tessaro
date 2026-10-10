# Vendored CRD schemas

JSON schemas for the custom resources `just check` validates with kubeconform, so the check needs
no network for them (spec 0007 AC-11). Generated from the cluster's own CRDs:

| Group | Kinds | Source version |
|---|---|---|
| `cilium.io` | CiliumNetworkPolicy | Cilium 1.20.2 |
| `bitnami.com` | SealedSecret | Sealed Secrets 0.40.0 |
| `argoproj.io` | Application, AppProject | Argo CD 3.5.4 |

Regenerate after a cluster upgrade with `just schemas` (needs the kube context in
`TESSARO_KUBE_CONTEXT`), then update the versions above.
