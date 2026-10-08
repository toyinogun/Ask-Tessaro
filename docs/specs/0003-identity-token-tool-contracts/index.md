# 0003. Ed25519 identity tokens per issuer, and tool contracts as Pydantic models

**Date**: 2026-10-08
**Status**: In Progress

## Summary

Every call in Tessaro carries a short lived signed token (a JWT, a small signed JSON document) that says who is asking: a human employee, minted by the Zulip adapter, or a workflow worker, minted by the jml-worker. Each issuer signs with its own Ed25519 key (a modern public key signature), and verifiers only accept a worker token when the worker key signed it, so a compromised adapter can never mint a write capable token. Every tool server publishes a typed, versioned contract, written once as Pydantic models in `tessaro-contracts`. The gateway, tool servers, agent, OPA policy data and tests are all generated from or checked against that one definition. This feature builds both libraries and the first contract, `get_my_leave`; it builds no service.

## Requirements

**User stories**:
- As a tool server, I want to verify who is calling from the token alone, so that self scoped tools never accept an employee identifier (FR-T2).
- As the gateway, I want to tell human tokens from workflow worker tokens with a guarantee I can trust, so that write scopes stay out of human hands (FR-G1, FR-G2, NFR-1).
- As the jml-worker, I want to mint a fresh token per activity that names the workflow and the approver, so that every write is audited with both (FR-G4, FR-W8).
- As a tool server author, I want one typed contract per tool, so that the agent, gateway, policy and tests can't disagree about a tool's inputs, outputs, scope or version (FR-T1).
- As a reviewer, I want a breaking contract change to fail CI, so that the agent never meets a changed tool under a name it already knows.

**Acceptance criteria** (the contract, each criterion is IDed and independently checkable). Every pattern below is applied with `re.fullmatch` and `re.ASCII`.

*Token issue*
- **AC-1**: `issue_human_token` returns a JWT whose header is exactly `alg=EdDSA`, `typ=JWT` and the signer's `kid`, and whose claims are exactly `iss=tessaro-adapter`, `aud=tessaro-tools`, `sub` (the employee ID), `email`, `kind=human`, `roles` (a sorted list), `request_id`, `jti` (32 random hex characters), `iat` and `exp = iat + TOKEN_TTL_SECONDS` (default 300), with `iat` and `exp` as integer Unix seconds.
- **AC-2**: Roles come from Authentik group names (exact, case sensitive) through one fixed table: `staff` gives `employee`, `managers` gives `manager`, `it-agents` gives `it_service_desk`, `people-advisors` gives `people_advisor`. Other groups are ignored. The result is deduplicated and sorted. No group ever yields `workflow_worker`.
- **AC-3**: `issue_human_token` raises `MintRefused` and returns no token, checking in this order and reporting the first failure: `inactive`; `missing_employee_id` (none or empty); `malformed_employee_id` (not `TES-\d{5}`); `malformed_email` (not `[^@\s]+@[^@\s]+`); `malformed_request_id` (not `[0-9a-f]{32}`); `no_role` (no group maps to a role).
- **AC-4**: `issue_worker_token` returns a JWT with the same header rules and exactly the claims `iss=tessaro-jml-worker`, `aud=tessaro-tools`, `sub=workflow:<workflow_id>`, `kind=workflow_worker`, `roles=["workflow_worker"]`, `request_id`, `jti`, `iat`, `exp`, plus `on_behalf_of` only when an approver is given. It refuses with `malformed_workflow_id` when `workflow_id` does not match `(joiner|mover|leaver)-TES-\d{5}(-\d{4}-\d{2}-\d{2})?` or its date part is not a real calendar date, `malformed_on_behalf_of` when the approver does not match `TES-\d{5}`, and `malformed_request_id` as in AC-3.
- **AC-5**: A signer can only mint its own kind. A signer's kind comes from its kid prefix (`adapter-` is human, `worker-` is workflow worker). A human signer passed to `issue_worker_token`, or a worker signer passed to `issue_human_token`, raises `MintRefused(wrong_signer_kind)`.

