# 0001. Python monorepo stack and architecture for Ask Tessaro's own services

**Date**: 2026-10-07
**Status**: Accepted

## Summary

Every service we write ourselves (Zulip adapter, master agent, privacy proxy, tool gateway, tool servers, JML intake, workflow worker) is Python 3.13. They live in one GitHub monorepo managed by uv (a fast Python package and workspace manager). Locally you run the supporting systems in Docker Compose and our services directly on your laptop, with in memory fakes standing in for the six team systems. That way all of Foundation (no cluster) works with no cluster at all. On the cluster, every service ships through one shared Helm chart (a reusable Kubernetes install template), deployed by Argo CD (a tool that keeps the cluster matching what is in git), with secrets encrypted in git by SOPS.

## Requirements

Decision spec: no acceptance criteria of its own. The scope feature's done line is the check for the scaffold that executes this decision: the stack is recorded here, and the empty repo builds, runs its (empty) tests locally, and renders its charts without a cluster.

## Decision

**Chosen option**: Option 1: Python uv monorepo, MCP everywhere, Compose locally, one shared chart, Argo CD

Build all of our own code as Python 3.13 packages in one uv workspace. Tool servers speak MCP over Streamable HTTP, behind an MCP aware gateway that is the single door for both agent reads and workflow writes. The adapter hands questions to the agent through a Redis Stream. Locally, Compose runs the dependencies and fakes replace the team systems. On the cluster, one shared Helm chart is deployed per service by Argo CD, with KSOPS decrypting SOPS secrets.

**Implementation skills**: `langgraph-fundamentals` · `langgraph-persistence` · `langchain-dependencies` (`langchain-ai/langchain-skills`) · `workflow-orchestration-patterns` · `temporal-python-testing` · `fastapi-templates` · `async-python-patterns` · `helm-chart-scaffolding` · `gitops-workflow` (`wshobson/agents`), all in `.claude/skills/`

## Rationale

Reasoning, options and evidence: see [rationale.md](rationale.md).

## Proposed stack

### Our code

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.13 for every service | Temporal SDK, LangGraph, Presidio and the MCP SDK are Python first. 3.13 is the safe overlap; 3.14 support across Presidio's spaCy models was not verified |
| Architecture pattern | Small services split along the PRD's isolation boundaries, one repo, one template | The split exists for security (per namespace NetworkPolicies, the "agent cannot reach Frappe" proof), not scale, so we keep the cost down with shared libs and one chart |
| Workspace and packages | uv workspace (≥ 0.12), one root `uv.lock` | Path dependencies on shared libs, atomic changes, one lockfile |
| Lint and format | ruff (≥ 0.16) | One fast tool for lint and format, configured once at the root |
| Type checking | mypy `--strict` with the pydantic plugin, gating CI | The most established strict checker, with first class pydantic support |
| HTTP services | FastAPI (≥ 0.142) on uvicorn | Pydantic models match the typed contracts; the MCP SDK's Streamable HTTP app mounts into it |
| Tool servers | Official MCP Python SDK (`mcp` ≥ 2.0), Streamable HTTP transport | PRD FR-T1 asks for MCP tools with typed, versioned contracts |
| Agent | LangGraph (≥ 1.1) with `langchain-mcp-adapters` as the MCP client and an OpenAI compatible chat client whose base URL is the privacy proxy | Fixed by the PRD (14.1, 11). The agent sees the gateway as one MCP server |
| Workflows | Temporal Python SDK (`temporalio`, latest 1.x at scaffold), one `jml-worker` service | Fixed by the PRD. Activities are thin calls to the gateway; team ownership lives in the tool servers |
| HTTP client | httpx (async) | Async, typed, and it pairs with respx for client tests later |
| Settings | pydantic-settings, environment variables only | One typed settings class per service; fails fast at startup on a missing variable |
| Logging and audit | structlog JSON to stdout; audit lines carry `audit=true` | A cluster log agent (Grafana Alloy) ships to Loki, so no service depends on Loki being up |
| Tests | pytest, pytest-asyncio, coverage ≥ 80% per package once it holds code (empty scaffold stubs are exempt) | Your global testing rule; native suites for Rego (`opa test`) and OpenFGA (`fga model test`) |
| Task runner | `just` | One `justfile`: `init`, `up`, `down`, `lint`, `typecheck`, `test`, `charts`, `check` (all of them) |

