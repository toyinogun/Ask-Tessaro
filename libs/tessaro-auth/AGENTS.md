# tessaro-auth

## Overview

Token issue and verify for the identity token: Ed25519 JWTs per issuer, human and workflow worker kinds. Designed in [spec 0003](../../docs/specs/0003-identity-token-tool-contracts/index.md).

## Stack

- Python 3.13, import name `tessaro_auth` (src layout: `src/tessaro_auth/`, `tests/`)
- Dependencies: PyJWT (`pyjwt[crypto]`), cryptography, pydantic-settings, Starlette and structlog (the last two only in `edge.py`), tessaro-contracts (for `Scope` and the JSON export helpers)

## Commands

```bash
uv run pytest libs/tessaro-auth/tests --cov=tessaro_auth -q
uv run mypy libs/tessaro-auth/src libs/tessaro-auth/tests
just keys   # write dev keys into .env; changes nothing when all three are set
```

## Conventions

- `TOKEN_SIGNING_KEY` is used only where tokens are minted; everything else verifies with `TOKEN_VERIFY_KEYS` (a JWK set). `just keys` is the only writer of the dev keys and `TOKEN_VERIFY_KEYS` in `.env`.
- A key ID's prefix binds its kind and issuer (`adapter-*` signs human tokens, `worker-*` workflow worker tokens); verify keys are local only, never fetched or taken from the token.
- `verify` runs its checks in the fixed order of spec 0003 AC-7 and raises `TokenInvalid` with the first failure; services turn headers into a Principal through `principal_from_headers` only.
- Never log a token; log the rejection reason and the request ID.
- `verify` refuses a token longer than `MAX_TOKEN_LENGTH` (8 KiB) as `malformed` before parsing anything, and maps every parse failure (including `RecursionError`) to `TokenInvalid`.
- `TokenVerifySettings.keyset` and `TokenSigningSettings.signer` are cached per settings object: build settings once at startup and reuse them.
- `just dev` hands every service a copy of `.env` without the `DEV_*_SIGNING_KEY` lines; only a minter gets its own key, as `TOKEN_SIGNING_KEY`.
- `ROLE_SCOPES` in `roles.py` is the only source of OPA's `policy/role_scopes.json` (spec 0005); change the table, then run `just contracts`. Write scopes belong to `workflow_worker` only, and a test fails otherwise.
- Root `AGENTS.md` rules apply.

## Agent skills

- Declined: PyJWT, cryptography

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
