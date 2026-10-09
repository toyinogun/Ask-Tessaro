# tessaro-contracts

## Overview

Typed, versioned tool contract models shared by the gateway, tool servers and agent. Designed in the identity token and tool contracts spec (feature 4).

## Stack

- Python 3.13, import name `tessaro_contracts` (src layout: `src/tessaro_contracts/`, `tests/`)
- Dependencies: pydantic only; never import the MCP SDK here (projections are plain dicts), and never import `tessaro_auth` (auth depends on contracts, not the other way)

## Commands

```bash
uv run pytest libs/tessaro-contracts/tests --cov=tessaro_contracts -q
uv run mypy libs/tessaro-contracts/src libs/tessaro-contracts/tests
just contracts   # regenerate schemas/<name>.json and policy/tools.json after a contract change
just contracts-check origin/main   # the version rule against the base ref's snapshots; writes nothing
```

## Conventions

- Tool names are unique across all servers; the gateway refuses to start on a collision.
- Tool results report touched record IDs in `_meta["tessaro/record_ids"]` so the gateway can audit them.
- One module per tool under its team folder (e.g. `people/get_my_leave.py`), registered in `registry.py` `ALL_CONTRACTS`; models are frozen with `extra="forbid"`.
- Committed snapshots in `schemas/` and `policy/tools.json` are generated, never hand edited; a test fails when they drift.
- Version rule (spec 0003 AC-19): an additive change bumps the minor; a breaking change ships as a new tool `<name>_v2`.
- A released tool is never removed or renamed: a snapshot in `schemas/` with no contract in the registry fails the rule.
- Tool server tests check their contracts with `testing.assert_contract_ok`, which fails when the schemas folder is missing.
- Root `AGENTS.md` rules apply.

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