### Service to service shape

| Concern | Choice | Reason |
|---|---|---|
| Gateway | Implements only `tools/list` and `tools/call` over stateless Streamable HTTP (no sessions, resources, prompts or notifications). Upstreams come from a static `GATEWAY_UPSTREAMS` list. It merges `tools/list` (filtered by OPA for the caller), checks OPA on every `tools/call`, forwards the caller's `Authorization` header, and writes one audit line per call. Tool names are unique by contract; the gateway refuses to start on a collision | One door, protocol level enforcement, one audit trail (FR-G1 to G4), and the smallest MCP surface to keep in step with SDK upgrades |
| OPA | Sidecar next to the gateway (PRD 14.2 step 7). Policy and data are a ConfigMap rendered from `policy/`. The gateway reads `OPA_URL` (`http://localhost:8181` in the cluster, the Compose hostname locally) | Fixed by the PRD; one setting works in both modes; Rego stays testable on its own |
| Workflow writes | Also MCP tools, with `*:write` scopes, through the same gateway | The PRD's Rego rule already blocks human tokens from write scopes; one protocol to secure and log |
| Adapter to agent | The adapter dedups on the Zulip message ID (`SET NX`, 24 hour expiry), enqueues to `stream:questions`, and only then returns 200. The agent consumes with a consumer group; stuck messages are reclaimed (`XAUTOCLAIM`) up to 3 deliveries, after which the user gets an apology reply. The agent writes its answer to `stream:replies`, and the adapter posts it to Zulip (the adapter alone holds the Zulip credentials) | No question is lost between ack and enqueue; exactly one reply; survives pod restarts |
| Shared state | One Redis in the `assistant` namespace (a departure from PRD 14.2, which lists it under `platform`, because every user of it lives in `assistant`). AOF persistence on. One ACL user per service, limited to its prefixes: privacy-proxy `proxy:*`; zulip-adapter `adapter:*` and the streams; master-agent the streams only. The proxy encrypts mapping values with its own key (`PROXY_MAPPING_KEY`), so Redis never holds plain text | Keeps traffic inside one namespace; per service access matches default deny; FR-P4 encryption |
| Team systems | One typed client protocol per system, with an httpx implementation and an in memory fake loaded from the dataset | Fast, deterministic tests now; the real clients are proven against the cluster later |

### Cross service contracts (fixed in `tessaro-core`)

| Contract | Choice |
|---|---|
| Correlation | `X-Request-ID` is read or created at every entry point, forwarded on every outbound call, and bound into structlog context vars. It equals the token's request ID claim when one is present |
| Audit line | A typed model with the FR-G4 fields: `time`, `request_id`, `caller`, `on_behalf_of`, `roles`, `tool`, `record_ids`, `result`, `latency_ms`, plus `audit=true`. Tool results report the record IDs they touched in the MCP result `_meta.record_ids`, so the gateway can log them |
| Token keys | Env names fixed now: `TOKEN_SIGNING_KEY` (only where tokens are minted) and `TOKEN_VERIFY_KEY` (gateway and every tool server). `just init` writes a dev keypair to `.env`. The algorithm and claims are decided in the identity token spec (feature 4) |

### Repo layout

