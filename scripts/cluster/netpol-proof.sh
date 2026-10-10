#!/usr/bin/env bash
# Prove on the live cluster that NetworkPolicies are enforced, that hostname egress works only
# where the shared chart allows it, and that sealed secrets are bound to their namespace
# (spec 0007 AC-6, AC-7). Prints one line per step; exits 0 only if every step passes.
# Touches nothing outside the two proof namespaces, which an EXIT trap deletes.
set -euo pipefail
# shellcheck source=scripts/cluster/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

NS=tessaro-netpol-proof
NS_B=tessaro-netpol-proof-b
CLIENT_RELEASE=proof-client
SEALED="$repo_root/deploy/secrets/$NS/netpol-proof.sealed.yaml"
SECRET_NAME=netpol-proof
SECRET_KEY=PROOF_VALUE
SECRET_VALUE=sealed-secrets-work
POLL_SECONDS=30
POLL_INTERVAL=2
STREAK=3
failures=0

require_context
for tool in helm yq; do command -v "$tool" > /dev/null || die "$tool is not installed"; done

cleanup() {
    kc delete namespace "$NS" "$NS_B" --ignore-not-found --wait=true --timeout=180s > /dev/null 2>&1 \
        || echo "warning: could not delete $NS / $NS_B, delete them by hand" >&2
}

report() { # report <PASS|FAIL> <step> <detail>
    printf '%-4s %-4s %s\n' "$1" "$2" "$3"
    [ "$1" = PASS ] || failures=$((failures + 1))
}

# probe <url>: the HTTP status the client sees, or 000 when it cannot connect.
probe() {
    kc -n "$NS" exec client -- curl -sS -m 5 -o /dev/null -w '%{http_code}' "$1" 2> /dev/null || true
}

# state <url>: "reachable" (any HTTP status), "blocked" (curl ran and printed 000: a timeout or
# refusal) or "error" (no output: curl never ran, e.g. the exec failed). An error never counts
# as blocked, so a dead client pod cannot pass a deny step.
state() {
    local code
    code="$(probe "$1")"
    if [[ "$code" =~ ^[1-5][0-9][0-9]$ ]]; then
        echo "reachable $code"
    elif [ "$code" = 000 ]; then
        echo "blocked"
    else
        echo "error (no curl output)"
    fi
}

resolves() { kc -n "$NS" exec client -- nslookup "$1" > /dev/null 2>&1; }

# expect <step> <url> <reachable|blocked> [status]: poll until the state appears, then require
# STREAK matching probes in a row.
expect() {
    local step="$1" url="$2" want="$3" code="${4:-}" got streak=0 deadline=$((SECONDS + POLL_SECONDS))
    while :; do
        got="$(state "$url")"
        if [ "${got%% *}" = "$want" ] && { [ -z "$code" ] || [ "$got" = "reachable $code" ]; }; then
            streak=$((streak + 1))
            if [ "$streak" -ge "$STREAK" ]; then report PASS "$step" "$url is $got"; return; fi
            continue
        fi
        streak=0
        if [ "$SECONDS" -ge "$deadline" ]; then
            report FAIL "$step" "$url is $got, expected $want${code:+ $code}"
            return
        fi
        sleep "$POLL_INTERVAL"
    done
}

expect_resolves() { # expect_resolves <step> <name>
    local deadline=$((SECONDS + POLL_SECONDS))
    until resolves "$2"; do
        if [ "$SECONDS" -ge "$deadline" ]; then report FAIL "$1" "$2 does not resolve"; return; fi
        sleep "$POLL_INTERVAL"
    done
    report PASS "$1" "$2 resolves"
}

client_manifest() {
    cat <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: client
  namespace: $NS
  labels: { app.kubernetes.io/name: $CLIENT_RELEASE }
spec:
  automountServiceAccountToken: false
  terminationGracePeriodSeconds: 1
  securityContext:
    runAsNonRoot: true
    runAsUser: 100
    runAsGroup: 101
    seccompProfile: { type: RuntimeDefault }
  containers:
    - name: curl
      image: $CLIENT_IMAGE
      command: [sleep, "3600"]
      resources: { requests: { memory: 16Mi, cpu: 10m }, limits: { memory: 32Mi } }
      securityContext:
        allowPrivilegeEscalation: false
        capabilities: { drop: [ALL] }
YAML
}

