# Ask Tessaro task runner. `just` lists the recipes; `just check` runs every check.

set shell := ["bash", "-euo", "pipefail", "-c"]

packages := `find libs services -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | tr "\n" " " || true`
values_files := `ls deploy/values/*.yaml 2>/dev/null | tr '\n' ' ' || true`
kube_version := "1.33.0"

default:
    @just --list

# Create .env from the template and install every package
init:
    @if [ -f .env ]; then echo ".env exists, leaving it alone"; else cp .env.example .env && echo "created .env from .env.example"; fi
    uv sync --all-packages --locked
    just keys
    uv run pre-commit install

# Write local dev token keys into .env (only when any of the three is missing or empty)
keys:
    uv run python -m tessaro_auth.devkeys --env-file .env

# Install the git pre-commit hooks (ruff, ruff format, mypy, file hygiene)
hooks:
    uv run pre-commit install

# Run every pre-commit hook against the whole repo
hooks-all:
    uv run pre-commit run --all-files

# Start the local dependencies (Redis, OpenFGA, OPA, Temporal dev server, Presidio)
up:
    docker compose up -d --wait

# Stop the local dependencies
down:
    docker compose down

# Run one service with hot reload on its local port, e.g. `just dev tool-gateway`
dev service port="":
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ service }}" in
        zulip-adapter) default=18081 ;;
        privacy-proxy) default=18082 ;;
        master-agent)  default=18083 ;;
        tool-gateway)  default=18084 ;;
        tools-people)  default=18085 ;;
        *)             default=18099 ;;
    esac
    port="{{ port }}"
    # Each minter gets only its own dev signing key, and no service sees the DEV_*_SIGNING_KEY
    # lines themselves: the service reads a copy of .env without them (spec 0003 AC-10).
    dev_key() { grep -E "^$1=" .env | tail -n1 | cut -d= -f2- || true; }
    case "{{ service }}" in
        zulip-adapter) export TOKEN_SIGNING_KEY="$(dev_key DEV_ADAPTER_SIGNING_KEY)" TOKEN_SIGNING_KID=adapter-1 ;;
        jml-worker)    export TOKEN_SIGNING_KEY="$(dev_key DEV_WORKER_SIGNING_KEY)" TOKEN_SIGNING_KID=worker-1 ;;
    esac
    env_file="$(mktemp)"
    trap 'rm -f "$env_file"' EXIT
    grep -v -E '^DEV_(ADAPTER|WORKER)_SIGNING_KEY=' .env > "$env_file" || true
    uv run --env-file "$env_file" --package {{ service }} uvicorn \
        "tessaro_{{ replace(service, "-", "_") }}.main:app" --reload --port "${port:-$default}"

# Export the fictional company dataset to dataset/build/ (gitignored), e.g. `just dataset --anchor 2026-10-07T10:00+02:00`
dataset *args:
    uv run tessaro-dataset export --out dataset/build {{ args }}

# Write contract snapshots (libs/tessaro-contracts/schemas/) and OPA data (policy/tools.json, policy/role_scopes.json)
contracts:
    uv run python -m tessaro_contracts.export
    uv run python -m tessaro_auth.policy_export

# Check the contracts against the snapshots released on a base ref (CI runs this on PRs), e.g. `just contracts-check origin/main`
contracts-check base="origin/main":
    #!/usr/bin/env bash
    set -euo pipefail
    git rev-parse --verify --quiet "{{ base }}^{commit}" > /dev/null || { echo "unknown base ref {{ base }}" >&2; exit 1; }
    base_dir="$(mktemp -d)"
    trap 'rm -rf "$base_dir"' EXIT
    if git cat-file -e "{{ base }}:libs/tessaro-contracts/schemas" 2> /dev/null; then
        git archive "{{ base }}" libs/tessaro-contracts/schemas | tar -x -C "$base_dir"
    fi
    uv run python -m tessaro_contracts.export --check-against "$base_dir/libs/tessaro-contracts/schemas"

# Ruff lint and format check
lint:
    uv run ruff check .
    uv run ruff format --check .

# Apply ruff fixes and formatting
fmt:
    uv run ruff check --fix .
    uv run ruff format .

# mypy --strict, one run per package so test module names never collide
typecheck:
    for p in {{ packages }}; do echo "mypy $p"; uv run mypy "$p/src" "$p/tests"; done