```text
/                        uv workspace root (pyproject.toml, uv.lock, justfile, compose.yaml, .env.example, renovate.json)
libs/
  tessaro-core/          settings base, structlog setup, health routes, httpx factory
  tessaro-auth/          token issue and verify (designed in the identity token spec, feature 4)
  tessaro-contracts/     typed, versioned tool contract models
  tessaro-clients/       per system client protocols, real clients, in memory fakes
services/
  zulip-adapter/  master-agent/  privacy-proxy/  tool-gateway/  tools-people/
  (later, from the template: tools-it, tools-finance, tools-workplace, tools-handbook, tools-identity, jml-intake, jml-worker)
templates/service/       copyable service skeleton (src layout, tests, Dockerfile, values file)
policy/                  OPA Rego + `opa test` files
authz/                   OpenFGA model + `fga model test` files
bundles/                 team access bundle YAML + JSON schema
dataset/                 fictional company dataset (feature 3)
evals/                   evaluation suites (feature 22)
charts/tessaro-service/  the one shared chart
deploy/
  values/<service>.yaml  one values file per release
  platform/              values for third party charts (cluster phase)
  argocd/                app of apps (cluster phase)
  secrets/               SOPS encrypted `*.enc.yaml` (cluster phase)
.github/workflows/       CI
```

Each service and lib uses the src layout (`src/tessaro_<name>/`, `tests/`). The Python import name is `tessaro_<name>`, with dashes becoming underscores.

### Service conventions

| Convention | Choice |
|---|---|
| Port | Every service listens on `8080` |
| Health | `GET /healthz` (process up) and `GET /readyz` (dependencies reachable) from `tessaro-core` |
| Image | `python:3.13-slim` multi stage, built from the repo root as context. The builder stage uses a pinned `ghcr.io/astral-sh/uv` tag and runs `uv sync --package <service> --locked --no-dev`, which pulls in the shared libs by path; the runtime stage copies the venv and runs as a non root user. The shell is kept for demo step 8. `.python-version` and `requires-python` pin 3.13 |
| Image tag | Git commit SHA. CI builds every service image on every `main` commit (layer cache keeps it fast), so no values file points at a tag that was never built: `ghcr.io/<owner>/tessaro-<service>:<sha>` |
| Config | Non secret config in a ConfigMap; secrets in a per namespace Secret; both read as env vars by pydantic-settings |

### Local dev loop (no cluster)

| Piece | Choice |
|---|---|
| Dependencies | `compose.yaml` runs Redis, OpenFGA (in memory store), OPA, the Temporal dev server (with its UI) and the Presidio analyzer |
| Our services | `uv run` with hot reload, started by `just` recipes; settings from a gitignored `.env` |
| Secrets | `.env.example` committed; `just init` creates `.env` and generates a dev only token signing key. No real secret is in git before the cluster phase |
| Team systems | In memory fakes from `tessaro-clients`, seeded from `dataset/` |

### Packaging and delivery (cluster phase)

| Layer | Choice | Reason |
|---|---|---|
| Code hosting and CI | GitHub (public repo) + GitHub Actions | Visible to reviewers; free CI |
| Image registry | GHCR | The k3s nodes pull public images with no credentials (confirmed in the cluster investigation) |
| Charts | One shared chart `charts/tessaro-service`: Deployment, Service, ServiceAccount, ConfigMap, NetworkPolicy, resource requests and limits, optional OPA sidecar. `namespace` is a required value; the chart never creates a Namespace (the cluster baseline does); the release name is the service name. Secrets are referenced by `existingSecret` name only, so rendering never needs SOPS | One chart to test; isolation applied identically to every service |
| NetworkPolicy values | A `values.schema.json` validated shape: `network.ingress[]` and `network.egress[]`, each `{namespace, podLabels, ports}`, plus `network.dns: true` and `network.egressCIDRs[]`. Every pod carries `app.kubernetes.io/name: <service>` as the one standard label. The proxy's DeepSeek egress uses `egressCIDRs` or a CNI specific policy, decided in the cluster investigation (feature 8) | A plain NetworkPolicy cannot allow a hostname, so the exception is explicit |
| Chart checks | `helm lint` + `helm template` piped to kubeconform, for every values file | Renders and validates with no cluster (the done line) |
| Deploy | Argo CD app of apps pointing at `deploy/argocd/`; each Application sets the destination namespace | Desired state lives in git and is diffable; the UI is demo friendly. Reuse Argo CD if the cluster investigation finds it |
| Secrets in the cluster | SOPS with age keys; KSOPS in the Argo CD repo server decrypts at sync time; plain Secrets land in each team's namespace | PRD 14.3; no extra operator or CRD; age keys live only in the `argocd` namespace |
| Dependency updates | Renovate, grouped weekly PRs | Handles uv lockfiles, Dockerfiles, Helm chart versions and Actions in one config |

