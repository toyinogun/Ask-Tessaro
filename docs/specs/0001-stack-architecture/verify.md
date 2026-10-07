# Verify: Stack & architecture · spec 0001 · updated 2026-10-07
_Steps derived from the scope done line (spec 0001 is a decision spec with no ACs of its own; DONE = "the empty repo builds, runs its (empty) tests locally, and renders its charts without a cluster"). `/check verify` runs these; `/test` locks the durable ones._

## Commands
- [x] `uv sync --all-packages --locked` → succeeds with no lockfile change → DONE (builds)
- [x] `just lint` → ruff check and format check both clean → DONE (builds)
- [x] `just typecheck` → mypy strict reports no issues in each of the 9 packages → DONE (builds)
- [x] `just test` → every package passes with coverage at or above 80% → DONE (tests run)
- [x] `just charts` → helm lint passes and kubeconform reports every resource valid for `ci/test-values.yaml` and all 5 files in `deploy/values/`, with no cluster configured → DONE (charts render)
- [x] `helm template x charts/tessaro-service --set image.repository=a,image.tag=b` → fails with a schema error on `/namespace` (namespace is required) → DONE (charts render)
- [x] `just check` → exits 0 → DONE
- [x] `just image tool-gateway`, then run it and `curl localhost:<port>/healthz` → `{"status":"ok"}`, and `id` inside the container shows uid and gid 10001 → DONE (builds)

## UI / manual
- [x] `just init`, then `just up` → all five dependencies running; Redis and OpenFGA report healthy → local dev loop
- [x] `just dev tool-gateway`, then `curl -i localhost:18084/readyz -H "X-Request-ID: v-1"` → 200, body `{"status":"ready",...}`, response header `x-request-id: v-1` → local dev loop
- [x] `just new-service tools-demo tools-demo` → creates `services/tools-demo/` and `deploy/values/tools-demo.yaml`; after `uv lock`, `just check` still passes. Delete both afterwards → template works

## Acceptance-criteria coverage
- DONE (builds): sync, lint, typecheck, image steps · DONE (tests run): `just test` · DONE (charts render without a cluster): `just charts` and the schema check · Spec's local dev loop: `just up`, `just dev` · Template: `just new-service`