# pytest per package with an 80% coverage gate
test:
    for p in {{ packages }}; do \
        pkg="tessaro_$(basename "$p" | sed 's/^tessaro-//; s/-/_/g')"; \
        echo "pytest $p ($pkg)"; \
        uv run pytest "$p/tests" --cov="$pkg" --cov-fail-under=80 -q; \
    done

# OPA tool policy (spec 0005): format, strict check, tests at 100% line coverage; then the OpenFGA model tests
policy:
    opa fmt --fail -l policy/
    opa check --strict policy/
    opa test policy/ -v --threshold 100
    just authz-test

# OpenFGA model tests against tuples exported from the dataset at a fixed anchor (spec 0004)
authz-test:
    fga model validate --file authz/model.fga
    uv run tessaro-dataset export --out authz/.build --anchor 2027-03-15T10:00+01:00 --stand-in-minutes 15
    for t in authz/*.fga.yaml; do echo "fga model test $t"; fga model test --tests "$t"; done

# Load the model and today's dataset tuples into a fresh local OpenFGA store, then pin its IDs in .env
authz-load:
    #!/usr/bin/env bash
    set -euo pipefail
    api_url="$(grep -E '^OPENFGA_API_URL=' .env | tail -n1 | cut -d= -f2- || true)"
    if [ -z "$api_url" ]; then echo "authz-load: OPENFGA_API_URL is not set in .env" >&2; exit 1; fi
    # fga store create never times out on a dead server, so fail fast here instead
    if ! curl -fsS --max-time 5 "$api_url/healthz" > /dev/null; then
        echo "authz-load: OpenFGA is not answering at $api_url (run \`just up\` first)" >&2; exit 1
    fi
    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT
    uv run tessaro-dataset export --out "$work/export"
    fga store create --name tessaro --model authz/model.fga --api-url "$api_url" > "$work/store.json"
    ids="$(uv run python -m tessaro_dataset.fgaload ids --store-json "$work/store.json")"
    read -r store_id model_id <<< "$ids"
    fga tuple write --file "$work/export/openfga.tuples.yaml" --store-id "$store_id" \
        --model-id "$model_id" --api-url "$api_url" > "$work/write.json"
    uv run python -m tessaro_dataset.fgaload env --env-file .env \
        --store-json "$work/store.json" --write-json "$work/write.json"

# Lint the shared chart and validate it rendered with every release values file
charts:
    helm lint charts/tessaro-service --values charts/tessaro-service/ci/test-values.yaml
    for f in charts/tessaro-service/ci/test-values.yaml {{ values_files }}; do \
        echo "render $f"; \
        helm lint charts/tessaro-service --quiet --values "$f"; \
        helm template "$(basename "$f" .yaml)" charts/tessaro-service --values "$f" \
            | kubeconform -strict -summary -kubernetes-version {{ kube_version }}; \
    done

# Build one service image locally, e.g. `just image tool-gateway`
image service:
    docker build -f services/{{ service }}/Dockerfile -t tessaro-{{ service }}:local .

# Stamp a new service from templates/service, e.g. `just new-service tools-it tools-it`
new-service name namespace:
    #!/usr/bin/env bash
    set -euo pipefail
    pkg="tessaro_$(echo '{{ name }}' | tr '-' '_')"
    dest="services/{{ name }}"
    if [ -e "$dest" ]; then echo "$dest already exists" >&2; exit 1; fi
    mkdir -p "$dest"
    cp -R templates/service/src templates/service/tests templates/service/pyproject.toml templates/service/Dockerfile "$dest/"
    mv "$dest/src/__PKG__" "$dest/src/$pkg"
    mv "$dest/tests/test___PKG___health.py" "$dest/tests/test_${pkg}_health.py"
    sed "s/__SERVICE__/{{ name }}/g; s/__PKG__/$pkg/g; s/__NAMESPACE__/{{ namespace }}/g" \
        templates/service/values.yaml > "deploy/values/{{ name }}.yaml"
    find "$dest" -type f \( -name '*.py' -o -name '*.toml' -o -name 'Dockerfile' \) -print0 \
        | xargs -0 perl -pi -e "s/__SERVICE__/{{ name }}/g; s/__PKG__/$pkg/g"
    echo "created $dest and deploy/values/{{ name }}.yaml; run 'uv lock' next"

# Everything CI will run
check: lint typecheck test policy charts
