# privacy-proxy

## Overview

OpenAI compatible proxy in front of the LLM that pseudonymises personal data with Presidio and stores encrypted mappings in Redis.

## Stack

- Python 3.13, FastAPI via `tessaro_core.create_app`, import name `tessaro_privacy_proxy` (src layout)
- Dependencies: tessaro-core
- Listens on `8080` in the cluster; `just dev privacy-proxy` serves it on `18082` locally

## Commands

```bash
just dev privacy-proxy
uv run pytest services/privacy-proxy/tests --cov=tessaro_privacy_proxy -q
just image privacy-proxy
```

## Conventions

- `main.py` exposes `build_app(settings)` for tests and `app` for uvicorn; settings live in `settings.py` (a `ServiceSettings` subclass).
- Release values: `deploy/values/privacy-proxy.yaml`, rendered by the shared chart.
- Root `AGENTS.md` rules apply.

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
