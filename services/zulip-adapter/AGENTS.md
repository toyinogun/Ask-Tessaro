# zulip-adapter

## Overview

Receives Zulip messages, dedups and enqueues them to `stream:questions`, and posts answers from `stream:replies`. The only holder of Zulip credentials.

## Stack

- Python 3.13, FastAPI via `tessaro_core.create_app`, import name `tessaro_zulip_adapter` (src layout)
- Dependencies: tessaro-core
- Listens on `8080` in the cluster; `just dev zulip-adapter` serves it on `18081` locally

## Commands

```bash
just dev zulip-adapter
uv run pytest services/zulip-adapter/tests --cov=tessaro_zulip_adapter -q
just image zulip-adapter
```

## Conventions

- `main.py` exposes `build_app(settings)` for tests and `app` for uvicorn; settings live in `settings.py` (a `ServiceSettings` subclass).
- Release values: `deploy/values/zulip-adapter.yaml`, rendered by the shared chart.
- Root `AGENTS.md` rules apply.

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
