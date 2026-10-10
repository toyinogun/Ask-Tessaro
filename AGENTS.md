# Ask Tessaro

AI employee service desk and lifecycle orchestrator for a fictional company. uv workspace monorepo: shared `libs/*`, one `services/*` package per isolation boundary.

## Stack

- **Language / Runtime**: Python 3.13 (pinned in `.python-version` and `requires-python`)
- **Framework**: FastAPI on uvicorn; MCP Python SDK (Streamable HTTP) for tool servers; LangGraph agent; Temporal workflows
- **Key dependencies**: pydantic + pydantic-settings, httpx (async), structlog (JSON, `audit=true` lines), OPA, OpenFGA, Presidio, Redis
- **Package manager / tasks**: uv workspace (one root `uv.lock`), `just` task runner; one shared Helm chart `charts/tessaro-service`
- Full decision: [docs/specs/0001-stack-architecture/index.md](docs/specs/0001-stack-architecture/index.md)

## Build approach

**Tracer Bullet**: prove the whole chain from Zulip to a team system works on one real question, then thicken it one strand at a time.

## Commands

```bash
just init        # .env from .env.example, uv sync --all-packages, install the pre-commit hooks
just up          # local deps in Docker (Redis, OpenFGA, OPA, Temporal, Presidio); `just down` stops them
just dev <svc>   # one service with hot reload, e.g. `just dev tool-gateway`
just fmt         # ruff fix + format
just check       # lint, typecheck, test (80% per package), policy, charts: what CI runs
just new-service <name> <namespace>   # stamp a service from templates/service
just keys        # write dev token keys and privacy proxy keys into .env, only the missing ones (also run by `just init`)
just contracts   # regenerate tool contract snapshots and the OPA data in policy/ (tools.json, role_scopes.json)
just contracts-check origin/main   # check contracts against the snapshots released on a base ref (CI, on PRs)
just dataset --anchor <iso>   # export the fictional company dataset to dataset/build/ (gitignored); the privacy proxy reads dataset/build/directory.json
just leak-scan   # privacy proxy leak scan against the real Presidio analyzer (after `just up`)
just policy      # opa fmt, opa check --strict and opa test at 100% coverage on policy/, then just authz-test
just authz-test   # validate authz/model.fga, export seed tuples to authz/.build, run every authz/*.fga.yaml (part of `just policy`)
just authz-load   # load the model and dataset tuples into local OpenFGA, then set OPENFGA_STORE_ID and OPENFGA_MODEL_ID in .env
just baseline    # lint and validate charts/tessaro-baseline; fails unless it renders exactly the 16 namespaces (part of `just charts`)
just seal <namespace> <name> <env-file>   # seal a git ignored dotenv file into deploy/secrets/<namespace>/<name>.sealed.yaml (offline, strict scope)
just netpol-proof   # live cluster: NetworkPolicy, hostname egress and sealed secret scope proof; append its output to docs/environment-report.md after each install step
just ingress-smoke [--prod]   # live cluster: DNS, ingress and certificate smoke test (`--prod` hits Let's Encrypt limits, run it rarely)
```

The live cluster recipes refuse to run unless `kubectl config current-context` equals `TESSARO_KUBE_CONTEXT` in `.env`. Cluster facts and decisions live in `docs/environment-report.md`.

## Specs

Stored in `docs/specs/`, one folder per decision: `docs/specs/NNNN-title/index.md`. Scope lives in `docs/scope/scope.md`.

## Rules

- Clean Architecture inside every package: domain logic is plain Python with no FastAPI, MCP, httpx or Redis imports; use cases orchestrate; adapters (routes, MCP tools, clients) sit at the edge and depend inward.
- Folder by feature under `src/tessaro_<name>/`: one module or subpackage per tool or capability, holding its models, logic and edge code together.
- Team systems are reached only through the typed client protocols in `tessaro-clients`; tests use the in memory fakes, real clients are integration tested on the cluster.
- Immutability: frozen pydantic models and dataclasses; return new objects, never mutate inputs.
- Types: `mypy --strict` with the pydantic plugin must pass; no `Any` without a comment saying why.
- Errors: typed exceptions in the domain, mapped once to HTTP or MCP errors at the edge; never swallow an error, log it with the request ID.
- Config: env vars only through a pydantic-settings class per service, failing fast at startup on a missing variable; never hardcode secrets.
- Docstrings on every public function, class and MCP tool (the tool docstring is the description the agent sees).
- Tests first (TDD): a failing pytest before the code; coverage at least 80% per package; Rego via `opa test`, OpenFGA via `fga model test`.
- Conventional commits (`feat:`, `fix:`, `docs:` ...), with no Claude or AI attribution lines in commits or PRs.

