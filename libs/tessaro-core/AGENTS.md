# tessaro-core

## Overview

Shared service plumbing every service builds on: the `ServiceSettings` base, structlog setup, `X-Request-ID` handling, `/healthz` and `/readyz` routes, the httpx client factory and `create_app`.

## Stack

- Python 3.13, import name `tessaro_core` (src layout: `src/tessaro_core/`, `tests/`)
- Dependencies: fastapi, uvicorn, pydantic, pydantic-settings, httpx, structlog

## Commands

```bash
uv run pytest libs/tessaro-core/tests --cov=tessaro_core -q
uv run mypy libs/tessaro-core/src libs/tessaro-core/tests
```

## Conventions

- Public API is whatever `__init__.py` exports in `__all__`; services import from `tessaro_core`, never from submodules.
- Owns the cross service contracts (request ID, audit line shape); a change here touches every service, so keep it backward compatible.
- Root `AGENTS.md` rules apply.

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
