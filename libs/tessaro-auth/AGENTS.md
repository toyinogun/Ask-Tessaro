# tessaro-auth

## Overview

Token issue and verify for the identity token. Empty until the identity token spec (feature 4) decides the algorithm and claims.

## Stack

- Python 3.13, import name `tessaro_auth` (src layout: `src/tessaro_auth/`, `tests/`)
- Dependencies: none yet

## Commands

```bash
uv run pytest libs/tessaro-auth/tests --cov=tessaro_auth -q
uv run mypy libs/tessaro-auth/src libs/tessaro-auth/tests
```

## Conventions

- `TOKEN_SIGNING_KEY` is used only where tokens are minted; everything else verifies with `TOKEN_VERIFY_KEY`.
- Root `AGENTS.md` rules apply.

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
