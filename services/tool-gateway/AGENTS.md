# tool-gateway

## Overview

The single MCP door to every tool server: merges `tools/list`, checks OPA on every `tools/call`, forwards the caller's token and writes one audit line per call.

## Stack

- Python 3.13, FastAPI via `tessaro_core.create_app`, import name `tessaro_tool_gateway` (src layout)
- Dependencies: tessaro-core
- Listens on `8080` in the cluster; `just dev tool-gateway` serves it on `18084` locally

## Commands

```bash
just dev tool-gateway
uv run pytest services/tool-gateway/tests --cov=tessaro_tool_gateway -q
just image tool-gateway
```

## Conventions

- `main.py` exposes `build_app(settings)` for tests and `app` for uvicorn; settings live in `settings.py` (a `ServiceSettings` subclass).
- Release values: `deploy/values/tool-gateway.yaml`, rendered by the shared chart.
- Root `AGENTS.md` rules apply.

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
