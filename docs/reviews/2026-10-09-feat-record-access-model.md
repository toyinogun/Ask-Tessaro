# Review, feat/record-access-model, 2026-10-09

**Reviewed by**: Sonnet 5.5 (author on a different model)
**Scope**: 20 files, branch vs main
**Verdict**: Approve with nits

## Summary
The change adds the OpenFGA record access model, four CLI test files that load tuples exported from the dataset, the org level IT approver tuples, the registry drift test, `just authz-test` and `just authz-load`. I ran `just authz-test` (all 4 files pass, 449 checks), the dataset pytest suite (233 passed, 99 percent coverage) and mypy (clean). The model matches the spec line for line and I found no correctness or security defects. Only small robustness and housekeeping points remain.

## Minor
### 🟡 Each `just authz-load` leaves an orphaned store behind, `justfile:125`
**Problem**: A fresh store is created on every run and never removed. If the tuple write or the env step fails after the store is created, that store is left on the server with no record of it.
**Why it matters**: Local only and harmless, but repeated runs and failed runs pile up stores, which makes it hard to know which one is live.
**Suggested fix**: On failure after store creation, print the store ID in the error so it can be deleted, or delete it in the trap when the run did not finish.

### 🟡 A write of zero tuples counts as success, `libs/tessaro-dataset/src/tessaro_dataset/fgaload.py:78`
**Problem**: `check_tuple_write` only fails when `failed_count` is non zero. A `successful_count` of 0 passes, so an empty export would set the store and model IDs with no data loaded.
**Why it matters**: Callers would then pin a store that denies everyone, with no sign of why.
**Suggested fix**: Treat zero written tuples as a load error.

### 🟡 `.env` is rewritten in place, `libs/tessaro-dataset/src/tessaro_dataset/fgaload.py:114`
**Problem**: `write_text` truncates and rewrites the file. A crash mid write could damage `.env`, which also holds the dev token keys.
**Why it matters**: AC-11 promises `.env` is untouched on failure. That holds for every checked failure, but not for a failure during the write itself.
**Suggested fix**: Write to a temp file in the same folder and rename it over `.env`.

### 🟡 The `authz-load` shell logic has no automated test, `justfile:119`
**Problem**: The Python helper is well tested, but the recipe itself (health check, URL lookup, step order) is only covered by the manual steps in verify.md.
**Why it matters**: A later edit to the recipe could break the "`.env` untouched on failure" rule without any test failing.
**Suggested fix**: Accept it as a manual check for now, or add a small script test with stubbed `fga` and `curl`.

## Nits
- ⚪ `libs/tessaro-dataset/AGENTS.md`, does not mention `fgaload.py`, the `authz/` test folder or the `FGA_ORG` constant (a good job for `/sync`).
- ⚪ `libs/tessaro-dataset/src/tessaro_dataset/fgaload.py:1`, a CLI helper for OpenFGA loading sits in the dataset package; fine for now, but it is not really dataset logic.
- ⚪ `justfile:121`, `OPENFGA_API_URL` is read only from `.env`, so a value exported in the shell is ignored.
- ⚪ `docs/specs/0003-identity-token-tool-contracts/index.md:4`, the status change to Accepted is unrelated to this feature; fine, but it could be its own commit.

## Strengths
- The model file is checked line for line against the spec block, and the registry is checked against the model without needing the `fga` CLI, so drift is caught early.
- The tests cover the awkward edges: window start inclusive, window end exclusive, one second before the start, subjects who are also approvers, the mover with two teams, and a rule that every check carries `current_time`.
- `authz-load` fails fast on a dead server, double checks `fga tuple write` (which exits 0 on partial failure) and only then touches `.env`.

## Test coverage
Strong. 449 CLI checks across four files plus pytest for the parser, exporter, test file shape and `fgaload` (99 percent for the package; the only uncovered `fgaload` line is the `__main__` guard). The only untested new logic is the shell recipe for `authz-load`, noted above.
