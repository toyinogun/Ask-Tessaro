# Shared helpers for the cluster scripts (spec 0007). Sourced, never run.
# shellcheck shell=bash

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Pinned by version and digest; both meet Pod Security `restricted`.
SERVER_IMAGE="nginxinc/nginx-unprivileged:1.30.5-alpine-slim@sha256:3af0c10d960cc2502427fe1219c52989d309e7d65596869c60a34fd2fa2406f0"
CLIENT_IMAGE="curlimages/curl:8.21.0@sha256:7c12af72ceb38b7432ab85e1a265cff6ae58e06f95539d539b654f2cfa64bb13"
export SERVER_IMAGE CLIENT_IMAGE

die() { echo "$(basename "$0"): $*" >&2; exit 1; }

# Abort before touching anything unless the current context is TESSARO_KUBE_CONTEXT (from the
# environment, else .env). Every later call pins that context with `kc`.
require_context() {
    local want="${TESSARO_KUBE_CONTEXT:-}" have
    if [ -z "$want" ] && [ -f "$repo_root/.env" ]; then
        want="$(grep -E '^TESSARO_KUBE_CONTEXT=' "$repo_root/.env" | tail -n1 | cut -d= -f2- || true)"
    fi
    [ -n "$want" ] || die "TESSARO_KUBE_CONTEXT is not set (add it to .env)"
    have="$(kubectl config current-context 2> /dev/null || true)"
    [ "$have" = "$want" ] || die "current context is '${have:-none}', expected '$want'; refusing to run"
    KUBE_CONTEXT="$want"
}

kc() { kubectl --context "$KUBE_CONTEXT" "$@"; }

# Labels for a namespace on the `restricted` tier, like the baseline chart's `own` tier.
restricted_namespace() {
    kc create namespace "$1" --dry-run=client -o yaml \
        | kc label --local -f - -o yaml \
            app.kubernetes.io/part-of=ask-tessaro \
            pod-security.kubernetes.io/enforce=restricted \
            pod-security.kubernetes.io/enforce-version=latest \
            pod-security.kubernetes.io/audit=restricted \
            pod-security.kubernetes.io/warn=restricted \
        | kc apply -f - > /dev/null
}

# Remove a namespace left over from an earlier run (these names belong to the scripts), then
# wait until it is fully gone.
wait_gone() {
    local ns="$1" phase
    phase="$(kc get namespace "$ns" -o jsonpath='{.status.phase}' 2> /dev/null || true)"
    [ -n "$phase" ] || return 0
    echo "removing namespace $ns left over from an earlier run ($phase)"
    if [ "$phase" != Terminating ]; then kc delete namespace "$ns" --wait=false > /dev/null; fi
    kc wait --for=delete "namespace/$ns" --timeout=180s > /dev/null \
        || die "namespace $ns is still there after 180s; delete it by hand"
}

# An unprivileged nginx on 8080 with a Service, both named `server`.
server_manifest() {
    cat <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: server
  namespace: $1
  labels: { app.kubernetes.io/name: server }
spec:
  automountServiceAccountToken: false
  securityContext:
    runAsNonRoot: true
    runAsUser: 101
    seccompProfile: { type: RuntimeDefault }
  containers:
    - name: nginx
      image: $SERVER_IMAGE
      ports: [{ containerPort: 8080 }]
      readinessProbe: { httpGet: { path: /, port: 8080 }, periodSeconds: 2 }
      resources: { requests: { memory: 32Mi, cpu: 10m }, limits: { memory: 64Mi } }
      securityContext:
        allowPrivilegeEscalation: false
        capabilities: { drop: [ALL] }
---
apiVersion: v1
kind: Service
metadata:
  name: server
  namespace: $1
spec:
  selector: { app.kubernetes.io/name: server }
  ports: [{ port: 8080, targetPort: 8080 }]
YAML
}
