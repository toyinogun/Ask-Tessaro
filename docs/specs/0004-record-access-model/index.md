# 0004. Record access model in OpenFGA, with separation of duties and an org level IT approver

**Date**: 2026-10-08
**Status**: Accepted

## Summary

This spec fixes who may see or approve whose records, as one OpenFGA model (OpenFGA stores relationships such as "Maria manages Payments" and answers "may Maria see Lisa's leave dates?"). It keeps the PRD 8.3 model and adds two safety rules: nobody can approve their own joiner, mover or leaver case, and IT approvers are named once for the whole company instead of per case. The model is tested with OpenFGA's CLI test files that load tuples generated from the fictional dataset, so the model and the data can never disagree. This feature builds the model, its tests and a small dataset change; the Python code that calls OpenFGA comes with the first tool that needs it (feature 13).

## Requirements

**User stories**:
- As an employee, I want to see my own records and nobody else's, so that colleagues can't see my absences.
- As a manager, I want to see my team's leave dates and approve my team's joiners and movers, so that I can plan and onboard.
- As a manager going on holiday, I want a stand in to act for me only during a set window, so that their access ends on its own.
- As an HR advisor, I want leave dates for the teams I advise and no others, so that my access matches my job.
- As the security owner, I want nobody to approve their own lifecycle case, so that access can't be self granted.

**Acceptance criteria** (the contract, each criterion is IDed and independently checkable). "Seed tuples" means the tuples `export_openfga` writes from the dataset with the fixed test anchor `2027-03-15T10:00+01:00` and a 15 minute stand in window. Every check passes `current_time` in its context as a UTC timestamp.

- **AC-1**: `authz/model.fga` holds exactly the model in *Feature design* (schema 1.1; types `user`, `org`, `team`, `employee`, `lifecycle_case`; the `within_window` condition), and `fga model validate --file authz/model.fga` passes.
- **AC-2**: Self access. With seed tuples, every seeded employee `X` has `can_view_own_data` and `can_view_leave_dates` on `employee:X`. The persona `TES-01003` has neither on `employee:TES-01004` (a teammate; demo step 1).
- **AC-3**: Manager leave dates. Team manager `TES-01001` (payments) has `can_view_leave_dates` on every seeded payments employee and `can_view_own_data` on none of them except `employee:TES-01001`.
- **AC-4**: Time boxed stand in. `TES-01002`, stand in for payments, has `can_view_leave_dates` on payments employees and `can_approve` on payments cases only when `valid_from <= current_time < valid_until`. With seed tuples (window `2027-03-13T08:00:00Z` to `2027-03-15T09:15:00Z`): allowed at exactly `2027-03-13T08:00:00Z` (the start is inclusive) and at `2027-03-15T09:10:00Z`; denied at `2027-03-13T07:59:59Z` and at exactly `2027-03-15T09:15:00Z` (the end is exclusive).
- **AC-5**: Cross team attempts. Payments manager `TES-01001`, payments stand in `TES-01002` (inside its window), workplace stand in `TES-01007` (inside its window) and finance manager `TES-01022` have no `can_view_leave_dates` on any employee of a team they don't manage or stand in for (their own record aside; `TES-01007` sits in payments but is denied every payments teammate), and no `can_approve` or `can_view` on a case of such a team.
- **AC-6**: HR advisor scope. `TES-01018` (advises payments and it) has `can_view_leave_dates` on employees of payments and it, and none on employees of finance, people or workplace. It has `can_view` on a payments case, and never `can_approve` or `can_approve_it` on any case.
- **AC-7**: Lifecycle case approval with separation of duties. For a case with `team:T`, `org:tessaro` and `subject:S`: the manager of `T` and an active stand in of `T` have `can_approve` and `can_view`, unless they are `S`; the IT approver (`TES-01012`) has `can_approve_it` and `can_view`, unless it is `S`; being the subject grants nothing, so a subject with no other relation (the joiner `TES-01042`) has no `can_view`, and a subject who is also an approver keeps `can_view` but never `can_approve` or `can_approve_it`; everyone else has nothing. Tested with the fixture cases in *Feature design* (a joiner case for `TES-01042`, and synthetic payments cases whose subjects are the payments manager, the payments stand in, and the IT approver). A subject keeps any view they hold through another relation (the IT approver keeps `can_view` through `org`).
- **AC-8**: Mover. When `employee:TES-01023` has team tuples for both finance (old) and payments (new), both `TES-01022` and `TES-01001` have `can_view_leave_dates` on it. Its mover case on `team:payments` is approvable by `TES-01001` and not by `TES-01022`.
- **AC-9**: Dataset tuples match the model. `export_openfga` also writes `user:<id> it_approver org:tessaro` for every seeded employee (`seed_employees()`, like the other tuples) with `it_approver: true`, and still writes no `lifecycle_case` tuples. `ALLOWED_RELATIONS` and `CONDITIONED_RELATIONS` in `tessaro_dataset.registry` equal the directly assignable relations and their conditions parsed from `authz/model.fga`, checked by a pytest that needs no `fga` CLI.
- **AC-10**: Tests run from dataset tuples. `just authz-test` runs `uv run tessaro-dataset export --out authz/.build --anchor 2027-03-15T10:00+01:00 --stand-in-minutes 15` (the other target files it writes there are harmless) and then `fga model test --tests` on every `authz/*.fga.yaml`; each test file sits beside the model, loads `model.fga` and `.build/openfga.tuples.yaml` (paths relative to `authz/`, never `../`, because the `fga` CLI refuses file references that leave the test file's folder), and adds only workflow written tuples (the fixture cases, the mover's second team) inline. `just policy` calls `just authz-test` in place of its old inline `fga model test` loop, so `just check` and CI run it.
- **AC-11**: Local load. `just authz-load` exports the dataset at the current anchor, creates a fresh store with `fga store create --model authz/model.fga --api-url "$OPENFGA_API_URL"`, reads `store.id` and `model.authorization_model_id` from its JSON output, writes the tuples with `fga tuple write --file`, and only after every step succeeds sets `OPENFGA_STORE_ID` and `OPENFGA_MODEL_ID` in `.env` (replacing existing lines, appending otherwise) with a small Python helper, not sed. Any failed step exits non zero and leaves `.env` untouched. `.env.example` lists both, empty.

