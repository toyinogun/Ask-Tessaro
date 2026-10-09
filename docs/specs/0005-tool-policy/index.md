# 0005. Tool policy in OPA, with generated role scopes and a structured decision

**Date**: 2026-10-09
**Status**: In Progress

## Summary

This is Layer 1 of Tessaro's authorization: the OPA policy (Open Policy Agent, a small rules engine that runs next to the gateway) that decides whether a caller's roles may use a tool at all. The gateway verifies the token first, then sends OPA only the caller's kind, roles and the tool name, and gets back an allow flag plus the reasons for any denial. The role to scope table from PRD 8.2 becomes a typed Python table that generates the policy data, so a renamed role or scope fails CI instead of failing open. Human tokens can never use a write scope, whatever the data says.

## Requirements

**User stories**:
- As the gateway, I want one OPA query that says allow or deny for a tool call, with the reasons, so that I can enforce it and write why into the audit line (FR-G2, FR-G4).
- As the gateway, I want one OPA query that lists the tools a caller may call, so that `tools/list` shows the agent only what it can use.
- As a security reviewer, I want every human token denied every write scope by the policy itself, so that write access depends on the worker key and on this rule, not on the data alone (NFR-1).
- As a maintainer, I want the role to scope table to live in one typed place, so that the policy, the token roles and the contract scopes can't drift apart.

**Acceptance criteria** (the contract, each criterion is IDed and independently checkable). "Input" means the JSON document the gateway sends as `input`; "decision" means the value at `data.tessaro.gateway.decision`.

