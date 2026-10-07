# tessaro-contracts

## Overview

Typed, versioned tool contract models shared by the gateway, tool servers and agent. Designed in the identity token and tool contracts spec (feature 4).

## Stack

- Python 3.13, import name `tessaro_contracts` (src layout: `src/tessaro_contracts/`, `tests/`)
- Dependencies: none yet

## Commands

```bash
uv run pytest libs/tessaro-contracts/tests --cov=tessaro_contracts -q
uv run mypy libs/tessaro-contracts/src libs/tessaro-contracts/tests
```

## Conventions

- Tool names are unique across all servers; the gateway refuses to start on a collision.
- Tool results report touched record IDs in `_meta.record_ids` so the gateway can audit them.
- Root `AGENTS.md` rules apply.

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