## Decision

**Chosen option**: Option 2: the PRD 8.3 model plus separation of duties and an org level IT approver.

Record access is one OpenFGA model with five types; a case's `subject` is excluded from approving it, IT approvers hang off `org:tessaro`, stand in access is a time window checked against the caller's clock, and every service pins the store and model ID it checks against.

**Declined skills**: no Agent Skill or MCP server searched; this feature adds no new tool (OpenFGA was chosen in spec 0001). The community `evansims/openfga-mcp` server stays a spec 0001 follow up.

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Feature design

**Files**:

```text
authz/
  model.fga                    the model (the single source of truth)
  employee.fga.yaml            self access, managers, HR advisors, cross team      AC-2, AC-3, AC-5, AC-6
  stand_in.fga.yaml            window inside, at the end, before the start          AC-4
  lifecycle_case.fga.yaml      approve, approve IT, view, self approval blocked     AC-5, AC-6, AC-7
  mover.fga.yaml               two team tuples, new manager approves                AC-8
  .build/                      gitignored; seed tuples written by `just authz-test`
libs/tessaro-dataset/src/tessaro_dataset/
  registry.py                  ALLOWED_RELATIONS, CONDITIONED_RELATIONS, FGA_ORG = "tessaro"
  exports/openfga.py           adds the org it_approver tuples
libs/tessaro-dataset/tests/
  test_fga_model.py            parses authz/model.fga and compares with the registry   AC-9
```

Each test file starts with `model_file: model.fga` and `tuple_file: .build/openfga.tuples.yaml`. The tests live beside the model, not in a `tests/` folder: `fga` v0.8.1 resolves file references inside the test file's own folder and rejects `../` ("path escapes from parent").

**Data model sketch** (the authorization model; types and relations, no database):

