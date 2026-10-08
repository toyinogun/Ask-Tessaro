# 0004. Record access model: rationale

## Context

Tessaro answers questions about people's own records and, through workflows, grants access when people join, move or leave. Tool policy (OPA, feature 6) decides which tools a role may call, but not whose record a call may return: a manager allowed to call `get_team_leave` must still see only their own team. That second layer is OpenFGA, chosen in spec 0001, with a draft model in PRD 8.3. Feature 5 turns the draft into the model the tool servers and workflows will check against, before any service calls it.

The forces: this is the security core, tagged GA, so every rule needs a test, and the done line asks for tests on self access, manager leave dates, expired stand ins, cross team attempts and HR advisor scope, using tuples generated from the dataset. The dataset (spec 0002) already exports tuples against an `ALLOWED_RELATIONS` list copied from the PRD, and feature 5 was asked to confirm it against the real model. Tokens (spec 0003) name people by employee ID, which is the `user:` ID in the tuples. Everything here must run on a laptop; there is no cluster yet.

The draft leaves gaps a reviewer would flag. A manager who becomes a mover could approve their own access bundle. IT approvers are written per case, so the workflow needs a source for who they are, and cases already open miss a new approver. Stand in windows need a trusted clock. Tuple timestamps move with the demo anchor, so tests need a fixed one. Leaving these open means each workflow or tool server answers them differently, in code, where a missed check fails open.

## Options considered

### Option 1: PRD 8.3 model as written

Take the PRD model verbatim: `team`, `employee`, `lifecycle_case`, a per case `it_approver`, and the `within_window` condition.

**Pros**:
- Matches the PRD and the existing `ALLOWED_RELATIONS` with no changes.
- Fewest relations to learn and test.

**Cons**:
- Anyone who is an approver of the case's team can approve their own case.
- The joiner workflow must write an `it_approver` tuple per case from some list it has no source for, and a newly appointed IT approver misses open cases.

### Option 2: PRD model plus separation of duties and an org level IT approver (chosen)

Keep the PRD model, add a `subject` relation to `lifecycle_case` excluded from both approvals with `but not`, and move `it_approver` to a single `org` type the case points at.

**Pros**:
- Self approval is impossible in the model, whatever the workflow does.
- IT approvers come from the dataset once; open cases see changes at once.
- Small: one new type, two new case relations, the rest unchanged.

**Cons**:
- Diverges from the PRD and spec 0002's registry, so both need a note and the exporter changes.
- Workflows must write a `subject` tuple; forgetting it removes the guard silently.

### Option 3: Option 2 plus org wide reader roles

Also add `it_agent` and `people_advisor` relations on `org`, with `employee.org` and read relations so `*:read_any` scopes have a record rule now.

**Pros**:
- Every role in PRD 8.2 gets a record rule in one place.

**Cons**:
- Designs record access for IT and People tools that don't exist yet; the records they would read (tickets, devices) aren't types in the model.
- Widens HR advisor reach beyond their teams, against the PRD.

## Rationale

The model's job is to make the unsafe thing impossible rather than unlikely. Option 1 leaves self approval to workflow code, and that is the check most likely to be missed in a mover edge case: the payments manager moving teams is a plausible demo day event. `but not subject` costs one relation and removes the whole class. Moving `it_approver` to `org` answers the question Option 1 leaves open (where the workflow learns who the IT approvers are) with data the dataset already has (`it_approver: true`), so the workflow writes nothing per case for IT.

Option 3 is the tempting completeness move, but it would design record rules for tools with no spec, against types that don't exist; the right time is when the IT tools define what an IT agent reads. HR advisors stay team scoped as the PRD says.

The smaller calls follow the same reasoning. The caller's own clock supplies `current_time`, because the token's issue time could stretch a window by the token's lifetime and anything from the agent or user is untrusted; errors deny. Tests load tuples generated at a fixed anchor at test time, not a committed fixture, so there is one source and nothing to regenerate (runner up: a committed fixture with a drift check, easier to review but one more artefact). Services pin the model ID so a bad model write can't change every decision at once (runner up: always latest, simpler config). The registry check parses the DSL in pytest rather than shelling out to `fga model transform`, so the test runs anywhere `uv` does (runner up: the CLI transform, which is exact but makes pytest depend on the `fga` binary). No management hierarchy: five flat teams, and a `parent` relation can be added later without rewriting tuples.