- **AC-1**: `ROLE_SCOPES` in `tessaro_auth.roles` maps every `Role` to a frozenset of `Scope`, exactly PRD 8.2 with Manager flattened: `employee` gets `it:read`, `hr:read`, `finance:read`, `workplace:read`, `kb:read`, `queue:handoff`, `workflow:read`; `manager` gets those seven plus `team:read`; `it_service_desk` gets `it:read_any`, `workflow:read_any`; `people_advisor` gets `hr:read_any`, `workflow:read_any`; `workflow_worker` gets `identity:write`, `it:write`, `workplace:write`, `hr:read_any`.
- **AC-2**: `just contracts` writes `policy/tools.json` (`{"tools": {<name>: {"owner", "scope", "version"}}}`, moved from `policy/data/tools.json`) and `policy/role_scopes.json` (`{"role_scopes": {<role>: [<scope>, ...]}}`, every role key present, each list sorted), both with sorted keys, two space indent and a trailing newline. `policy/data/tools.json` is moved with `git mv` and `policy/data/` no longer exists (the exporter never deletes files). `libs/tessaro-contracts/tests/test_snapshots.py` (via `TOOLS_DATA`) and the new `libs/tessaro-auth/tests/test_policy_export.py` each fail when their committed file, read through `repo_root`, differs from what the code generates now.
- **AC-3**: For a valid, consistent input naming a tool in `data.tools`, the decision is `{"allow": true, "reasons": []}` exactly when at least one input role's `role_scopes` entry holds the tool's scope and the scope is not a write scope used by a human. The demo case (kind `human`, roles `["employee"]`, tool `get_my_leave`) is allowed.
- **AC-4**: Otherwise the decision is `{"allow": false, "reasons": [...]}`, listing every reason that applies, sorted: `unknown_tool` (the tool is not in `data.tools`), `scope_not_granted` (the tool is known and no input role grants its scope), `write_needs_worker` (the tool's scope ends in `:write` and kind is not `workflow_worker`), `kind_role_mismatch` (see AC-6). Reasons combine: `kind_role_mismatch` is reported alongside the others, and a worker lacking a read scope gets `scope_not_granted` like anyone else. `scope_not_granted` and `write_needs_worker` are never reported for an unknown tool. The truth table under *Policy shape* is normative.
- **AC-5**: A human input is denied every write scope with `write_needs_worker`, for every role set, including a test where `data.role_scopes` is overridden to grant `employee` all three write scopes.
- **AC-6**: The decision carries `kind_role_mismatch` when kind is `human` and roles hold `workflow_worker`, or kind is `workflow_worker` and roles are not exactly the one element array `["workflow_worker"]`. Role order is irrelevant everywhere else; the policy accepts unsorted roles.
- **AC-7**: The principal is invalid when kind is not `human` or `workflow_worker`, or roles is not a non empty array of strings each a key of `data.role_scopes` with no duplicate. The tool is invalid when it is not a non empty string. An invalid principal, or an invalid tool on a `decision` query, gives exactly `{"allow": false, "reasons": ["invalid_input"]}`. An invalid principal gives an empty `allowed_tools`; the tool never affects `allowed_tools`. Both rules have defaults, so they are defined even when input is `{}` or absent entirely.
- **AC-8**: `data.tessaro.gateway.allowed_tools` is the sorted array of every tool name in `data.tools` whose decision for the same kind and roles (with that tool) would be allow. Input `tool` is ignored by this rule and may be absent or empty.
- **AC-9**: `policy/gateway_test.rego` covers every cell of the 5 role by 14 scope grid against the real generated `data.role_scopes`, with `data.tools` replaced by a fixture holding one tool per scope, named after it (`"it:read"` becomes tool `it_read`). Each of the four human roles runs with kind `human` and roles `[role]`; `workflow_worker` runs with kind `workflow_worker`. Each cell asserts the exact decision (allow and reasons) from the PRD 8.2 grid written out in the test. `just policy` runs `opa fmt --fail -l policy/`, `opa check --strict policy/` and `opa test policy/ -v --threshold 100` (line coverage of the policy at 100%), then `just authz-test`; CI runs it through `just check`.
- **AC-10**: Pytests in `libs/tessaro-auth/tests/` assert `ROLE_SCOPES` has a key for every `Role`; every `Scope` is granted to at least one role; write scopes appear only under `workflow_worker`; every `Scope` value appears in the Rego grid fixture (read from `policy/gateway_test.rego`); and every `Scope` is listed in a hand written `READ_SCOPES` or `WRITE_SCOPES` set that agrees with `Scope.is_write`, so a new scope must be classified on purpose.
- **AC-11** (manual check, also in the PR test plan): with `just up`, this request returns `{"result": {"allow": true, "reasons": []}}`, and the same request with `"tool": "nope"` returns `allow: false` with `["unknown_tool"]`:
  `curl -s -X POST localhost:8181/v1/data/tessaro/gateway/decision -d '{"input": {"kind": "human", "roles": ["employee"], "tool": "get_my_leave"}}'`

## Decision

**Chosen option**: Option 2: verified principal input, generated typed data, a structured decision and a flat policy folder.

The gateway sends `{kind, roles, tool}` from a token `tessaro-auth` already verified. OPA package `tessaro.gateway` returns `decision` (`allow` plus `reasons`) and `allowed_tools`, reading `data.tools` and `data.role_scopes`, which are generated from the contracts and from a typed `ROLE_SCOPES` table in `tessaro-auth`.

**Declined skills**: no Agent Skill or MCP server searched; this feature adds no new tool (OPA was chosen in spec 0001, and the Regal linter was declined).

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Feature design

**Files**:

```text
policy/gateway.rego          package tessaro.gateway: decision, allowed_tools, the deny reason helper
policy/gateway_test.rego     package tessaro.gateway_test: grid, deny reasons, invalid input, allowed_tools
policy/tools.json            generated by tessaro_contracts.export (moved from policy/data/tools.json)
policy/role_scopes.json      generated by tessaro_auth.policy_export
libs/tessaro-auth/src/tessaro_auth/roles.py          adds ROLE_SCOPES beside GROUP_TO_ROLE
libs/tessaro-auth/src/tessaro_auth/policy_export.py  `python -m tessaro_auth.policy_export [--root DIR]`, root defaults to repo_root(cwd), like the contracts export
libs/tessaro-auth/tests/test_policy_export.py        drift test (AC-2) and ROLE_SCOPES checks (AC-10)
libs/tessaro-auth/pyproject.toml                     adds the tessaro-contracts workspace dependency (uv.lock changes; `uv lock --check` guards it)
libs/tessaro-contracts/src/tessaro_contracts/export.py  TOOLS_DATA becomes policy/tools.json; the module docstring and the "wrote" message follow
libs/tessaro-contracts/tests/test_snapshots.py       follows TOOLS_DATA; check its paths still hold
justfile                     `contracts` also runs the auth export and its comment drops policy/data; `policy` runs the AC-9 commands with no "no Rego yet" guard
.pre-commit-config.yaml      a local hook `opa fmt --fail -l` with `files: \.rego$`
docs/scope/scope.md          feature 4's pointer line names `policy/data/`; update it to `policy/`
```

The folder is flat because OPA loads a JSON file at the path of its folder (a file in `policy/data/` lands at `data.data.*`, checked with `opa eval`), and a Kubernetes ConfigMap mounts as one flat folder. With every file at the root, `tools.json` lands at `data.tools`, `role_scopes.json` at `data.role_scopes`, and each file maps one to one to a ConfigMap key.

**Data model sketch** (documents, no database):

| Document | Shape | Source |
|---|---|---|
| `input` | `{kind: "human" \| "workflow_worker", roles: [Role], tool: str}`; extra keys are ignored | the gateway, from a verified principal (feature 13) |
| `data.tools` | `{<name>: {owner: str, scope: Scope, version: str}}` | `tessaro_contracts.export`, from `ToolContract` (spec 0003) |
| `data.role_scopes` | `{<role>: [Scope, ...]}`, all five roles, sorted lists | `tessaro_auth.policy_export`, from `ROLE_SCOPES` |
| `decision` | `{allow: bool, reasons: [Reason]}`; `allow` is true exactly when `reasons` is empty | Rego |
| `allowed_tools` | sorted array of tool names | Rego, same deny reason helper as `decision` |

`Reason` is one of `invalid_input`, `unknown_tool`, `scope_not_granted`, `write_needs_worker`, `kind_role_mismatch`.

**Policy shape** (Rego v1 syntax, the OPA 1.x default, so no `import rego.v1`):

- `valid_principal` holds when the AC-7 kind and roles conditions hold; `valid_tool(t)` holds when `t` is a non empty string.
- `deny_reasons(t)` is a function returning the set of reasons for the current kind and roles with tool `t`: `{"invalid_input"}` alone when the principal or `t` is invalid, otherwise the union of `unknown_tool`, `kind_role_mismatch`, and (for known tools only) `scope_not_granted` and `write_needs_worker`.
- `default decision := {"allow": false, "reasons": ["invalid_input"]}`, then `decision := {"allow": count(r) == 0, "reasons": sort(r)}` with `r := deny_reasons(input.tool)`. The default matters: a call with an undefined argument is itself undefined, so without it an absent `input.tool` would leave `decision` undefined (confirmed with `opa eval`).
- `default allowed_tools := []`, then `allowed_tools := sort([name | some name, _ in data.tools; valid_principal; count(deny_reasons(name)) == 0])`.
- A write scope is one whose value ends in `:write`, the same rule as `Scope.is_write` (spec 0003).
- `opa check --strict` rejects an unused function argument or variable, so every helper argument must be used on every branch (or named `_`).

Truth table for a valid principal and a valid tool string (reasons sorted in the output):

| Tool known | Kind and roles consistent | A role grants the scope | Write scope and kind `human` | Reasons |
|---|---|---|---|---|
| no | yes | n/a | n/a | `unknown_tool` |
| no | no | n/a | n/a | `kind_role_mismatch`, `unknown_tool` |
| yes | yes | yes | no | none, allowed |
| yes | yes | no | no | `scope_not_granted` |
| yes | yes | yes | yes | `write_needs_worker` (only reachable with doctored data) |
| yes | yes | no | yes | `scope_not_granted`, `write_needs_worker` |
| yes | no | any | any | `kind_role_mismatch` plus whichever of the two above apply |

**State transitions**: none. The policy is stateless; it changes only when `policy/` changes and OPA reloads it.

**API surface** (OPA's REST data API; the client is feature 13):

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/v1/data/tessaro/gateway/decision` | POST | `input.kind`, `input.roles`, `input.tool` | `result.allow`, `result.reasons` | none; the sidecar listens on localhost in the pod (spec 0001) | OPA down or a non 200: the gateway denies (fail closed, feature 13) |
| `/v1/data/tessaro/gateway/allowed_tools` | POST | `input.kind`, `input.roles` | `result` (array of names) | as above | as above; the gateway returns an empty list |
| `tessaro_auth.policy_export` | CLI | none | writes `policy/role_scopes.json` | developer, `just contracts` | non zero exit on a write failure |

**Value sourcing**:

| Action | Value produced / displayed | Source |
|---|---|---|
| decision | `input.kind` | the gateway: `human` for a `HumanPrincipal`, `workflow_worker` for a `WorkerPrincipal` (the `Kind` values, spec 0003) |
| decision | `input.roles` | the verified principal's `roles`, as a sorted list (spec 0003, AC-6) |
| decision | `input.tool` | the MCP `tools/call` request's `params.name` |
| decision | the tool's scope | `data.tools[tool].scope`, generated from `ToolContract.scope` |
| decision | the scopes a role grants | `data.role_scopes[role]`, generated from `ROLE_SCOPES` |
| decision | "is a write scope" | derived: the scope string ends in `:write` |
| decision | `allow` | derived: `reasons` is empty |
| allowed_tools | the candidate tool names | the keys of `data.tools` |
| audit line (feature 13) | the deny reasons | `result.reasons` from the decision |

**Key invariants**:
- No human input is ever allowed a write scope, whatever `data.role_scopes` holds.
- The decision is always defined, so an empty OPA result means OPA failed, never "no rule matched".
- `decision` and `allowed_tools` share one deny reason helper, so a listed tool is always a callable tool.
- `data.tools` and `data.role_scopes` are generated, never hand edited; drift fails CI.
- Policy input never holds an email, employee ID, workflow ID or token, so OPA sees no personal data.

**Security model**: OPA is Layer 1 (may this role call this tool at all); OpenFGA is Layer 2 (may this person see this record, spec 0004). Both must allow. The worker and human boundary rests on key custody first (spec 0003: only the worker key mints `workflow_worker`), then on `write_needs_worker` and `kind_role_mismatch` here. Be clear about the limit: OPA trusts `input.kind`. A gateway bug that sends a consistent `workflow_worker` input for a human would get writes, and nothing in OPA can tell. The mismatch check catches only mixed input; the real guard is key custody and the kid to kind binding in `tessaro-auth`, so the gateway must build `kind` from the principal's type, never from a claim it reads itself. Missing data fails safe: with no `role_scopes.json` every principal is invalid, and with no `tools.json` every tool is unknown. The input carries no personal data (GDPR scope, fictional data treated as real), and OPA decision logs stay off; the gateway's audit line, with the request ID and the reasons, is the single record of every decision (FR-G4). The sidecar is reachable only inside the gateway pod.

**Configuration required**: none new. `OPA_URL` is already fixed by spec 0001. Compose keeps `opa run --server --watch /policy`; OPA's decision logs are off by default and stay off.

**Dependencies**: `tessaro-auth` gains a workspace dependency on `tessaro-contracts` (pydantic only), to type `ROLE_SCOPES` with `Scope` and reuse `repo_root` and `render_json`. No new binary: OPA 1.21.1 is already pinned in Compose and CI.

**Critical test scenarios** (each maps to an acceptance criterion in ## Requirements):
- Happy path: a human employee calls `get_my_leave` and is allowed, in `opa test` and against the Compose OPA, verifies **AC-3**, **AC-11**
- Full grid: every role against a fixture tool for every scope matches the PRD 8.2 grid, verifies **AC-1**, **AC-9**
- Write from a human: an employee, a manager and an IT agent are denied `identity:write`, `it:write` and `workplace:write`, even with doctored role data granting them, verifies **AC-5**
- Forged mix: a human input with roles `["employee", "workflow_worker"]` is denied with `kind_role_mismatch`; a worker input with roles `["workflow_worker", "employee"]` likewise, verifies **AC-6**
- Several reasons at once: a human manager calling a known `it:write` tool gets `["scope_not_granted", "write_needs_worker"]`, verifies **AC-4**
- Unknown tool: `nope` gives only `["unknown_tool"]`, verifies **AC-4**, **AC-11**
- Garbage input: no `with input` at all, input `{}`, kind `admin`, roles `[]`, roles `["root"]` and roles `["employee", "employee"]` each give exactly `["invalid_input"]` and an empty `allowed_tools`; tool `""` with a valid employee gives `["invalid_input"]` for `decision` but the normal seven tool `allowed_tools`, verifies **AC-7**, **AC-8**
- Unsorted roles: `["manager", "employee"]` is valid and allowed `team:read`, verifies **AC-6**
- Listing: an employee's `allowed_tools` over the fixture data is exactly the seven employee scope tools; a worker's is exactly its four, verifies **AC-8**
- Drift: hand editing either generated JSON file fails pytest, verifies **AC-2**
- New scope: adding a 15th `Scope` member without classifying it or adding it to the Rego grid fails pytest, verifies **AC-10**

## Build plan

Ordered as a tracer bullet: one real allowed call through the real files and a real OPA first, then the deny paths, then the guards around it.

1. [x] Thin thread: add `ROLE_SCOPES` and `policy_export` (with the `tessaro-contracts` dependency), `git mv` the tools data to `policy/tools.json`, point `TOOLS_DATA` and every stale mention (see Files) at it, regenerate both files, write `gateway.rego` with `decision` for the allow path, one Rego test for the demo case, drop the "no Rego yet" guard from `just policy`, and check the Compose OPA by hand with the AC-11 request, satisfies **AC-1**, **AC-2**, **AC-3**, **AC-11**
2. [x] Deny reasons: `unknown_tool`, `scope_not_granted`, `write_needs_worker` and `kind_role_mismatch` through the shared `deny_reasons` helper, with their Rego tests including the doctored data case, satisfies **AC-4**, **AC-5**, **AC-6**
3. [x] Invalid input: `valid_principal`, `valid_tool`, both defaults, and the garbage input tests, satisfies **AC-7**
4. [x] Listing: `allowed_tools` on the same helper, with its tests, satisfies **AC-8**
5. [x] Grid and gates: the fixture tools, the full role by scope grid test, `opa fmt` and `opa check --strict` and 100% coverage in `just policy`, and the pre-commit `opa fmt` hook, satisfies **AC-9**
6. [x] Python guards: the drift test for `role_scopes.json` and the `ROLE_SCOPES` enum coverage test, satisfies **AC-2**, **AC-10**

## Consequences

**Positive**:
- One query per call and one per listing; the gateway stays a thin enforcer with no policy logic of its own.
- Every denial says why, so the audit log and the demo can explain a refusal.
- Role and scope names are typed end to end: tokens, contracts and policy data all come from the same enums.
- The policy fails closed on malformed input and on a kind and role mix that should be impossible.

**Negative / tradeoffs**:
- A scope revoked by editing `ROLE_SCOPES` reaches the cluster only by deploy, then after kubelet syncs the ConfigMap (about a minute) and OPA reloads. That is short of FR-G5's "immediately" for scopes, the same class of documented gap as spec 0003's role lag. Accepted for Phase 1.
- `tessaro-auth` now depends on `tessaro-contracts`, a new edge in the workspace graph; `tessaro-contracts` must never import `tessaro-auth` back.
- Moving `policy/data/tools.json` touches spec 0003's export, its tests and the contracts `AGENTS.md`.
- The input is deliberately minimal, so a future rule about a specific person (not role) needs an input change and a gateway change together.

**Neutral**:
- The grid test hard codes the PRD 8.2 table a second time, on purpose: it is the independent check on the generated data.
- `opa test` files sit in `policy/` and Compose loads them too; harmless locally, but the cluster ConfigMap should carry only `gateway.rego` and the two JSON files.

## Follow-up

- [x] Spec 0003 names `policy/data/tools.json` (Files, AC-18, Consequences); the path becomes `policy/tools.json` with this feature. Worth a one line update in 0003 when this ships.
- [ ] `libs/tessaro-contracts/AGENTS.md` mentions `policy/data/tools.json`; `/sync` should update it, and add a `policy/` context note once the Rego exists.
- [ ] Feature 13 (tool gateway): build the OPA input exactly as in Value sourcing, deny on any OPA error or missing `result`, and write `result.reasons` into the audit line.
- [ ] Feature 16 (assistant deploy): render the ConfigMap from `policy/gateway.rego`, `policy/tools.json` and `policy/role_scopes.json` only, excluding `*_test.rego`.
- [ ] The `*:read_any` record rule for IT agents and People advisors is still open (spec 0004 hands it to the IT tools feature); this spec only grants the scope.
