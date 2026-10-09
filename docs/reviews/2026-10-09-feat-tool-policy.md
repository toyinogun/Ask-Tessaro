# Review, feat/tool-policy, 2026-10-09

**Reviewed by**: Claude Sonnet (review subagent; author on Opus)
**Scope**: 17 files, branch vs main
**Verdict**: Approve with nits

## Summary
Adds Layer 1 OPA tool policy (`decision`, `allowed_tools`), a typed `ROLE_SCOPES` table with a generated `role_scopes.json`, the moved `tools.json`, and gates (`opa fmt`, `check --strict`, `--threshold 100`, pre-commit hook). I traced the Rego for fail-open paths and found none reachable from malformed input or principals: both rules are always defined, strict check is clean, 35/35 tests pass at 100% coverage. The one real gap is defense in depth against a tool entry with no `scope`.

## Minor
### 🟡 Tool entry without a scope is allowed for everyone, `policy/gateway.rego:53-61`
**Problem**: `scope_not_granted` and `write_needs_worker` both read `data.tools[t].scope`; if the key is absent, both are undefined, so no reason applies and `decision` is `{allow: true}` for any valid principal (verified with a hand-made `data.tools` entry `{"owner","version"}`; it also appears in `allowed_tools`). A non-string scope is denied (scope_not_granted), only a missing one fails open.
**Why it matters**: The spec promises that missing or bad data fails safe. Today the contracts exporter always writes a scope, so it needs a corrupted or hand-edited `tools.json` to trigger, and drift tests guard that. It is still the single fail-open edge in an authorization rule.
**Suggested fix**: Treat a known tool whose scope is missing or not a string as `scope_not_granted` (for example a `tool_scope(t)` helper and apply the reason when it is undefined), and add a Rego test.

### 🟡 `write_needs_worker` depends on the `:write` suffix convention, `policy/gateway.rego:59-62`
**Problem**: A future write scope not ending in `:write` would be treated as a read scope by OPA. Python `Scope.is_write` uses the same suffix, and AC-10 pins classification, so it is consistent today.
**Why it matters**: The "no human ever uses a write scope" invariant is only as strong as the naming rule.
**Suggested fix**: Add a pytest asserting every `Scope` value matches `^[a-z]+:(read|read_any|write|handoff)$`, or similar, so a new verb must be classified on purpose.

### 🟡 100% coverage gate counts the test file, `justfile` (policy recipe)
**Problem**: `opa test --threshold 100` measures all loaded Rego including `gateway_test.rego`, so the figure is diluted and does not prove every `gateway.rego` line is hit (currently true, 242/242).
**Suggested fix**: Optional; fine to leave since behaviour tests are dense. Consider checking per-file coverage for `policy/gateway.rego`.

### 🟡 CI log hides test names, `justfile` (policy recipe)
**Problem**: `opa test -v --threshold 100` prints only coverage JSON, so passing test names are not visible in CI. Exit code is correct.
**Suggested fix**: Run `opa test policy/ -v` first, then a second `opa test policy/ --threshold 100` (or `--coverage` with jq).

## Nits
- ⚪ `libs/tessaro-auth/tests/test_policy_export.py` (`test_every_scope_is_in_the_rego_grid_fixture`), substring match on `"scope"` could be satisfied by an unrelated occurrence; `test_grid_covers_every_scope_and_role` in the Rego already covers it more strictly.
- ⚪ `policy/gateway.rego:28-37`, `valid_principal` is re-evaluated per tool inside `allowed_tools` via `deny_reasons`; harmless at this size.
- ⚪ `libs/tessaro-auth/src/tessaro_auth/roles.py`, the `ROLE_SCOPES` docstring sits after the assignment (attribute docstring); fine, just unusual.

## Strengths
- Both rules are total (default plus an else branch), so an empty OPA result unambiguously means OPA failure; garbage input (non-object, wrong types, duplicates, unknown roles) is tested for both `decision` and `allowed_tools`.
- The PRD 8.2 grid is hand-written independently of `ROLE_SCOPES`, runs against the real `role_scopes.json`, asserts exact reasons, and is guarded by drift and scope-coverage tests in both languages.
- The human-write invariant is tested with doctored role data, and `kind_role_mismatch` is enforced in both directions.

## Test coverage
Rego: 35 tests, 100% line coverage, `opa check --strict` and `opa fmt` clean. Python: drift, enum coverage, write-scope placement, justfile and pre-commit wiring. Untested: the missing-scope tool entry (see Minor 1).
