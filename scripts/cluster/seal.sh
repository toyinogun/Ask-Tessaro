#!/usr/bin/env bash
# Seal a dotenv file into deploy/secrets/<namespace>/<name>.sealed.yaml (spec 0007 AC-10).
# Uses only the committed controller certificate, so it needs no cluster access. Strict scope:
# the result decrypts only as Secret <name> in <namespace>; a rename means sealing again.
#
# Usage: seal.sh <namespace> <name> <env-file>
# The env file: one KEY=value per line, `#` comments and blank lines ignored, one pair of
# matching single or double quotes stripped, no multiline values.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cert="${SEAL_CERT:-$repo_root/deploy/secrets/sealed-secrets.pem}"
out_root="${SEAL_OUT_ROOT:-$repo_root/deploy/secrets}"
namespaces_file="$repo_root/charts/tessaro-baseline/ci/expected-namespaces.txt"
proof_namespaces=(tessaro-netpol-proof tessaro-netpol-proof-b)
kubeseal_series="0.40."

die() { echo "seal: $*" >&2; exit 1; }

[ "${BASH_VERSINFO[0]}" -ge 4 ] || die "bash 4 or newer is required (found $BASH_VERSION)"

[ "$#" -eq 3 ] || die "usage: just seal <namespace> <name> <env-file>"
namespace="$1" name="$2" env_file="$3"

allowed=false
while IFS= read -r ns; do
    [ "$ns" = "$namespace" ] && allowed=true
done < <(cat "$namespaces_file"; printf '%s\n' "${proof_namespaces[@]}")
$allowed || die "namespace '$namespace' is not an Ask Tessaro namespace"

if ! [[ "$name" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || [ "${#name}" -gt 253 ]; then
    die "'$name' is not a valid Secret name"
fi

[ -f "$env_file" ] || die "env file '$env_file' not found"
env_abs="$(realpath "$env_file")"
repo_real="$(cd "$repo_root" && pwd -P)"
case "$env_abs" in
    "$repo_real"/*)
        git -C "$repo_root" check-ignore -q "$env_abs" \
            || die "'$env_file' is inside the repo and not git ignored; move it out or ignore it"
        ;;
esac

command -v kubeseal > /dev/null || die "kubeseal is not installed (need ${kubeseal_series}x)"
version="$(kubeseal --version 2>&1 | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n1 || true)"
case "$version" in
    "$kubeseal_series"*) ;;
    *) die "kubeseal ${version:-unknown} found, need ${kubeseal_series}x" ;;
esac
[ -s "$cert" ] || die "certificate '$cert' is missing"

# Parse into KEY<TAB>base64 lines; base64 keeps any value safe inside YAML.
declare -A seen=()
data=""
line_no=0
while IFS= read -r line || [ -n "$line" ]; do
    line_no=$((line_no + 1))
    line="${line%$'\r'}"
    trimmed="${line#"${line%%[![:space:]]*}"}"
    [ -z "$trimmed" ] && continue
    [ "${trimmed:0:1}" = "#" ] && continue
    [[ "$line" == *=* ]] || die "line $line_no: expected KEY=value"
    key="${line%%=*}"
    value="${line#*=}"
    [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || die "line $line_no: '$key' is not a valid key"
    [ -z "${seen[$key]:-}" ] || die "line $line_no: duplicate key '$key'"
    seen[$key]=1
    first="${value:0:1}"
    if [ "$first" = '"' ] || [ "$first" = "'" ]; then
        if [ "${#value}" -lt 2 ] || [ "${value: -1}" != "$first" ]; then
            die "line $line_no: unmatched quote in '$key' (multiline values are not supported)"
        fi
        value="${value:1:${#value}-2}"
    elif [[ "$value" =~ ^[[:space:]]|[[:space:]]$ ]]; then
        die "line $line_no: '$key' has leading or trailing spaces; quote the value to keep them"
    fi
    [ -n "$value" ] || die "line $line_no: '$key' has an empty value"
    data+="  $key: $(printf '%s' "$value" | base64 | tr -d '\n')"$'\n'
done < "$env_file"
[ -n "$data" ] || die "'$env_file' holds no KEY=value lines"

out_dir="$out_root/$namespace"
created_dir=false
[ -d "$out_dir" ] || { mkdir -p "$out_dir"; created_dir=true; }
tmp="$(mktemp "$out_dir/.$name.XXXXXX")"
cleanup() {
    rm -f "$tmp"
    if $created_dir; then rmdir "$out_dir" 2> /dev/null || true; fi
}
trap cleanup EXIT

printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: %s\n  namespace: %s\ntype: Opaque\ndata:\n%s' \
    "$name" "$namespace" "$data" \
    | kubeseal --cert "$cert" --scope strict --format yaml > "$tmp"

mv "$tmp" "$out_dir/$name.sealed.yaml"
created_dir=false
echo "wrote ${out_dir#"$repo_root"/}/$name.sealed.yaml"