*Token verify*
- **AC-6**: `verify(token, keyset, now)` returns a frozen `HumanPrincipal` or `WorkerPrincipal` whose fields carry the claims (roles as a frozenset, `iat` and `exp` as timezone aware UTC datetimes `issued_at` and `expires_at`), for any token from AC-1 or AC-4 checked within its lifetime.
- **AC-7**: `verify` runs its checks in this fixed order and raises `TokenInvalid` with the reason of the first failure:
  1. `malformed`: not three base64url parts, header or payload not a JSON object, or a header holding any member other than `alg`, `kid` and `typ` (so `jwk`, `jku`, `x5u`, `x5c`, `crit` and `b64` are refused), or `typ` present and not `JWT`.
  2. `unknown_key`: `kid` missing, not a string, or not in the local key set (keys are never fetched or taken from the token).
  3. `bad_algorithm`: `alg` is anything but `EdDSA`, including `none` and `HS256`.
  4. `bad_signature`: the signature does not verify. PyJWT is called with `algorithms=["EdDSA"]` and a typed `Ed25519PublicKey` object only, never bytes or a string, so no HMAC path exists.
  5. `wrong_audience`: `aud` is not exactly `tessaro-tools`.
  6. `kind_not_allowed`: `kind` is not the kind bound to the `kid`.
  7. `wrong_issuer`: `iss` is not the issuer bound to the `kid`.
  8. `claims_invalid`: the claim set is not exactly the set for that kind (a missing or an extra claim), `iat` or `exp` is not an integer (a bool counts as not an integer), or `exp <= iat`.
  9. `lifetime_too_long`: `exp - iat > 600` (600 itself is allowed).
  10. `not_yet_valid`: `iat > now + 30s`.
  11. `expired`: `now > exp + 30s`.
  12. `claims_invalid`: `sub`, `email`, `on_behalf_of` or `request_id` breaks its AC-1, AC-3 or AC-4 pattern; `jti` is not 32 hex characters; `roles` is not a list of known role names, holds a duplicate, is empty, holds `workflow_worker` on a human token, or is not exactly `["workflow_worker"]` on a worker token.

  PyJWT exceptions map once: `DecodeError` to `malformed`, `InvalidSignatureError` to `bad_signature`, `InvalidAudienceError` to `wrong_audience`, `MissingRequiredClaimError` to `claims_invalid`, any other `PyJWTError` to `malformed`. PyJWT's own time checks are switched off; steps 8 to 11 run in our code against `now`.
- **AC-8**: A token with `kind=workflow_worker` and `iss=tessaro-jml-worker`, otherwise perfect, but signed with the adapter key (`adapter-1`), is rejected with `kind_not_allowed`. This is the core security property of the feature.