```text
model
  schema 1.1

type user

type org
  relations
    define it_approver: [user]

type team
  relations
    define member: [user]
    define manager: [user]
    define stand_in: [user with within_window]
    define hr_advisor: [user]
    define approver: manager or stand_in

type employee
  relations
    define owner: [user]
    define team: [team]
    define can_view_own_data: owner
    define can_view_leave_dates: owner or approver from team or hr_advisor from team

type lifecycle_case
  relations
    define org: [org]
    define team: [team]
    define subject: [user]
    define can_approve: approver from team but not subject
    define can_approve_it: it_approver from org but not subject
    define can_view: approver from team or hr_advisor from team or it_approver from org

condition within_window(current_time: timestamp, valid_from: timestamp, valid_until: timestamp) {
  current_time >= valid_from && current_time < valid_until
}
```

| Tuple (user, relation, object) | Written by | Cardinality and notes |
|---|---|---|
| `user:X owner employee:X` | dataset; joiner workflow | exactly one per employee |
| `team:T team employee:X` | dataset; joiner and mover workflows | one, or two during a move (PRD 9.3) |
| `user:X member team:T` | dataset; workflows | data only; no permission reads it yet |
| `user:M manager team:T` | dataset | one per team |
| `user:S stand_in team:T` with `within_window` | dataset; managers (Phase 2) | many; context `valid_from`, `valid_until` (RFC 3339) |
| `user:A hr_advisor team:T` | dataset | one or more per team |
| `user:I it_approver org:tessaro` | dataset (from `it_approver: true`) | new; one per IT approver |
| `org:tessaro org lifecycle_case:C` | workflow at case creation | new; exactly one per case |
| `team:T team lifecycle_case:C` | workflow at case creation | one; the new team for a mover |
| `user:X subject lifecycle_case:C` | workflow at case creation | new; exactly one per case |

**Fixture cases** (written inline in the test files, each with its `org:tessaro`, `team` and `subject` tuples, exactly as a workflow would):

| Case ID | Team | Subject | Extra tuples | Used by |
|---|---|---|---|---|
| `joiner-TES-01042` | payments | `TES-01042` (not seeded; a demo input) | none | AC-5, AC-6, AC-7 |
| `mover-TES-01023-2027-03-22` | payments (the new team) | `TES-01023` | `team:payments team employee:TES-01023` | AC-8 |
| `mover-TES-01001-2027-03-22` | payments | `TES-01001` (the payments manager) | none; synthetic | AC-7 |
| `joiner-TES-01002-2027-03-22` | payments | `TES-01002` (the payments stand in) | none; synthetic, checked at `2027-03-15T09:10:00Z` | AC-7 |
| `mover-TES-01012-2027-03-22` | payments | `TES-01012` (the IT approver) | none; synthetic | AC-7 |

Synthetic cases exist only to test separation of duties; their IDs follow the spec 0003 workflow ID format.

IDs: `X`, `M`, `S`, `A`, `I` are employee IDs (`TES-NNNNN`, spec 0002, matching the token `sub` from spec 0003); `T` is a dataset team ID; `C` is the Temporal workflow ID of the case, in the format spec 0003 fixed for worker tokens (for example `joiner-TES-01042`); `tessaro` is the one org.

**State transitions**: no state machine in the model. Access changes only by writing or deleting tuples: joiner adds owner, team and member; mover adds the new team and later deletes the old one; leaver deletes every tuple naming the user and every stand in they hold (PRD 9.4), except `lifecycle_case` tuples, which stay until their case closes so the leaver's own case keeps its `subject` guard; a stand in ends by time without any write.

**API surface** (OpenFGA checks callers will make; the client itself is feature 13):

| Check | Relation | Object | Context | Caller | On error |
|---|---|---|---|---|---|
| May I see this record? | `can_view_own_data` | `employee:<id>` | `current_time` | self tools (`get_my_leave` and later) | deny |
| May I see these leave dates? | `can_view_leave_dates` | `employee:<id>` | `current_time` | `get_team_leave` | deny |
| May this person approve? | `can_approve` | `lifecycle_case:<workflow id>` | `current_time` | jml worker, on an approval signal | deny |
| May this person approve IT access? | `can_approve_it` | `lifecycle_case:<workflow id>` | `current_time` | jml worker | deny |
| May this person see the case status? | `can_view` | `lifecycle_case:<workflow id>` | `current_time` | workflow status tool | deny |
| Local load | n/a | n/a | n/a | `just authz-load` | exit non zero, `.env` untouched |
| Model tests | n/a | n/a | n/a | `just authz-test` | exit non zero |

