# Verify: Tool policy · spec 0005 · updated 2026-10-09
_Steps derived from spec 0005 acceptance criteria. `/check verify` runs these; `/test` locks the durable ones._

## Commands
- [ ] `just policy` → `opa fmt`, `opa check --strict` clean; `opa test` all pass at 100% coverage; the OpenFGA tests pass → AC-9
- [ ] `uv run pytest libs/tessaro-auth/tests/test_policy_export.py -q` → all pass → AC-1, AC-2, AC-10
- [ ] `uv run pytest libs/tessaro-contracts/tests/test_snapshots.py -q` → all pass with `TOOLS_DATA` at `policy/tools.json` → AC-2
- [ ] `just contracts`, then `git status --short policy/` → nothing changed, and `policy/data/` does not exist → AC-2
- [ ] Hand edit one scope in `policy/role_scopes.json`, run the auth pytest → the drift test fails; then `git checkout policy/role_scopes.json` → AC-2
- [ ] Add a 15th member to `Scope` locally, run the auth pytest → the classification and Rego grid fixture tests fail; then revert → AC-10
- [ ] Flip one cell of `grid` in `policy/gateway_test.rego`, run `opa test policy/` → `test_prd_8_2_grid` fails; then revert → AC-9
- [ ] Add an unused rule to `policy/gateway.rego`, run `opa test policy/ --threshold 100` → non zero exit; then revert → AC-9

## Live OPA (manual, `just up` or `docker compose up -d opa`)
- [ ] `curl -s -X POST localhost:8181/v1/data/tessaro/gateway/decision -d '{"input": {"kind": "human", "roles": ["employee"], "tool": "get_my_leave"}}'` → `{"result":{"allow":true,"reasons":[]}}` → AC-3, AC-11
- [ ] Same request with `"tool": "nope"` → `allow: false`, `reasons: ["unknown_tool"]` → AC-4, AC-11
- [ ] Same request with `"roles": ["employee", "workflow_worker"]` → reasons include `kind_role_mismatch` → AC-6
- [ ] `curl -s -X POST localhost:8181/v1/data/tessaro/gateway/decision -d '{}'` → `allow: false`, `reasons: ["invalid_input"]` (a result, never empty) → AC-7
- [ ] `curl -s -X POST localhost:8181/v1/data/tessaro/gateway/allowed_tools -d '{"input": {"kind": "human", "roles": ["employee"]}}'` → `["get_my_leave"]` → AC-8
- [ ] Same listing with `"kind": "admin"` → `[]` → AC-7, AC-8

## Value sourcing
- [ ] `input.kind`: vary it between `human` and `workflow_worker` with roles `["workflow_worker"]` and a write tool → human gets `write_needs_worker` plus `kind_role_mismatch`; worker is allowed (Rego tests `test_worker_may_write`, `test_human_with_only_workflow_worker_is_a_mismatch`)
- [ ] `input.roles`: send `["manager", "employee"]` unsorted → valid and allowed `team:read` (`test_unsorted_roles_are_valid`)
- [ ] `input.tool`: absent, `""`, `5` → `invalid_input` on `decision`, listing unaffected (`test_invalid_tool`, `test_empty_tool_does_not_affect_the_listing`)
- [ ] The tool's scope comes from `data.tools`: with `data.tools` empty, a known tool becomes `unknown_tool` (`test_missing_tool_data_makes_every_tool_unknown`)
- [ ] The scopes a role grants come from `data.role_scopes`: with it empty, every principal is `invalid_input` (`test_missing_role_data_makes_every_principal_invalid`)
- [ ] "Is a write scope" is derived from the `:write` suffix: doctored data granting humans every write scope still gives `write_needs_worker` (`test_human_denied_writes_even_when_data_grants_them`)
- [ ] `allow` is derived from empty `reasons`: every listed tool is callable (`test_every_listed_tool_is_callable`)

## Acceptance-criteria coverage
- AC-1 … `test_role_scopes_match_prd_8_2`, grid test · AC-2 … drift tests, `test_policy_files_sit_flat_in_policy`, `just contracts` no diff · AC-3 … demo test, live curl · AC-4 … deny reason tests, live `nope` · AC-5 … the three human write tests · AC-6 … the mismatch and unsorted tests · AC-7 … invalid input tests, live `{}` · AC-8 … listing tests, live listing · AC-9 … `just policy`, grid mutation, coverage mutation · AC-10 … enum pytests, `Scope` mutation · AC-11 … the two live curls
