#!/usr/bin/env bash
# Smoke test the front door on the live cluster (spec 0007 AC-9): wildcard DNS, ingress-nginx
# and a cert-manager certificate for smoke.tessaro.toyintest.org, in a temporary namespace with
# the baseline policies plus the ingress controller allow. Deletes the namespace on exit.
#
# Usage: ingress-smoke.sh [--prod]
#   default  letsencrypt-staging; checks the Certificate is Ready and the URL answers 200 (curl -k)
#   --prod   letsencrypt-prod; also checks the certificate is trusted by the system store.
#            Let's Encrypt allows 5 identical certificates a week, so run it once, for the report.
# Needs kubectl 1.31 or newer (`kubectl wait --for=create`).
set -euo pipefail
# shellcheck source=scripts/cluster/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

NS=tessaro-ingress-smoke
HOST=smoke.tessaro.toyintest.org
TLS_SECRET=smoke-tls
CERT_TIMEOUT=300s
HTTP_SECONDS=90

issuer=letsencrypt-staging
prod=false
case "${1:-}" in
    "") ;;
    --prod) issuer=letsencrypt-prod prod=true ;;
    *) die "usage: just ingress-smoke [--prod]" ;;
esac

require_context
command -v helm > /dev/null || die "helm is not installed"

cleanup() {
    kc delete namespace "$NS" --ignore-not-found --wait=true --timeout=180s > /dev/null 2>&1 \
        || echo "warning: could not delete $NS, delete it by hand" >&2
}

ingress_manifest() {
    cat <<YAML
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-ingress-controller
  namespace: $NS
spec:
  podSelector:
    matchLabels: { app.kubernetes.io/name: server }
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels: { kubernetes.io/metadata.name: ingress-nginx }
          podSelector:
            matchLabels: { app.kubernetes.io/name: ingress-nginx }
      ports: [{ protocol: TCP, port: 8080 }]
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: smoke
  namespace: $NS
  annotations:
    cert-manager.io/cluster-issuer: $issuer
spec:
  ingressClassName: nginx
  tls:
    - hosts: [$HOST]
      secretName: $TLS_SECRET
  rules:
    - host: $HOST
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: { name: server, port: { number: 8080 } }
YAML
}

# expect_200 <curl flags...>: poll until https://HOST/ answers 200 or HTTP_SECONDS pass.
expect_200() {
    local code deadline=$((SECONDS + HTTP_SECONDS))
    while :; do
        code="$(curl -sS -m 5 -o /dev/null -w '%{http_code}' "$@" "https://$HOST/" 2> /dev/null || true)"
        [ "$code" = 200 ] && return 0
        [ "$SECONDS" -ge "$deadline" ] && { echo "last status: ${code:-none}" >&2; return 1; }
        sleep 3
    done
}

echo "ingress smoke on context $KUBE_CONTEXT with $issuer, $(date -u +%Y-%m-%dT%H:%M:%SZ)"
if command -v dig > /dev/null; then
    echo "DNS: $HOST -> $(dig +short "$HOST" | tr '\n' ' ')"
fi
wait_gone "$NS"
trap cleanup EXIT
restricted_namespace "$NS"
helm template tessaro-baseline "$repo_root/charts/tessaro-baseline" \
    -f "$repo_root/scripts/cluster/fixtures/baseline-ingress-smoke.yaml" \
    --show-only templates/networkpolicy.yaml | kc apply -f - > /dev/null
{ server_manifest "$NS"; echo "---"; ingress_manifest; } | kc apply -f - > /dev/null
kc -n "$NS" wait --for=condition=Ready pod/server --timeout=120s > /dev/null

started=$SECONDS
kc -n "$NS" wait --for=create "certificate/$TLS_SECRET" --timeout=60s > /dev/null \
    || die "cert-manager created no Certificate for the Ingress"
kc -n "$NS" wait --for=condition=Ready "certificate/$TLS_SECRET" --timeout="$CERT_TIMEOUT" > /dev/null \
    || { kc -n "$NS" describe certificate "$TLS_SECRET" >&2; die "Certificate not Ready within $CERT_TIMEOUT"; }
echo "PASS certificate $TLS_SECRET Ready from $issuer in $((SECONDS - started))s"

expect_200 -k || die "https://$HOST/ did not answer 200 (curl -k); check the DNS record and the ingress"
echo "PASS https://$HOST/ answers 200 (curl -k)"

if $prod; then
    expect_200 || die "https://$HOST/ is not trusted by the system certificate store"
    echo "PASS https://$HOST/ answers 200 with a certificate the system store trusts"
    echo | openssl s_client -connect "$HOST:443" -servername "$HOST" 2> /dev/null \
        | openssl x509 -noout -issuer -enddate || true
fi
echo "ingress smoke: every step passed"
