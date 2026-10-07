# tools-people

## Overview

MCP tool server for People data in Frappe HR (first tool: my leave).

## Stack

- Python 3.13, FastAPI via `tessaro_core.create_app`, import name `tessaro_tools_people` (src layout)
- Dependencies: tessaro-core
- Listens on `8080` in the cluster; `just dev tools-people` serves it on `18085` locally

## Commands

```bash
just dev tools-people
uv run pytest services/tools-people/tests --cov=tessaro_tools_people -q
just image tools-people
```

## Conventions

- `main.py` exposes `build_app(settings)` for tests and `app` for uvicorn; settings live in `settings.py` (a `ServiceSettings` subclass).
- Release values: `deploy/values/tools-people.yaml`, rendered by the shared chart.
- Root `AGENTS.md` rules apply.

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