**Value sourcing**:

| Action | Value | Source |
|---|---|---|
| any check | `user:<id>` | the verified token: `HumanPrincipal.employee_id` for human calls; for approvals, the approver identity carried by the signal (`on_behalf_of` in spec 0003). Never from model output or tool input |
| any check | `current_time` | the caller's own clock in UTC (`datetime.now(UTC)`; inside a Temporal workflow, `workflow.now()`). Never the agent, the user or the token |
| employee checks | `employee:<id>` | the employee ID on the record being returned (Frappe HR `employee` field) |
| case checks | `lifecycle_case:<id>` | the Temporal workflow ID |
| seed tuples | stand in `valid_from`, `valid_until` | `standins.yaml`, resolved against the anchor by the dataset (spec 0002) |
| seed tuples | `org:tessaro` | `FGA_ORG` constant in `tessaro_dataset.registry` |
| `just authz-test` | anchor, window | fixed in the recipe: `--anchor 2027-03-15T10:00+01:00 --stand-in-minutes 15` |
| `just authz-load` | `OPENFGA_STORE_ID`, `OPENFGA_MODEL_ID` | the JSON printed by `fga store create --model authz/model.fga` |
| `just authz-load` | API URL | `OPENFGA_API_URL` already in `.env` |

**Key invariants**:
- Deny by default: no tuple, no access. No wildcard (`user:*`) relation exists.
- A lifecycle case's subject can never approve it through any path (`but not subject` on both approvals). Being the subject grants no view; a subject who is also the team's approver can still view the case status. This is a conscious Phase 1 choice: joiners and movers can't ask for their own case status.
- HR advisors can view but never approve.
- Stand in access exists only while `valid_from <= current_time < valid_until` (half open, so the window end is denied).
- No inheritance up a hierarchy: access comes only from a direct relation on the record's team or the org.
- A check that errors (missing context, store unreachable, unknown model) counts as deny at every caller.
- `ALLOWED_RELATIONS` equals the model's directly assignable relations (AC-9); any model change fails that test until the registry follows.
- Callers pin `OPENFGA_MODEL_ID`; a model change is a new model ID rolled out with the services, never picked up silently.

**Security model**: OpenFGA is Layer 2; OPA (feature 6) is Layer 1 and decides which tools a role may call. Both must allow. Employee data is personal data under GDPR (fictional here, but treated as real): leave dates are visible to the owner, their team's approvers and the team's HR advisors only; absence reasons are never exposed by any relation (the tool contracts forbid the field, spec 0003). Writes to OpenFGA come only from the dataset seed and workflow worker tokens (the identity tool server, feature 18); no human path writes tuples in Phase 1. IT agents and People advisors with `*:read_any` scopes get no record relation in this spec; their record rule is decided with the IT tools feature. Every check result is audit logged by its caller with the request ID (feature 13 and later), not by OpenFGA.

**Configuration required**:
- `OPENFGA_API_URL`: already in `.env.example` (`http://localhost:18080`).
- `OPENFGA_STORE_ID`: the store each caller checks against; set by `just authz-load` locally, by the cluster seed later.
- `OPENFGA_MODEL_ID`: the pinned authorization model ID; same sources.
No service reads these yet; feature 13 adds them to its settings class and fails fast when missing.

**Dependencies**: none new. The `fga` CLI (v0.8.1, pinned in CI) is already required by `just policy`; the parser test uses only the standard library.

