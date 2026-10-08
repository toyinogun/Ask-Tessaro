# Review, feat/identity-token-tool-contracts, 2026-10-08

**Reviewed by**: Sonnet 5.5 (fresh reviewer; author model not stated)
**Scope**: 46 files (uv.lock included), branch vs main
**Verdict**: Changes requested

## Summary
You added the Ed25519 token library (`tessaro-auth`) and the typed tool contract library (`tessaro-contracts`), plus `just keys`, `just contracts`, the first contract `get_my_leave` and the generated OPA tool data. The design follows spec 0003 closely, the security property that matters most (a worker kind token signed by the adapter key is refused) is built on key custody and tested, and the checks run in the spec's order. I ran the suite: 313 tests pass, coverage is 99% across both packages, ruff is clean and mypy strict is clean per package. One real bug stands out: a crafted token can make `verify` raise `RecursionError` instead of `TokenInvalid`, so the edge returns a 500 instead of the fixed 401.

## Major
### 🟠 A deeply nested token header or payload escapes as `RecursionError`, not `TokenInvalid`, `libs/tessaro-auth/src/tessaro_auth/verify.py:77`
**Problem**: `_json_object` catches `ValueError` and `UnicodeDecodeError` around `json.loads`, but a header such as `{"x":[[[[...]]]]}` nested a few thousand levels deep makes `json.loads` raise `RecursionError`, which is not a `ValueError`. I confirmed it by calling `verify` with a 100,000 deep header: it raised `RecursionError`. The header is read before any signature check, so an unauthenticated caller controls it, and a few thousand `[` characters fit in a normal request header.
**Why it matters**: AC-7 says the first failure raises `TokenInvalid`, and AC-11 says any failure at the edge becomes the same 401 with the fixed body. `principal_from_headers` only catches `TokenInvalid` (`edge.py:64`), so this input gives a 500 with a stack trace in the logs instead of a logged `token_rejected` and a 401. It fails closed (no access is granted), but it breaks the contract, skips the rejection audit line, and gives anyone without credentials a cheap way to produce server errors.
**Suggested fix**: Catch `RecursionError` next to `ValueError` in `_json_object` and map it to `malformed`. Consider also capping the token length (for example a few kilobytes) before parsing, and add a test with a deeply nested header and payload.

## Minor
### 🟡 `AliasChoices` on an input field slips past the self identity check, `libs/tessaro-contracts/src/tessaro_contracts/schema_rules.py:62`
**Problem**: `all_names` only collects aliases that are plain strings. A field declared with `validation_alias=AliasChoices("q", "employee_id")` is accepted at runtime under `employee_id`, but the JSON Schema shows only the first choice and the alias is not a `str`, so `_check_self_inputs` (`contract.py:136`) never sees it.
**Why it matters**: AC-13 exists so a `self` tool can never accept a person identifier (FR-T2). This is a contrived route, since a contract author has to write it on purpose, but the guard is meant to be airtight.
**Suggested fix**: Also walk `AliasChoices.choices` and `AliasPath` first elements, and add a test for it.

### 🟡 `just dev` hands every service both dev private keys, `justfile:53`
**Problem**: `uv run --env-file .env` loads the whole `.env`, including `DEV_ADAPTER_SIGNING_KEY` and `DEV_WORKER_SIGNING_KEY`, into every service. The comment, the spec and `.env.example` say each minter gets only its own key, but only the `TOKEN_SIGNING_*` mapping is per service. The gateway or a tool server run locally can read the worker key.
**Why it matters**: Local only, and the spec admits the shared `.env`. The statement "passes each service only its own key" is still not true as written, and a local gateway holding the worker key hides separation mistakes until the cluster.
**Suggested fix**: Either reword the comment and spec to say plainly that all dev keys are visible locally, or write a per service env file without the other minter's key and pass that to `--env-file`.

### 🟡 Settings re parse the key set on every property access, `libs/tessaro-auth/src/tessaro_auth/settings.py:25`
**Problem**: `TokenVerifySettings.keyset` runs `parse_jwks` (JSON parse and key construction) each time it is read, and `TokenSigningSettings.signer` rebuilds the key each time. The validator also parses once at startup, so the work is done twice before the first request.
**Why it matters**: A service that writes `principal_from_headers(headers, settings.keyset)` pays that cost on every request, on the auth hot path.
**Suggested fix**: Cache the parsed value once (a private attribute set in a model validator, or a cached property on the frozen settings) and document that services should read it once at startup.

