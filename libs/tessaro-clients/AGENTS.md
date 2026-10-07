# tessaro-clients

## Overview

One typed client protocol per team system, with a real httpx client and an in memory fake seeded from `dataset/`.

## Stack

- Python 3.13, import name `tessaro_clients` (src layout: `src/tessaro_clients/`, `tests/`)
- Dependencies: none yet

## Commands

```bash
uv run pytest libs/tessaro-clients/tests --cov=tessaro_clients -q
uv run mypy libs/tessaro-clients/src libs/tessaro-clients/tests
```

## Conventions

- Every protocol ships its fake in the same change; unit tests everywhere else use the fakes, never the network.
- Root `AGENTS.md` rules apply.

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
