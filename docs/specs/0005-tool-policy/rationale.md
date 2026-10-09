# 0005. Tool policy: rationale

## Context

Tessaro has two authorization layers. Layer 2, record access in OpenFGA, is built (spec 0004). Layer 1 is still a sketch in PRD 8.2: a role to scope table and a short Rego rule that allows a call when a role grants the tool's scope and blocks write scopes for anything but a workflow worker token. Spec 0001 already placed OPA as a sidecar beside the gateway, loading policy from a ConfigMap built from `policy/`. It also said the gateway checks OPA on every `tools/call` and filters `tools/list` by it. Spec 0003 fixed the token claims (`kind`, `roles`), the `Role` and `Scope` enums, and generated `policy/data/tools.json` from the contracts, leaving `role_scopes` to this feature.

The forces: this is security core work, tagged GA. The done line asks for tests covering every role and scope in PRD 8.2, and proof that every human token is denied every write scope. The policy must run and be tested on a laptop, with no cluster yet. The audit log (FR-G4) needs to record the result of every call, and a bare "denied" tells an operator little. Tokens carry an email and an employee ID, which are personal data under GDPR (fictional here, treated as real).

Three gaps in the draft would bite at build time. First, OPA loads a data file at the path of its folder, so today's `policy/data/tools.json` lands at `data.data.tools`, and the PRD rule, which reads `data.tools`, would find no tool at all (confirmed with `opa eval -d policy/ data`). Second, a ConfigMap is a flat folder, so a nested layout doesn't survive the trip to the cluster without extra mount rules. Third, the role table has no home: `Role` lives in `tessaro-auth` and `Scope` in `tessaro-contracts`, and neither library depends on the other. A hand written table would let a renamed role or scope fail open at runtime instead of failing in CI.

## Options considered

### Option 1: PRD 8.2 as written

Copy the PRD Rego into `policy/`, hand write `role_scopes` as JSON, return a plain `allow` boolean, and send the verified claims as `input.token`.

**Pros**:
- Smallest change from the PRD; anyone reading the PRD recognises the policy.
- No new dependency between libraries.

**Cons**:
- The audit line can only record "denied", never why.
- A hand written role table can drift from the `Role` and `Scope` enums with no CI signal.
- Still needs the data path fix, and `tools/list` needs either N queries or a second, separate rule.
- Trusts the gateway completely to never mix a worker role into a human input.

### Option 2: Verified principal input, generated typed data, structured decision, flat folder (chosen)

The gateway sends only `{kind, roles, tool}` after verifying the token. OPA returns `decision` (`allow` plus deny `reasons`) and `allowed_tools`, both built on one deny reason helper. `role_scopes` comes from a typed `ROLE_SCOPES` table in `tessaro-auth`, exported beside the contract data. The policy also denies an inconsistent kind and role mix. All files sit flat in `policy/`.

**Pros**:
- Every denial is explained, in the audit line and in the demo.
- Role and scope names are checked by mypy and by a drift test, so they can't silently diverge.
- One query per call and one per listing, using the same rules.
- Fails closed on malformed input or an impossible kind and role mix, so a gateway bug can't grant writes.
- No personal data reaches OPA.

**Cons**:
- A new dependency edge, `tessaro-auth` on `tessaro-contracts`.
- Moves the generated `tools.json`, touching spec 0003's export and its tests.
- More Rego than the PRD sketch (about three times as many rules), so more to test.

### Option 3: OPA verifies the raw JWT

The gateway forwards the raw token; Rego verifies it with `io.jwt` against the public keys and reads the claims itself.

**Pros**:
- Defence in depth: OPA trusts nothing the gateway computed.
- The policy can use any claim later without a gateway change.

**Cons**:
- OPA would need the verify key set too, a second copy of key handling to keep in step.
- The kid to kind binding, the core property of spec 0003, would have to be rebuilt in Rego.
- Puts the email and employee ID into OPA input and any logs it writes.

### Option 4: No OPA, policy in the gateway's Python

Check scopes inside the gateway with the typed table directly, and drop the sidecar.

**Pros**:
- One fewer process; fully typed; tests in pytest only.

**Cons**:
- Departs from the PRD and spec 0001, which fix OPA as Layer 1.
- Mixes policy with the enforcer, so a policy change means a gateway release and review of gateway code.
- Loses `opa test` and the "policy as data" story the portfolio is meant to show.

## Rationale

Option 2 keeps the PRD's rule and package name but closes the gaps the PRD left open. The structured decision exists because FR-G4 makes the audit log the system of record; an operator reading a refusal needs the reason, and producing it costs one extra set in Rego. The `allowed_tools` rule exists because spec 0001 already committed the gateway to filtering `tools/list`, and building it on the same helper as `decision` makes "listed but refused" impossible by construction.

The typed table is the GA answer to drift. Spec 0003 made tool scopes generated for the same reason, and its follow up asked this feature to key `role_scopes` by the `Role` names. Putting `ROLE_SCOPES` in `tessaro-auth` keeps all role knowledge (groups to roles, roles to scopes) in one module. The dependency it needs points at `tessaro-contracts`, which is pydantic only, so it is light. The reverse direction would have pulled cryptography and PyJWT into every contract consumer. The grid test then writes the PRD table out a second time in Rego, so the generated data is checked against an independent copy, not against itself.

Sending only verified `{kind, roles, tool}` follows from spec 0003: verification and the kid to kind binding already live in `tessaro-auth`, and repeating them in Rego (Option 3) doubles the key handling for no new guarantee. The kind and role check is the cheap backstop: it can only fire if the gateway is wrong, and that is exactly the case where a GA security layer should fail closed. Keeping on_behalf_of out of the policy was deliberate: leaver steps run with no approver (FR-W5), and approval gating belongs to the workflow (FR-W6). The flat folder fixes the `data.data` path and matches the ConfigMap shape in one move.

Smaller calls settled during the design: Manager scopes are flattened in the data, so the grant reads plainly and doesn't depend on a manager also being in `staff`. Rego quality uses `opa fmt` and `opa check --strict` from the already pinned binary rather than adding Regal. Coverage is 100%, since the policy is tiny and every line is a security decision. OPA decision logs stay off, so the gateway audit line remains the single record. The ConfigMap sync lag against FR-G5 is accepted for Phase 1, like spec 0003's role lag, rather than adding a bundle server before a cluster exists.