## Tooling

- Lint and format: ruff (config in root `pyproject.toml`). Types: mypy strict.
- Pre commit: `.pre-commit-config.yaml` runs ruff check, ruff format, mypy (`just typecheck`), `uv lock --check` and file hygiene on every commit. `just hooks` installs, `just hooks-all` runs them on every file.
- CI: `.github/workflows/ci.yml` runs `just check` on pushes to main, on PRs, and by hand (workflow_dispatch); on PRs it also runs `just contracts-check` against the base branch. Service image builds on main come later, with the cluster phase.

## Git

- integration: on
- branch prefix: feat/
- commit: per-milestone

## Agent skills

- [async-python-patterns](.claude/skills/async-python-patterns/): `wshobson/agents`, asyncio patterns for the async services
- [fastapi-templates](.claude/skills/fastapi-templates/): `wshobson/agents`, FastAPI service structure
- [langgraph-fundamentals](.claude/skills/langgraph-fundamentals/): `langchain-ai/langchain-skills`, the master agent graph
- [langgraph-persistence](.claude/skills/langgraph-persistence/): `langchain-ai/langchain-skills`, agent checkpoints and state
- [langchain-dependencies](.claude/skills/langchain-dependencies/): `langchain-ai/langchain-skills`, LangChain package choices
- [temporal-python-testing](.claude/skills/temporal-python-testing/): `wshobson/agents`, testing JML workflows
- [workflow-orchestration-patterns](.claude/skills/workflow-orchestration-patterns/): `wshobson/agents`, durable workflow design
- [redis-connections](.claude/skills/redis-connections/): `redis/agent-skills`, Redis client setup (pooling, timeouts, retries) for redis-py
- [helm-chart-scaffolding](.claude/skills/helm-chart-scaffolding/): `wshobson/agents`, the shared service chart
- [gitops-workflow](.claude/skills/gitops-workflow/): `wshobson/agents`, Argo CD app of apps in `deploy/`

## Context files

- [authz/AGENTS.md](authz/AGENTS.md): the OpenFGA record access model and its CLI test files
- [policy/AGENTS.md](policy/AGENTS.md): the OPA tool policy (Layer 1) and its generated data
- [libs/tessaro-core/AGENTS.md](libs/tessaro-core/AGENTS.md) (shared plumbing: settings, logging, request IDs, health, app factory)
- [libs/tessaro-auth/AGENTS.md](libs/tessaro-auth/AGENTS.md) (token issue and verify)
- [libs/tessaro-contracts/AGENTS.md](libs/tessaro-contracts/AGENTS.md) (typed, versioned tool contracts)
- [libs/tessaro-clients/AGENTS.md](libs/tessaro-clients/AGENTS.md) (team system client protocols and fakes)
- [libs/tessaro-dataset/AGENTS.md](libs/tessaro-dataset/AGENTS.md): the fictional company dataset, its validation and one exporter per team system
- [services/zulip-adapter/AGENTS.md](services/zulip-adapter/AGENTS.md) (Zulip in and out, Redis streams)
- [services/privacy-proxy/AGENTS.md](services/privacy-proxy/AGENTS.md) (LLM proxy with Presidio pseudonymisation)
- [services/master-agent/AGENTS.md](services/master-agent/AGENTS.md) (LangGraph read only agent)
- [services/tool-gateway/AGENTS.md](services/tool-gateway/AGENTS.md) (MCP gateway, OPA checks, audit)
- [services/tools-people/AGENTS.md](services/tools-people/AGENTS.md) (People tools on Frappe HR)

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
