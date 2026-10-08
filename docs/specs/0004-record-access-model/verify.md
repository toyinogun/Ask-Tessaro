# Verify: Record access model · spec 0004 · updated 2026-10-08 (build)
_Steps derived from spec 0004 acceptance criteria. `/check verify` runs these; `/test` locks the durable ones._

## Commands
- [ ] `fga model validate --file authz/model.fga` → valid; the file matches the model block in the spec line for line      → AC-1
- [ ] `just authz-test` → `authz/.build/openfga.tuples.yaml` written, every `authz/*.fga.yaml` passes      → AC-10
- [ ] `just check` → lint, mypy strict, tests, policy (including the model tests) and charts all green      → every AC
- [ ] `uv run pytest libs/tessaro-dataset/tests --cov=tessaro_dataset -q` → all pass, coverage at least 80%      → AC-9
- [ ] Self access: `TES-01003` allowed `can_view_leave_dates` on `employee:TES-01003`, denied on `employee:TES-01004`      → AC-2
- [ ] Manager: `TES-01001` allowed on every payments employee's leave dates, denied `can_view_own_data` on `employee:TES-01003`      → AC-3
- [ ] Stand in: `TES-01002` on `employee:TES-01003` allowed at `2027-03-13T08:00:00Z` and `2027-03-15T09:10:00Z`, denied at `2027-03-13T07:59:59Z` and `2027-03-15T09:15:00Z`      → AC-4
- [ ] Cross team: `TES-01001` and `TES-01002` denied on `employee:TES-01011`; `TES-01007` (workplace stand in) denied on `employee:TES-01003` and on `joiner-TES-01042`; `TES-01022` denied on `employee:TES-01003` and on a payments case      → AC-5
- [ ] HR advisor: `TES-01018` allowed on `employee:TES-01003` and `employee:TES-01011`, denied on `employee:TES-01022`; allowed `can_view`, denied `can_approve` on a payments case      → AC-6
- [ ] Cases: on `joiner-TES-01042` `TES-01001` can approve, `TES-01012` can approve IT, `TES-01042` has nothing; on `mover-TES-01001-2027-03-22` `TES-01001` can view but not approve; on `joiner-TES-01002-2027-03-22` at `09:10Z` `TES-01002` can view but not approve; on `mover-TES-01012-2027-03-22` `TES-01012` can view but not approve IT      → AC-7
- [ ] Mover: with both team tuples on `employee:TES-01023`, `TES-01022` and `TES-01001` both see leave dates; only `TES-01001` approves the payments mover case      → AC-8
- [ ] Remove `define hr_advisor` from a scratch copy of the model the parser test reads → the registry test fails      → AC-9
- [ ] `grep -c "it_approver" authz/.build/openfga.tuples.yaml` → at least 1, every one on `org:tessaro`; no `lifecycle_case` object in the file      → AC-9
- [ ] With OpenFGA stopped, `just authz-load` → exits non zero, `.env` unchanged      → AC-11
- [ ] With OpenFGA stopped, `just authz-load` → fails within a few seconds with `OpenFGA is not answering`, never hangs (fga store create has no timeout of its own)      → AC-11
- [ ] `uv run python -m tessaro_dataset.fgaload env --env-file <copy of .env> --store-json <store create output> --write-json <a write output with "failed_count": 1>` → exit 1, the copy unchanged (fga tuple write exits 0 even when tuples fail)      → AC-11
- [ ] `just up` then `just authz-load` twice → two runs, `.env` holds one `OPENFGA_STORE_ID` and one `OPENFGA_MODEL_ID` line each, matching the second run's output; `fga query check --store-id … user:TES-01003 can_view_leave_dates employee:TES-01003 --context '{"current_time":"<now UTC>"}'` → allowed      → AC-11

## Value sourcing
- [ ] A check on a stand in tuple with no `current_time` in its context (`fga query check` against the loaded store) → an error or not allowed, never allowed      → value sourcing, deny on error
- [ ] Change the IT approver flag in a scratch dataset to `TES-01013` → the export's `org:tessaro` tuple follows      → value sourcing