# Step d's second half: no Secret may appear in NS_B within the poll window.
expect_no_secret() {
    local deadline=$((SECONDS + POLL_SECONDS))
    while [ "$SECONDS" -lt "$deadline" ]; do
        if kc -n "$NS_B" get secret "$SECRET_NAME" > /dev/null 2>&1; then
            report FAIL d2 "the file sealed for $NS unsealed in $NS_B (scope is not strict)"
            return
        fi
        sleep "$POLL_INTERVAL"
    done
    report PASS d2 "the same sealed file gives no Secret in $NS_B (strict scope)"
}

expect_secret() {
    local deadline=$((SECONDS + POLL_SECONDS)) value
    until value="$(kc -n "$NS" get secret "$SECRET_NAME" -o "jsonpath={.data.$SECRET_KEY}" 2> /dev/null)" \
        && [ -n "$value" ]; do
        if [ "$SECONDS" -ge "$deadline" ]; then report FAIL d1 "no Secret $SECRET_NAME in $NS"; return; fi
        sleep "$POLL_INTERVAL"
    done
    if [ "$(printf '%s' "$value" | base64 -d)" = "$SECRET_VALUE" ]; then
        report PASS d1 "SealedSecret became Secret $SECRET_NAME with key $SECRET_KEY in $NS"
    else
        report FAIL d1 "Secret $SECRET_NAME holds an unexpected $SECRET_KEY"
    fi
}

echo "netpol proof on context $KUBE_CONTEXT, $(date -u +%Y-%m-%dT%H:%M:%SZ)"
wait_gone "$NS"
wait_gone "$NS_B"
trap cleanup EXIT
restricted_namespace "$NS"
{ server_manifest "$NS"; echo "---"; client_manifest; } | kc apply -f - > /dev/null
kc -n "$NS" wait --for=condition=Ready pod/server pod/client --timeout=120s > /dev/null
server_url="http://server.$NS.svc.cluster.local:8080/"

echo "# a: no policy"
expect a1 "$server_url" reachable 200
expect a2 https://api.deepseek.com reachable
expect a3 https://ghcr.io reachable

echo "# b: the baseline chart's default-deny and allow-dns"
helm template tessaro-baseline "$repo_root/charts/tessaro-baseline" \
    -f "$repo_root/scripts/cluster/fixtures/baseline-netpol-proof.yaml" \
    --show-only templates/networkpolicy.yaml | kc apply -f - > /dev/null
expect b1 "$server_url" blocked
# Fully qualified: busybox nslookup ignores the resolv.conf search list, so `kubernetes.default`
# gives NXDOMAIN even with no policy at all.
expect_resolves b2 kubernetes.default.svc.cluster.local
expect_resolves b3 example.com
expect b4 https://api.deepseek.com blocked

echo "# c: the shared chart's CiliumNetworkPolicy for egressFQDNs [api.deepseek.com]"
helm template "$CLIENT_RELEASE" "$repo_root/charts/tessaro-service" \
    -f "$repo_root/scripts/cluster/fixtures/egress-fqdn-proof.yaml" \
    --show-only templates/ciliumnetworkpolicy.yaml | kc apply -f - > /dev/null
expect c1 https://api.deepseek.com reachable
expect_resolves c2 example.com
expect c3 https://example.com blocked
expect c4 "$server_url" blocked

echo "# d: a SealedSecret is bound to its namespace"
kc apply -f "$SEALED" > /dev/null
expect_secret
restricted_namespace "$NS_B"
yq ".metadata.namespace = \"$NS_B\" | .spec.template.metadata.namespace = \"$NS_B\"" "$SEALED" \
    | kc apply -f - > /dev/null
expect_no_secret

if [ "$failures" -eq 0 ]; then
    echo "netpol proof: every step passed"
else
    echo "netpol proof: $failures step(s) failed, a blocking finding (PRD 14.2)" >&2
    exit 1
fi
