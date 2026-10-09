# authz

## Overview

The OpenFGA record access model: who may see an employee record or leave dates, and who may view or approve a lifecycle case. `model.fga` is the single source of truth. Governing spec: [docs/specs/0004-record-access-model/index.md](../docs/specs/0004-record-access-model/index.md).

## Layout

- `model.fga`: the model (types `user`, `org`, `team`, `employee`, `lifecycle_case`; the `within_window` condition for time boxed stand ins)
- `employee.fga.yaml`, `stand_in.fga.yaml`, `lifecycle_case.fga.yaml`, `mover.fga.yaml`: `fga model test` files, one per area, each check tagged with the AC it covers
- `.build/`: gitignored; seed tuples written by `just authz-test`

## Commands

```bash
just authz-test   # fga model validate, export tuples at the pinned anchor, fga model test on every *.fga.yaml
just authz-load   # local only: fresh store, load tuples, pin OPENFGA_STORE_ID and OPENFGA_MODEL_ID in .env (needs `just up`)
```

## Conventions

- `model.fga` matches the model block in spec 0004 line for line; change the spec first, then the file. `libs/tessaro-dataset/tests/test_fga_model.py` checks both this and the registry.
- Test files sit beside the model and start with `model_file: model.fga` and `tuple_file: .build/openfga.tuples.yaml`. Never use `../`: the `fga` CLI rejects paths that leave the test file's folder.
- Seed tuples come only from the dataset export. Inline `tuples:` in a test file hold only what a workflow writes: `lifecycle_case` `org`, `team` and `subject`, and a mover's second `employee` `team`.
- Every check passes `context: {current_time: ...}`; a stand in tuple checked without it errors instead of answering.
- The tests run at anchor `2027-03-15T10:00+01:00` with a 15 minute stand in, so the payments stand in window is `2027-03-13T08:00:00Z` to `2027-03-15T09:15:00Z` (start inclusive, end exclusive).
- Root `AGENTS.md` rules apply.

_Drafted by /sync from the introducing change, worth a quick human pass._