**Critical test scenarios** (each maps to an acceptance criterion in ## Requirements):
- Happy path: the persona sees their own leave dates; the payments manager sees the team's; the stand in approves a joiner inside the window, verifies **AC-2**, **AC-3**, **AC-4**, **AC-7**
- Failure case: the same stand in is denied at exactly `valid_until` and one second before `valid_from`, and allowed at exactly `valid_from`, verifies **AC-4**
- Auth/permission: the persona is denied a teammate's leave dates; a manager or either stand in is denied another team's employees and cases; the manager and the stand in, each the subject of a case, are denied `can_approve` on it; the HR advisor is denied every approval, verifies **AC-2**, **AC-5**, **AC-6**, **AC-7**
- Drift: removing a relation from the model without updating `ALLOWED_RELATIONS` fails pytest, verifies **AC-9**

## Build plan

Tracer Bullet: the first task runs the whole chain once (dataset, generated tuples, model, CLI test, `just check`) for one rule; each later task thickens one strand.

1. Thin thread: write `authz/model.fga`; add `FGA_ORG`, the org `it_approver` export and the `ALLOWED_RELATIONS` change (drop `lifecycle_case#it_approver`, add `org#it_approver`, `lifecycle_case#org`, `lifecycle_case#subject`); write `test_fga_model.py` (a small parser for `type` and `define …: [...]` lines, stripping `with <condition>`); update the existing exporter tests for the new `org#it_approver` tuples; add `authz/.build/` to `.gitignore`; add `just authz-test` and replace the `authz/*.fga.yaml` loop in `just policy` with it; write `authz/employee.fga.yaml` with the self access checks only, satisfies **AC-1**, **AC-2**, **AC-9**, **AC-10**
2. Team access: extend `employee.fga.yaml` with manager, HR advisor and cross team checks over all five teams, satisfies **AC-3**, **AC-5**, **AC-6**
3. Stand in window: `stand_in.fga.yaml` with checks at the start, inside, one second before the start and at the end, on both leave dates and a payments case; plus the workplace stand in `TES-01007` denied on payments, satisfies **AC-4**, **AC-5**
4. Lifecycle cases: `lifecycle_case.fga.yaml` with the fixture cases from *Feature design* (joiner, and the manager, stand in and IT approver as subjects) and `mover.fga.yaml` with the mover case and the second team tuple for `TES-01023`, satisfies **AC-5**, **AC-6**, **AC-7**, **AC-8**
5. Local load: `just authz-load` and the two `.env.example` lines, satisfies **AC-11**

## Consequences

**Positive**:
- Self approval is impossible by construction, not by workflow code that could forget a check.
- One IT approver tuple serves every case; adding an IT approver applies to open cases at once.
- Model and dataset can't drift: the tests load generated tuples and the registry is checked against the model.
- Stand in access expires with no job or write; demo step 5 needs nothing but time.

**Negative / tradeoffs**:
- The model now differs from PRD 8.3 (new `org` type, `subject`, `but not`); the PRD and spec 0002 AC-8 (which says `ALLOWED_RELATIONS` is copied from PRD 8.3) need a note.
- Every workflow must write three tuples per case (org, team, subject); a missing subject tuple silently drops the self approval guard. Feature 17 must test that.
- During a move both managers see the mover's leave dates until the old tuple is deleted.
- Pinning the model ID means a model change needs a config rollout to every caller.
- The DSL parser in the test is ours to maintain; an unusual DSL construct could slip past it (the CLI tests still catch behaviour).

**Neutral**:
- `member` is stored but unused by any permission for now.
- IT agents' and People advisors' read any record rule is deferred.
- Caller side error handling (deny on error) is specified here but built in feature 13.

## Follow-up

- [ ] Update the PRD 8.3 model block to match this spec, and note on spec 0002 AC-8 that `ALLOWED_RELATIONS` now follows `authz/model.fga` (spec 0004), not PRD 8.3.
- [ ] Feature 13: OpenFGA check client protocol, fake and httpx client; settings with `OPENFGA_API_URL`, `OPENFGA_STORE_ID`, `OPENFGA_MODEL_ID`; deny on any error; audit log each decision.
- [ ] Feature 17 (joiner workflow) and the mover and leaver workflows: write the `org`, `team` and `subject` tuples in one atomic OpenFGA write from a single case creation helper, test that a case without `subject` is never created, and keep `lifecycle_case` tuples out of the leaver cleanup until the case closes.
- [ ] IT tools feature: decide the record rule for `it:read_any` (and `hr:read_any` if broader than advised teams).
- [ ] Feature 10 (platform services): seed the cluster store from the dataset export and publish its store and model IDs to the services' config.