### CI pipeline

On every PR: `uv sync --locked`, ruff check and format check, mypy strict, pytest with coverage gate, `opa test policy/`, `fga model test` on `authz/`, chart lint, render and kubeconform. On `main`: the same checks, then build and push every service image tagged with the SHA.

## Consequences

**Positive**:
- All of Foundation (no cluster) is buildable and testable on the laptop today.
- One language, one lockfile and one chart keep a ten service system manageable for one person.
- Every tool call, read or write, passes one gateway, one OPA rule and one audit format.

**Negative / tradeoffs**:
- Many deployables for a solo build: more images, values files and NetworkPolicies than a monolith. This is accepted because the isolation is the point of the demo.
- In memory fakes can drift from the real APIs. Each real client must be proven against the cluster before its feature is `done` (already the scope's rule).
- mypy strict slows early iteration on LangGraph and Temporal code, whose typings are loose in places. Expect targeted `# type: ignore[...]` lines with reasons.
- Argo CD and KSOPS add an in cluster controller to run and upgrade. helmfile would have been lighter.
- Making the gateway MCP aware means it must track the MCP spec version the SDK speaks; an SDK major bump touches the gateway and every tool server at once.

**Neutral**:
- No relational database of our own; all durable state lives in the off the shelf systems, Temporal and OpenFGA.
- The token format, OPA data shape and OpenFGA model are decided in their own specs (features 4, 5, 6); this spec only fixes where they live.

## Follow-up

- [ ] The repo is not yet under git. Run `git init`, create the public GitHub repo, and push before CI can run.
- [ ] Before pinning the MCP SDK, run a short spike: one tool server, the gateway passing `tools/list` and `tools/call` through, and the agent's `langchain-mcp-adapters` client, including the `Authorization` header forwarded on each call. If `mcp` 2.x or the adapters do not fit, pin `mcp<2` (v2 and the adapter versions were unverified today; reports differ on whether FastMCP is still built in).
- [ ] Feature 4 must decide who mints workflow worker tokens (recommended: a `tessaro-auth` function, with its signing key mounted only in the `workflows` namespace).
- [ ] Feature 8 decides how the proxy's internet egress to `api.deepseek.com` is allowed (CIDR or a CNI policy), and the cluster baseline adds the Redis and gateway paths to its allowed path table.
- [ ] Optional MCP servers worth connecting once the systems run on the cluster: Langfuse (official), Argo CD (`argoproj-labs/mcp-for-argocd`), OpenFGA (`evansims/openfga-mcp`, community), and a Grafana/Loki server. Connecting one is a step in your Claude Code MCP settings.
- [ ] Confirm `temporalio` and Presidio/spaCy wheels install on Python 3.13 at scaffold time (Python version support was unverified).
- [ ] Cluster investigation (feature 8) decides: whether Argo CD already exists, the ingress and storage classes, and whether nodes can pull from GHCR. Revisit the Deploy and Secrets rows if it finds something different.
- [ ] `/audit` (feature 2) should capture this stack's conventions (layout, ports, health routes, logging fields, `just` recipes) in root `AGENTS.md`, plus pre commit hooks, and list the nine installed skills in its `## Agent skills` section. Declined as off stack: the Azure, AWS, Firebase, Entra, BetterAuth and Grafana Mimir/Beyla skills.
