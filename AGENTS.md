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
just init        # .env from .env.example, uv sync --all-packages
just up          # local deps in Docker (Redis, OpenFGA, OPA, Temporal, Presidio); `just down` stops them
just dev <svc>   # one service with hot reload, e.g. `just dev tool-gateway`
just fmt         # ruff fix + format
just check       # lint, typecheck, test (80% per package), policy, charts: what CI runs
just new-service <name> <namespace>   # stamp a service from templates/service
```

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
- Pre commit: `pre-commit` hooks run ruff check, ruff format and mypy on every commit (to install: `/develop tooling`).
- CI: GitHub Actions runs `just check` on every push and PR (to add: `/develop tooling`).

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
- [helm-chart-scaffolding](.claude/skills/helm-chart-scaffolding/): `wshobson/agents`, the shared service chart
- [gitops-workflow](.claude/skills/gitops-workflow/): `wshobson/agents`, Argo CD app of apps in `deploy/`

## Context files

- [libs/tessaro-core/AGENTS.md](libs/tessaro-core/AGENTS.md) (shared plumbing: settings, logging, request IDs, health, app factory)
- [libs/tessaro-auth/AGENTS.md](libs/tessaro-auth/AGENTS.md) (token issue and verify)
- [libs/tessaro-contracts/AGENTS.md](libs/tessaro-contracts/AGENTS.md) (typed, versioned tool contracts)
- [libs/tessaro-clients/AGENTS.md](libs/tessaro-clients/AGENTS.md) (team system client protocols and fakes)
- [services/zulip-adapter/AGENTS.md](services/zulip-adapter/AGENTS.md) (Zulip in and out, Redis streams)
- [services/privacy-proxy/AGENTS.md](services/privacy-proxy/AGENTS.md) (LLM proxy with Presidio pseudonymisation)
- [services/master-agent/AGENTS.md](services/master-agent/AGENTS.md) (LangGraph read only agent)
- [services/tool-gateway/AGENTS.md](services/tool-gateway/AGENTS.md) (MCP gateway, OPA checks, audit)
- [services/tools-people/AGENTS.md](services/tools-people/AGENTS.md) (People tools on Frappe HR)

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