*Configuration and keys*
- **AC-9**: `TokenVerifySettings` parses `TOKEN_VERIFY_KEYS` (a JSON JWK set) at startup and fails fast (the service won't start) on: invalid JSON; an empty set; a duplicate `kid`; a `kid` not matching `(adapter|worker)-\d+`; a key whose `kty` is not `OKP` or `crv` is not `Ed25519`; an `x` that does not decode to 32 bytes; `use` present and not `sig`; `alg` present and not `EdDSA`; or a `tessaro_kind`/`tessaro_iss` pair other than `human`/`tessaro-adapter` for `adapter-*` kids and `workflow_worker`/`tessaro-jml-worker` for `worker-*` kids. `TokenSigningSettings` fails fast on a missing `TOKEN_SIGNING_KEY` or `TOKEN_SIGNING_KID`, a key that is not 32 bytes of base64url, a kid not matching that pattern, or a `TOKEN_TTL_SECONDS` outside 1 to 600. `check_signer_against(signer, keyset)` fails when the signer's public key differs from its kid's entry; a minter that also verifies calls it at startup.
- **AC-10**: `just keys` is the only writer of `DEV_ADAPTER_SIGNING_KEY`, `DEV_WORKER_SIGNING_KEY` and `TOKEN_VERIFY_KEYS` in `.env`. When all three are present and non empty, it changes nothing; when any is missing or empty, it generates two fresh Ed25519 pairs (`adapter-1`, `worker-1`) and rewrites all three together, the JSON on one line in single quotes. `just init` runs it after `.env` is created. A test mints a token with each generated signing key and verifies it with the generated `TOKEN_VERIFY_KEYS`. `.env.example` lists every token variable with an empty value. `just dev` maps `DEV_ADAPTER_SIGNING_KEY` and `adapter-1` onto `TOKEN_SIGNING_KEY`/`TOKEN_SIGNING_KID` only for `zulip-adapter`, and the worker pair only for `jml-worker` (exercised once those services exist).

*Edge helper*
- **AC-11**: `principal_from_headers(headers, keyset)` returns the Principal for `Authorization: Bearer <token>`. With no header, a non Bearer scheme, or any `TokenInvalid`, it raises a 401 `HTTPException` with `WWW-Authenticate: Bearer error="invalid_token"` and the fixed body `{"detail": "invalid token"}`. The reason is logged at `warning` as `token_rejected` with the request ID, and the token text is never logged.
- **AC-12**: On success, `principal_from_headers` binds the token's `request_id` into the structlog context for the rest of the handler, so every later log line in that call carries it. When the incoming `X-Request-ID` differs, it logs `request_id_mismatch` at `warning` with the token's value and the header value cut to 64 characters. The response `X-Request-ID` header stays as the middleware set it; `tessaro-core` is unchanged.

*Contract format*
- **AC-13**: Building a `ToolContract` raises `ContractError` when: `name` does not match `[a-z][a-z0-9_]*`; `version` does not match `[1-9]\d*\.\d+`; `scope` is not a `Scope` member; `description` or `authorization` is empty; the input or output model, or any model nested in them, is not frozen with `extra="forbid"`; `write` is missing on a scope ending in `:write` or present on any other; `write.idempotency_key_param` is not a required `str` field of the input model; `identity=self` and an input field name or alias, lowercased with underscores removed, is one of `employeeid`, `employee`, `userid`, `user`, `email`, `sub`, `subject`, `personid`; or any `never_returns` name equals a property name or alias anywhere in the output JSON Schema. The walkers read only the keys inside each `properties` object (including those under `$defs`), never schema keywords such as `title` or `description`.
- **AC-14**: `build_registry(contracts)` returns an immutable registry and raises `ContractError` on a duplicate name, or on an `undo_tool` that is not in the registry or is not itself a write tool. `ALL_CONTRACTS` is built with it at import.
- **AC-15**: `to_mcp_tool(contract)` returns a plain dict with `name`, `description`, `inputSchema` and `outputSchema` (Pydantic generated JSON Schema), and `_meta` with `tessaro/version`, `tessaro/scope` and `tessaro/owner`, following the MCP tool shape. `tessaro-contracts` does not import the MCP SDK.
- **AC-16**: `to_mcp_result(ToolResult(output, record_ids))` returns `structuredContent` (the output validated against the output model, dumped in JSON mode), `content` holding one text item with `model_dump_json()` of the output, and `_meta.tessaro/record_ids`. `to_mcp_error(ToolError(code, message))` returns `isError: true`, the message as one text item, and `_meta.tessaro/error_code`, where `code` is one of `unauthenticated`, `forbidden`, `not_found`, `invalid_input`, `upstream_unavailable`, `internal`.

*The first contract*
- **AC-17**: `get_my_leave` 1.0 exists with owner `people-team`, scope `hr:read`, identity `self`, authorization `OpenFGA check can_view_own_data on employee:<sub>`, an empty input model, and this output: `balances`, a list of 0 or 1 entries (vacation for the current year; empty when no allocation exists) with `leave_type` (`vacation`), `year` (int), `entitled_days`, `taken_days`, `pending_days`, `remaining_days` (ints, whole working days); `upcoming`, at most 50 entries with `application_id` (str), `leave_type` (`vacation`, `sick`, `parental` or `special`), `from_date` and `to_date` (ISO dates), `status` (`open` or `approved`); and `truncated` (bool). Its `never_returns` is `reason`, `absence_reason`, `medical_note`, `notes`, `description`, `salary`, and AC-13 passes for it.

*Snapshots, versions and policy data*
- **AC-18**: `just contracts` writes each contract's MCP projection to `libs/tessaro-contracts/schemas/<name>.json` and the OPA tool data to `policy/data/tools.json` (`{"tools": {<name>: {"scope", "version", "owner"}}}`), both as JSON with sorted keys, two space indent and a trailing newline. A test (finding the repo root by walking up to `uv.lock`) fails when either committed file differs from what the registry generates now.
- **AC-19**: A test compares each contract's projection to its committed snapshot. A contract with no snapshot yet passes. Otherwise:
  - no change with the same version passes; no change with a different version fails ("version changed without a contract change");
  - a change with the same version fails;
  - a breaking change fails whatever the version, with a message saying to publish `<name>_v2`. Breaking means a change to `scope`, `identity`, `owner` or `write`, or any input or output schema change that is not on the additive list;
  - the additive list is: a new optional input property, a new output property, a new enum value in an output field, and changes to `description`, `authorization`, `never_returns` or schema `title`/`description` text. An additive change passes only when the major is unchanged and the minor went up.

## Decision

**Chosen option**: Option 2 for the token (one Ed25519 key pair per issuer, with kind bound to the key) and Option 1 for contracts (Pydantic models as the single source).

Human and worker tokens are EdDSA JWTs issued and verified by `tessaro-auth` on PyJWT, with the allowed kind and issuer bound to each verify key. Tool contracts are frozen Pydantic models in `tessaro-contracts`, from which MCP schemas, snapshots and OPA tool data are generated.

**Declined skills**: no Agent Skill was installed. The search found none for PyJWT or JWK sets; `anthropics/skills@mcp-builder`, `wshobson/agents@auth-implementation-patterns` and `wshobson/agents@python-configuration` were offered and declined on 2026-10-08.

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Feature design

**Package layout** (folder by feature, domain code free of FastAPI and httpx):

```text
libs/tessaro-auth/src/tessaro_auth/
  claims.py      Role, Kind, HumanPrincipal, WorkerPrincipal, AUDIENCE, ISSUER_ADAPTER, ISSUER_WORKER, the ID patterns
  roles.py       GROUP_TO_ROLE table, roles_from_groups()
  keys.py        Signer, KeySet, KeyEntry, parse_jwks(), check_signer_against()
  issue.py       DirectoryIdentity, issue_human_token(), issue_worker_token(), MintRefused
  verify.py      verify(), TokenInvalid, InvalidReason
  settings.py    TokenSigningSettings, TokenVerifySettings (pydantic-settings, mixed into a service's settings)
  edge.py        principal_from_headers() (the only module importing Starlette and structlog)
  devkeys.py     `python -m tessaro_auth.devkeys`, used by `just keys`
libs/tessaro-contracts/src/tessaro_contracts/
  scopes.py      Scope (StrEnum)
  contract.py    ToolContract, WriteSpec, IdentityMode, ContractError, the AC-13 checks
  schema_rules.py  JSON Schema walkers: forbidden names, identity fields, nested model checks, breaking change diff
  results.py     ToolResult, ToolError, ToolErrorCode, to_mcp_result(), to_mcp_error()
  mcp.py         to_mcp_tool() (plain dicts, no MCP SDK import)
  registry.py    build_registry(), ALL_CONTRACTS, contract_by_name()
  export.py      `python -m tessaro_contracts.export`, used by `just contracts`
  testing.py     assert_contract_ok(contract) (runs the AC-13 checks plus a snapshot comparison, for tool server test suites); assert_result_matches(contract, result)
  people/get_my_leave.py
libs/tessaro-contracts/schemas/<name>.json   committed snapshots
policy/data/tools.json                       generated OPA tool data (feature 6 adds role_scopes)
```

**Enumerations**:
- `Role`: `employee`, `manager`, `it_service_desk`, `people_advisor`, `workflow_worker`.
- `Kind`: `human`, `workflow_worker`.
- `Scope` (PRD 8.2, 14 members): `it:read`, `hr:read`, `finance:read`, `workplace:read`, `kb:read`, `queue:handoff`, `workflow:read`, `team:read`, `it:read_any`, `workflow:read_any`, `hr:read_any`, `identity:write`, `it:write`, `workplace:write`. A scope is a write scope when its value ends in `:write`.
- `IdentityMode`: `self` (identity from the token only, no person field accepted), `subject` (the input names a target person and the tool checks OpenFGA for the caller against that person), `none` (the tool returns no per person data, e.g. handbook search).
- `ToolErrorCode`: see AC-16.

**Data model sketch** (no database; these are the typed shapes):

| Shape | Fields | Rules |
|---|---|---|
| JWT header | `alg` (`EdDSA`), `kid`, `typ` (`JWT`) | no other members (AC-7 step 1) |
| Human claims | `iss`, `aud`, `sub` (`TES-NNNNN`), `email`, `kind=human`, `roles`, `request_id`, `jti`, `iat`, `exp` | exactly these |
| Worker claims | `iss`, `aud`, `sub` (`workflow:<id>`), `kind=workflow_worker`, `roles=["workflow_worker"]`, `on_behalf_of` (optional), `request_id`, `jti`, `iat`, `exp` | exactly these |
| `KeyEntry` | `kid`, `Ed25519PublicKey`, `kind`, `iss` | kid prefix fixes kind and iss (AC-9); several kids per kind allowed (rotation) |
| `Signer` | `kid`, `Ed25519PrivateKey`, `kind` (from the kid prefix) | built from `TokenSigningSettings` |
| `HumanPrincipal` | `employee_id`, `email`, `roles` (frozenset), `request_id`, `token_id` (jti), `issued_at`, `expires_at` | frozen; never holds the raw token |
| `WorkerPrincipal` | `workflow_id`, `on_behalf_of` (nullable), `roles`, `request_id`, `token_id`, `issued_at`, `expires_at` | frozen |
| `DirectoryIdentity` | `employee_id` (nullable str), `email` (str), `groups` (tuple of str), `is_active` (bool) | built by the adapter from Authentik |
| `ToolContract` | `name`, `version`, `owner`, `scope`, `identity`, `authorization`, `description`, `input_model`, `output_model`, `never_returns` (tuple of str), `write` (nullable `WriteSpec`) | AC-13 |
| `WriteSpec` | `idempotency_key_param` (str), `undo_tool` (nullable str) | AC-13, AC-14 |

`TOKEN_VERIFY_KEYS` example (a standard JWK set with two Tessaro members):

```json
{"keys": [
  {"kty": "OKP", "crv": "Ed25519", "x": "<base64url>", "kid": "adapter-1", "alg": "EdDSA", "use": "sig",
   "tessaro_kind": "human", "tessaro_iss": "tessaro-adapter"},
  {"kty": "OKP", "crv": "Ed25519", "x": "<base64url>", "kid": "worker-1", "alg": "EdDSA", "use": "sig",
   "tessaro_kind": "workflow_worker", "tessaro_iss": "tessaro-jml-worker"}
]}
```

**State transitions**: none. A token is never refreshed; callers mint a new one. With the 30 second leeway and the 600 second cap, the longest any token can be accepted is 660 seconds of wall time (a token whose `iat` sits 30 seconds ahead, with `exp = iat + 600`, accepted until `exp + 30s`). With the default TTL it is 360 seconds.

**API surface** (libraries, no HTTP):

| Function | Inputs | Outputs | Used by | Key errors |
|---|---|---|---|---|
| `issue_human_token` | `identity: DirectoryIdentity`, `request_id: str`, `signer: Signer`, `now: datetime`, `ttl_seconds: int` | JWT str | zulip-adapter (feature 12) | `MintRefused` |
| `issue_worker_token` | `workflow_id: str`, `on_behalf_of: str \| None`, `request_id: str`, `signer`, `now`, `ttl_seconds` | JWT str | jml-worker activities (features 24 to 31) | `MintRefused` |
| `verify` | `token: str`, `keyset: KeySet`, `now: datetime` | `HumanPrincipal \| WorkerPrincipal` | gateway, tool servers | `TokenInvalid(reason)` |
| `principal_from_headers` | `headers: Mapping[str, str]`, `keyset`, `now` (defaults to UTC now) | Principal | FastAPI routes and MCP tool handlers | 401 `HTTPException` |
| `parse_jwks` / `TokenVerifySettings.keyset` | JSON str | `KeySet` | service startup | `ValueError` (startup fails) |
| `check_signer_against` | `signer`, `keyset` | none | minters that also verify, at startup | `ValueError` |
| `ToolContract(...)` | fields above | contract | each tool module | `ContractError` |
| `build_registry` | contracts | registry | `registry.py`, tests | `ContractError` |
| `to_mcp_tool` | contract | dict | tool servers' `tools/list`, snapshots | none |
| `to_mcp_result` / `to_mcp_error` | `ToolResult` / `ToolError` | dict | tool servers | `ValidationError` on a bad output |
| `contract_by_name` | name | contract | gateway, agent tests | `KeyError` |
| `just keys` / `just contracts` | none | `.env` lines / snapshot and OPA files | developers, CI | non zero exit |

**Value sourcing**:

| Action | Value produced | Source |
|---|---|---|
| issue human | `sub` | `DirectoryIdentity.employee_id`, which the adapter reads from the Authentik user attribute `employee_id` (the dataset's `AuthentikUser.employee_id`; feature 9 must load it as an attribute) |
| issue human | `email`, `groups`, `is_active` | the Authentik user record, via `DirectoryIdentity` |
| issue human | `roles` | derived from `groups` by `GROUP_TO_ROLE` |
| issue (both) | `request_id` | required argument; callers pass `current_request_id() or new_request_id()` from `tessaro_core` (both produce 32 hex characters) |
| issue (both) | `iat`, `exp` | `now` argument (timezone aware UTC) truncated to whole seconds, and `TOKEN_TTL_SECONDS` |
| issue (both) | `jti` | `secrets.token_hex(16)` |
| issue (both) | `iss`, `kind` | constants chosen by the signer's kid prefix |
| issue (both) | `kid` | `TOKEN_SIGNING_KID` |
| issue worker | `sub` | `workflow_id` argument, the Temporal workflow ID (FR-W2 format) |
| issue worker | `on_behalf_of` | argument; the approver's employee ID from the approval signal (FR-W6) |
| verify | allowed `kind` and `iss` per key | the `TOKEN_VERIFY_KEYS` entry for the token's `kid` |
| verify | the time used for checks | `now` argument; `edge.py` passes `datetime.now(UTC)` |
| edge | request ID in the handler's logs | the token's `request_id` |
| `get_my_leave` | `balances[0]` values | computed by the People tool server (feature 14) from Frappe HR, by the spec 0002 AC-14 rule: `entitled` = the year's vacation allocation; `taken` = working days of approved vacation in that year; `pending` = working days of open vacation in that year; `remaining = entitled - taken` (pending is reported, not deducted) |
| `get_my_leave` | working days | Monday to Friday, no public holidays (the spec 0002 calendar) |
| `get_my_leave` | "today" and "current year" | the tool server's clock in `Europe/Amsterdam` (the company time zone fixed in spec 0002) |
| `get_my_leave` | `upcoming` | the caller's applications with `to_date >= today` and Frappe status Open (`open`) or Approved (`approved`); Rejected and Cancelled are left out; sorted by `from_date`, cut at 50 with `truncated=true` |
| `get_my_leave` | `application_id` | the Frappe leave application name, passed through as an opaque string |
| `get_my_leave` | `record_ids` | the `application_id` of each returned entry |
| contract export | OPA `data.tools[name].scope` | `ToolContract.scope` |
| MCP projection | `_meta.tessaro/*` | contract fields |

**Key invariants**:
- A worker kind token can only come from a key whose entry says `workflow_worker`, and that is checked before the issuer. Claims never decide trust on their own.
- Only `EdDSA` is accepted, keys come only from the local key set, and PyJWT only ever receives a typed Ed25519 key.
- No token is accepted longer than 660 seconds of wall time, whatever the TTL setting says.
- Human tokens always carry at least one role and a well formed employee ID; worker tokens always carry exactly `workflow_worker`.
- The raw token and private keys are never logged, never stored in a Principal, never put in an exception message. Untrusted header values are cut to 64 characters before logging.
- A tool name, once released, keeps a compatible contract forever; breaking changes ship under a new name.
- OPA tool scopes are generated from contracts, never hand edited; CI catches drift.
- `never_returns` names can't appear in a tool's output schema.

**Security model**:
- Compliance scope: personal data under GDPR (the dataset is fictional, but the design treats it as real). Tokens carry an email and an employee ID, so they are personal data; they live 5 minutes and are never logged.
- Minting: only the zulip-adapter holds the adapter signing key and only the jml-worker holds the worker signing key, each mounted as a Secret in its own namespace (`assistant` and `workflows`). Every other service gets only `TOKEN_VERIFY_KEYS` (public keys, not secret). On the laptop, both dev private keys sit in the shared `.env`; this breaks key separation for local development only, and `just dev` passes each service only its own key.
- The master agent and privacy proxy pass the token along opaquely and never verify or mint.
- Revocation: OPA scopes and OpenFGA relations are evaluated live on every call, so they take effect at once. A role removed in Authentik lingers for at most one token's accepted window (360 seconds with the default TTL). This is a documented, accepted gap against FR-G5. The leaver workflow also ends Zulip sessions, so no new token is minted.
- Replay: inside its window a token can be replayed. Reads are harmless to repeat and writes are idempotent by key (FR-T4). Because every verifier shares the audience `tessaro-tools`, a compromised tool server that receives a worker token (the People server does, for `hr:read_any`) could replay it against a write tool until it expires. Accepted for now; per server audiences, minted or exchanged at the gateway, are the later fix. `jti` is for audit correlation, not a replay cache.
- Key rotation: add the new kid to every verifier's `TOKEN_VERIFY_KEYS`, switch the minter's `TOKEN_SIGNING_KEY`/`TOKEN_SIGNING_KID`, wait at least 11 minutes (the 660 second window), then remove the old kid.
- Audit: every rejection logs `token_rejected` with reason and request ID; the gateway's audit line (feature 13) records `sub`, `on_behalf_of`, `roles` and `jti`.

**Configuration required**:
- `TOKEN_SIGNING_KEY`: base64url of the 32 byte Ed25519 private key, Secret, minters only.
- `TOKEN_SIGNING_KID`: the key ID this minter signs with, `adapter-<n>` or `worker-<n>`.
- `TOKEN_TTL_SECONDS`: token lifetime, default 300, allowed 1 to 600.
- `TOKEN_VERIFY_KEYS`: the JWK set above, every verifying service. Replaces the `TOKEN_VERIFY_KEY` name from spec 0001 and PRD 14.3.
- `DEV_ADAPTER_SIGNING_KEY`, `DEV_WORKER_SIGNING_KEY`: local `.env` only, written by `just keys`.

**Dependencies**: `pyjwt[crypto]` (2.10 or later as of this writing; confirm at build) and `cryptography` in `tessaro-auth`, plus `pydantic`, `pydantic-settings`, `structlog` and `starlette` (both already in the workspace through `tessaro-core`). `tessaro-contracts` needs only `pydantic`.

**Critical test scenarios** (each maps to an acceptance criterion in ## Requirements):
- Happy path: mint a human token for the demo persona and a worker token for `joiner-TES-01042` approved by Maria, verify both with the two key set, and get Principals carrying the inputs, verifies **AC-1**, **AC-4**, **AC-6**
- Kind forgery: sign a worker kind token with `iss=tessaro-jml-worker` using the adapter key and get `kind_not_allowed`, verifies **AC-8**
- Tampering: flip one payload byte, swap the signature, re sign with `HS256` using the public key bytes, send `alg=none`, add a `jwk` header; each fails with its reason, verifies **AC-7**
- Order: a token that is both expired and has the wrong audience reports `wrong_audience`, verifies **AC-7**
- Expiry: at `exp + 30s` the token passes, at `exp + 31s` it fails `expired`; a token with `exp - iat = 601` fails `lifetime_too_long`, verifies **AC-7**
- Mint refusal: an inactive user, a user with no `employee_id`, and a user in only `team-payments` raise `inactive`, `missing_employee_id` and `no_role`, verifies **AC-3**
- Edge: a missing header, a `Basic` header and an expired token all give the same 401 body; logs hold the reason and never the token, verifies **AC-11**
- Contract guard: a self tool with an `employeeId` alias input, and an output model with a nested `reason` field, both raise `ContractError`, verifies **AC-13**
- Breaking change: removing `taken_days` from `get_my_leave` fails the snapshot test even with version `2.0`; adding an optional output field with version `1.1` passes, verifies **AC-19**

## Build plan

Ordered Tracer Bullet style: first one thin thread through both libraries (mint, verify, contract, MCP projection) proven by one test, then each strand thickened. TDD per root `AGENTS.md`: a failing test first for every task.

1. [x] Thin thread: `claims.py`, minimal `keys.py` (one adapter key), `issue_human_token` and `verify` for the happy path only, plus `Scope`, a minimal `ToolContract`, `get_my_leave` and `to_mcp_tool`. One test mints a token for the demo persona, verifies it, and projects `get_my_leave`, satisfies **AC-1**, **AC-6**, **AC-15**, **AC-17**
2. [x] Roles and refusal: `roles.py` table and every `MintRefused` reason in order, satisfies **AC-2**, **AC-3**
3. [x] Worker tokens and signer kinds: `issue_worker_token`, kid prefix kinds, the two key `KeySet`, satisfies **AC-4**, **AC-5**, **AC-8**
4. [x] Every verify step in order with an injected clock, the header member check and the PyJWT exception mapping, satisfies **AC-7**, **AC-8**
5. [x] Settings: `TokenSigningSettings`, `TokenVerifySettings` and `check_signer_against`, satisfies **AC-9**
6. [x] `edge.py`: `principal_from_headers` with 401 mapping, rejection logging and request ID binding, satisfies **AC-11**, **AC-12**
7. [x] Dev keys: `devkeys.py`, `just keys` (run by `just init`), the `just dev` key mapping, `.env.example` updates, satisfies **AC-10**
8. [x] Contract checks: all AC-13 validators in `contract.py` and `schema_rules.py`, `WriteSpec`, `build_registry`, and the `testing.py` helpers, satisfies **AC-13**, **AC-14**, **AC-17**
9. [x] Results and errors: `ToolResult`, `ToolError`, `ToolErrorCode`, `to_mcp_result`, `to_mcp_error`, satisfies **AC-16**
10. [x] Export and drift: `export.py`, `just contracts`, committed `schemas/get_my_leave.json` and `policy/data/tools.json`, the drift tests, satisfies **AC-18**
11. [x] Compatibility rule: the breaking change diff in `schema_rules.py` and the snapshot version test, satisfies **AC-19**
12. [x] Coverage at 80% or more for both packages, `mypy --strict` clean, `just check` green, satisfies every AC

## Consequences

**Positive**:
- The human and worker boundary rests on key custody, not on a claim, so the most damaging forgery (a human token with write powers) needs the worker key.
- Tool servers verify locally with public keys: no call to Authentik or a token service on the hot path.
- One contract definition feeds MCP schemas, OPA data, snapshots and tests; a drifted scope or a quietly broken tool fails CI.
- Ed25519 keys fit on one env line, and verify keys are public, so only two Secrets in the whole system can mint.

**Negative / tradeoffs**:
- Role removal lags up to 6 minutes, short of FR-G5's "immediately" for roles. Documented and accepted.
- One shared audience lets a compromised tool server replay a forwarded token elsewhere within its window. Documented and accepted for now.
- Two key pairs mean two rotations to manage, each with an 11 minute overlap.
- Breaking changes create `_v2` tools that live beside the old ones until the agent moves over, so the tool list grows. The conservative breaking rule may also flag harmless schema tweaks, forcing a new name.
- Env names change from spec 0001 and PRD 14.3 (`TOKEN_VERIFY_KEY` becomes `TOKEN_VERIFY_KEYS`, plus `TOKEN_SIGNING_KID`).
- Generated files (`schemas/*.json`, `policy/data/tools.json`) must be regenerated with `just contracts` whenever a contract changes; forgetting it fails CI.
- The response `X-Request-ID` can differ from the token's request ID when a caller sends a mismatched header; logs flag it.

**Neutral**:
- `tessaro-auth` gains PyJWT and `cryptography`; `edge.py` uses Starlette and structlog, which the workspace already has.
- The `_meta` keys use a `tessaro/` prefix (`tessaro/version`, `tessaro/record_ids`, `tessaro/error_code`), which the MCP spec allows for custom metadata.
- This feature builds no service. The adapter, gateway and People tool server use these libraries in features 12, 13 and 14.

## Follow-up

- [ ] `libs/tessaro-auth/AGENTS.md` names `TOKEN_VERIFY_KEY`; it should become `TOKEN_VERIFY_KEYS` plus `TOKEN_SIGNING_KID` (for `/sync` after the build).
- [ ] `libs/tessaro-contracts/AGENTS.md` says results carry `_meta.record_ids`; this spec fixes the key as `_meta.tessaro/record_ids` (for `/sync`).
- [ ] The spec 0001 follow up item "Feature 4 must decide who mints workflow worker tokens" is answered here: the jml-worker, through `tessaro-auth`, with its own key in the `workflows` namespace.
- [ ] Spec 0001 and PRD 14.3 list `TOKEN_VERIFY_KEY`; note the rename when those are next touched.
- [ ] Feature 9 (identity systems) must load `employee_id` as an Authentik user attribute so the adapter can fill `sub`.
- [ ] Feature 6 (tool policy) must use the `Role` names from `tessaro_auth.claims` as `role_scopes` keys and read `policy/data/tools.json` rather than writing tool scopes by hand.
- [ ] Feature 12 (Zulip adapter) decides the exact user facing reply when `MintRefused` is raised (suggested: "I can't verify your account. Please contact IT.").
- [ ] Feature 13 (tool gateway) should consider per server audiences (the gateway exchanging a token per upstream) to close the shared audience replay window.
- [ ] The MCP SDK spike from spec 0001 should confirm, before features 13 and 14, that a tool handler can read the request headers (for `principal_from_headers`) and that `outputSchema`, `structuredContent` and `_meta` pass through `langchain-mcp-adapters` unchanged. This feature's dicts follow the MCP tool shape and don't depend on the spike.
- [ ] Record in root `AGENTS.md` that the Agent Skills `anthropics/skills@mcp-builder`, `wshobson/agents@auth-implementation-patterns` and `wshobson/agents@python-configuration` were declined on 2026-10-08 (for `/sync`).
