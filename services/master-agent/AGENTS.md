# master-agent

## Overview

The read only LangGraph agent that answers employee questions by calling tools through the gateway as one MCP server.

## Stack

- Python 3.13, FastAPI via `tessaro_core.create_app`, import name `tessaro_master_agent` (src layout)
- Dependencies: tessaro-core
- Listens on `8080` in the cluster; `just dev master-agent` serves it on `18083` locally

## Commands

```bash
just dev master-agent
uv run pytest services/master-agent/tests --cov=tessaro_master_agent -q
just image master-agent
```

## Conventions

- `main.py` exposes `build_app(settings)` for tests and `app` for uvicorn; settings live in `settings.py` (a `ServiceSettings` subclass).
- Release values: `deploy/values/master-agent.yaml`, rendered by the shared chart.
- Root `AGENTS.md` rules apply.

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