### 🟡 Removing or renaming a released tool is not caught, `libs/tessaro-contracts/src/tessaro_contracts/export.py:58`
**Problem**: The compatibility check only loops over contracts that are in the registry. If a contract is deleted from `ALL_CONTRACTS`, `just contracts` regenerates `tools.json` without it, leaves the old `schemas/<name>.json` behind, and every test passes once `tools.json` is regenerated. The drift test is also parametrized only over files the registry still generates.
**Why it matters**: The spec invariant says a released tool name keeps a compatible contract forever, and removing the tool is the most breaking change there is. It also leaves an orphan snapshot nobody checks.
**Suggested fix**: Add a check that every committed snapshot has a matching contract in the registry, and fail with a message pointing at the `_v2` rule.

### 🟡 The version rule trusts the working tree snapshot, and the test helper passes silently when it cannot find one, `libs/tessaro-contracts/src/tessaro_contracts/testing.py:12`
**Problem**: CI compares the contract to the snapshot in the same checkout, so someone who edits the contract and hand edits or deletes the snapshot passes both tests; the version rule only truly bites inside `just contracts`. Separately, `PACKAGE_SCHEMAS` is computed from `__file__` and assumes the workspace layout. From an installed wheel the folder is missing and `assert_contract_ok` quietly skips the snapshot comparison, which the spec treats as "no snapshot yet, pass".
**Why it matters**: The user story is "a breaking contract change fails CI". Today that depends on the author running the tool honestly, and a moved path turns the check off without a sound.
**Suggested fix**: Add a CI step that diffs `schemas/` against the base branch (or compares against the snapshot from `main`), and make `assert_contract_ok` raise when the given `schemas_dir` does not exist instead of treating it as empty.

## Nits
- ⚪ `libs/tessaro-contracts/src/tessaro_contracts/schema_rules.py:197`, an output enum with the same values in a different order counts as "widened" (additive) instead of no change; compare as sets first.
- ⚪ `libs/tessaro-contracts/src/tessaro_contracts/mcp.py:24`, `_meta` carries four extra keys beyond the three AC-15 names (identity, authorization, never_returns, write). The docstring explains why, but the spec text and AC-15 should be updated to match.
- ⚪ `libs/tessaro-auth/src/tessaro_auth/keys.py:110`, `KeySet` is a frozen dataclass whose generated `__hash__` hashes a `MappingProxyType`, so `hash(keyset)` raises; set `eq=False` or drop the generated hash if it should be usable as a dict key.
- ⚪ `docs/specs/0003-identity-token-tool-contracts/index.md:4`, status still says "In Progress" while every build step is ticked and the scope table says shipped; update it when you finish `/sync`.

## Strengths
- The core security property rests on key custody: the kind and issuer are bound to the kid in the verifier's own key set, checked before any claim is trusted, with an explicit test for the adapter key signing a worker token (AC-8).
- `verify` is a clean, readable pipeline in the spec's exact order, uses PyJWT with a typed key object and `algorithms=["EdDSA"]` only, turns off PyJWT's own time checks, and runs leeway and lifetime logic in one place against an injected clock.
- Errors and secrets are handled with care: one fixed 401 body, the reason logged with the request ID, the token never logged, `Signer.__repr__` hides the key, `SecretStr` for the signing key, and settings that fail at startup.
- Contract validation is thorough and import time (`ContractError`), the breaking change classifier is conservative, and generated files have drift tests plus a refuse before write export.
- Code follows the project rules: frozen dataclasses and models, docstrings on public items, a justified `Any` where PyJWT forces one, and domain code free of FastAPI and MCP imports (Starlette and structlog only in `edge.py`).

## Test coverage
Strong. 313 tests, 99% coverage on both packages (only the `__main__` guards and two lines of base64 error handling are missed). Every verify step has its own test including ordering cases (audience before expiry, lifetime before expiry), the 660 second window, header member refusals, `alg=none` and HS256 confusion, mint refusals in order, edge logging and request ID binding, devkeys idempotence, and snapshot and version rule cases. The gaps are the ones above: nothing exercises hostile JSON shape (deep nesting), `AliasChoices` on an input field, or removal of a released contract.
