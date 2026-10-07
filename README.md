# Ask Tessaro

An AI employee service desk and lifecycle orchestrator for a fictional 2,400 person company, built as a portfolio reference on made up data. The product is described in [PRD.md](PRD.md); the stack decision is [spec 0001](docs/specs/0001-stack-architecture/index.md); the build plan is [docs/scope/scope.md](docs/scope/scope.md).

## Quick start (no cluster needed)

You need uv (0.12 or newer), just, Docker, Helm, kubeconform, opa and the OpenFGA CLI (`fga`).

```bash
just init      # create .env from .env.example and install every package
just up        # Redis, OpenFGA, OPA, Temporal dev server, Presidio analyzer
just dev tool-gateway   # run one service with hot reload on its local port
just check     # lint, typecheck, tests, policy tests, charts
```

## Local ports

| What | Port |
|---|---|
| zulip-adapter, privacy-proxy, master-agent, tool-gateway, tools-people | 18081 to 18085 |
| OpenFGA HTTP API | 18080 |
| OPA | 8181 |
| Temporal frontend / web UI | 7233 / 8233 |
| Presidio analyzer | 5002 |
| Redis | 6379 |

In the cluster every service listens on 8080.

## Layout

| Path | Holds |
|---|---|
| `libs/` | Shared libraries: `tessaro-core` (settings, logging, request IDs, health routes, httpx factory), `tessaro-auth`, `tessaro-contracts`, `tessaro-clients` |
| `services/` | One folder per service. Add one with `just new-service <name> <namespace>` |
| `templates/service/` | The skeleton `just new-service` copies |
| `charts/tessaro-service/` | The one shared Helm chart |
| `deploy/values/` | One values file per release |
| `policy/`, `authz/`, `bundles/`, `dataset/`, `evals/` | OPA policy, OpenFGA model, access bundles, the fictional dataset, evaluation suites (filled by later features) |
