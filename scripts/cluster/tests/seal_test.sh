#!/usr/bin/env bash
# Tests for seal.sh (spec 0007 AC-10). Offline: seals with the committed certificate into a
# temporary output root. Run by `just cluster-scripts`.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/../../.." && pwd)"
seal="$repo_root/scripts/cluster/seal.sh"
work="$(mktemp -d)"
inrepo="$here/.tmp"
trap 'rm -rf "$work" "$inrepo"' EXIT
export SEAL_OUT_ROOT="$work/out"
failures=0

pass() { echo "ok   $1"; }
fail() { echo "FAIL $1" >&2; failures=$((failures + 1)); }

# expect_error <description> <message fragment> <seal args...>
expect_error() {
    local desc="$1" fragment="$2" output
    shift 2
    if output="$("$seal" "$@" 2>&1)"; then
        fail "$desc (exited 0)"
    elif [[ "$output" != *"$fragment"* ]]; then
        fail "$desc (got: $output)"
    else
        pass "$desc"
    fi
}

env_file() { printf '%b' "$2" > "$work/$1"; echo "$work/$1"; }

good="$(env_file good.env '# comment\n\nAPI_KEY=abc=def\nQUOTED="hello world"\nSINGLE='"'"'x'"'"'\n')"
if "$seal" assistant demo-secret "$good" > /dev/null; then
    out="$SEAL_OUT_ROOT/assistant/demo-secret.sealed.yaml"
    if grep -q 'kind: SealedSecret' "$out" \
        && grep -q 'sealedsecrets.bitnami.com/namespace-wide' "$out"; then
        fail "strict scope (found a namespace wide annotation)"
    elif grep -q 'kind: SealedSecret' "$out" && grep -q 'API_KEY:' "$out" \
        && grep -q 'QUOTED:' "$out" && grep -q 'SINGLE:' "$out" \
        && ! grep -q 'abc=def' "$out"; then
        pass "seals every key, encrypted, strict scope"
    else
        fail "sealed output is missing keys or holds plain text"
    fi
else
    fail "seals a valid env file"
fi
if "$seal" tessaro-netpol-proof-b demo "$good" > /dev/null; then
    pass "allows a proof namespace"
else
    fail "allows a proof namespace"
fi

expect_error "refuses a namespace outside the list" "not an Ask Tessaro namespace" default demo "$good"
expect_error "refuses a bad Secret name" "not a valid Secret name" assistant Bad_Name "$good"
expect_error "refuses a missing env file" "not found" assistant demo "$work/missing.env"
expect_error "refuses a duplicate key" "duplicate key" assistant demo \
    "$(env_file dup.env 'A=1\nA=2\n')"
expect_error "refuses a lowercase key" "not a valid key" assistant demo \
    "$(env_file lower.env 'api_key=1\n')"
expect_error "refuses an empty value" "empty value" assistant demo \
    "$(env_file empty.env 'A=\n')"
expect_error "refuses empty quotes" "empty value" assistant demo \
    "$(env_file emptyq.env 'A=""\n')"
expect_error "refuses an unmatched quote" "unmatched quote" assistant demo \
    "$(env_file multi.env 'A="line one\nline two"\n')"
expect_error "refuses unquoted trailing spaces" "trailing spaces" assistant demo \
    "$(env_file spaces.env 'A=abc \n')"
expect_error "refuses a line without =" "expected KEY=value" assistant demo \
    "$(env_file noeq.env 'JUSTAKEY\n')"
expect_error "refuses an env file with no pairs" "no KEY=value" assistant demo \
    "$(env_file blank.env '# only a comment\n')"

mkdir -p "$inrepo"
printf 'A=1\n' > "$inrepo/plain.txt"
expect_error "refuses an env file in the repo that git does not ignore" "not git ignored" \
    assistant demo "$inrepo/plain.txt"
printf 'A=1\n' > "$inrepo/.env"
ln -s "$inrepo/plain.txt" "$work/link.env"
expect_error "refuses a symlink to an in repo file git does not ignore" "not git ignored" \
    assistant demo "$work/link.env"
if "$seal" assistant from-repo "$inrepo/.env" > /dev/null; then
    pass "allows a git ignored env file in the repo"
else
    fail "allows a git ignored env file in the repo"
fi

mkdir -p "$work/bin"
printf '#!/usr/bin/env bash\necho "kubeseal version: v0.37.0"\n' > "$work/bin/kubeseal"
chmod +x "$work/bin/kubeseal"
PATH="$work/bin:$PATH" expect_error "refuses kubeseal outside 0.40.x" "need 0.40.x" \
    assistant demo "$good"

# shellcheck disable=SC2016 # the fake script's own $1, not ours
printf '#!/usr/bin/env bash\n[ "$1" = --version ] && { echo "v0.40.0"; exit 0; }\nexit 1\n' \
    > "$work/bin/kubeseal"
PATH="$work/bin:$PATH" expect_error "a failed seal" "" workflows broken "$good"
if [ -e "$SEAL_OUT_ROOT/workflows" ]; then
    fail "a failed seal leaves nothing behind"
else
    pass "a failed seal leaves nothing behind"
fi

[ "$failures" -eq 0 ] || { echo "$failures seal test(s) failed" >&2; exit 1; }
echo "all seal tests passed"
