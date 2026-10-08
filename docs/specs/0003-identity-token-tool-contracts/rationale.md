# 0003. Rationale: identity token and tool contracts

The decision record behind [index.md](index.md). `/develop` builds from `index.md`; this file explains why.

## Context

Tessaro's whole security story rests on one question asked at every hop: who is this call really for? An employee's question passes from Zulip through the adapter, the master agent, the privacy proxy's model round trip, the gateway and finally a team's tool server. A workflow step passes from Temporal through the gateway to a tool server's write endpoint. The PRD asks the gateway to tell these two callers apart (FR-G1), to grant write scopes only to workflow workers (FR-G2, NFR-1), to audit the caller and the approver it acts for (FR-G4), and asks self scoped tools to take identity from the token alone (FR-T2). If the human and worker boundary can be crossed by anyone who can mint a token, every write protection downstream is decorative.

Two services mint tokens, and they face very different risks. The Zulip adapter takes webhooks from the chat system and talks to Authentik; it is the most exposed service we write. The jml-worker runs in its own `workflows` namespace and only reacts to signed Frappe HR events and Temporal. Every other service (gateway, every tool server) only needs to check tokens, never create them. Spec 0001 fixed the env names (`TOKEN_SIGNING_KEY` only where tokens are minted, `TOKEN_VERIFY_KEY` everywhere else) and left the algorithm, claims and worker minting to this feature.

The second half of the problem is the shape of a tool. PRD FR-T1 asks for typed, versioned contracts, and section 9 gives a JSON example with a scope, an identity rule, an authorization rule and a `never_returns` list. Several parties read the same facts about a tool: the tool server implements it, the gateway needs its scope for OPA, the agent sees its schema and description, the eval suite tests it, and reviewers need to see when it changes. When each keeps its own copy, they drift, and drift here means either a tool the policy doesn't cover or an agent calling a tool whose output changed under it.

Constraints: one engineer, Python 3.13 with `mypy --strict`, Clean Architecture (no framework imports in domain code), 80% coverage per package, frozen models everywhere, a GA rigor tier for this feature, and no cluster yet, so everything must work and be tested on a laptop. The data is fictional but treated as GDPR personal data.

## Options considered

### Token option 1: One shared key pair for every minter

Both the adapter and the jml-worker hold the same Ed25519 signing key; verifiers hold one public key. Kind is just a claim.

**Pros**:
- Simplest possible setup, and matches the single `TOKEN_SIGNING_KEY` and `TOKEN_VERIFY_KEY` in PRD 14.3 and spec 0001.
- One rotation to manage.

**Cons**:
- Whoever holds the adapter's key can mint a `workflow_worker` token, so a compromise of the most exposed service hands over every write scope. The human and worker split becomes a convention, not a control.

### Token option 2: One Ed25519 key pair per issuer, kind bound to the key (chosen)

The adapter and the jml-worker each hold their own signing key and `kid`. Every verifier holds a small JWK set in which each `kid` names the one kind and issuer it may sign. A worker kind token signed by the adapter key fails verification whatever its claims say.

**Pros**:
- The write boundary rests on key custody: forging a worker token needs the worker key, which lives only in the `workflows` namespace.
- Still fully local verification, no extra service, no network call on the hot path.
- The JWK set gives rotation for free: add a new `kid`, roll minters, remove the old one.

**Cons**:
- Two keys to generate, store and rotate, and one more env variable (`TOKEN_SIGNING_KID`) plus a JSON value (`TOKEN_VERIFY_KEYS`) that is less readable than a single PEM.
- Departs from the env names in PRD 14.3 and spec 0001.

### Token option 3: A dedicated token service mints worker tokens

A small service owns the worker key; the jml-worker asks it for a token per activity, perhaps authenticated by its Kubernetes ServiceAccount token.

**Pros**:
- The worker key never touches workflow code, so even a compromised jml-worker process cannot mint arbitrary tokens offline.
- A natural place for future checks, such as only minting for workflows that are actually running.

**Cons**:
- One more service to build, deploy, secure and keep available; if it is down, every workflow write stops.
- Needs its own authentication between jml-worker and the token service, which is the same problem one level down.

### Token option 4: Use Authentik issued OIDC tokens directly

The adapter obtains an access token from Authentik for the user (or a service account), and verifiers check it against Authentik's JWKS endpoint.

**Pros**:
- No signing keys of our own; Authentik already does key management and rotation.
- Standard OIDC claims and tooling.

**Cons**:
- The adapter receives a Zulip webhook, not a user login, so it has no user session to exchange; it would need token exchange or impersonation features that add real complexity.
- Our claims (`kind`, mapped `roles`, `request_id`, `on_behalf_of`) would need custom Authentik property mappings, and the PRD already warns about mapping pitfalls (section 8.1).
- Every verifier depends on Authentik's JWKS being reachable at startup and on key rotation.

### Contract option 1: Pydantic models in `tessaro-contracts` (chosen)

A frozen `ToolContract` holds the metadata and points at frozen input and output Pydantic models. JSON Schema, MCP tool definitions, snapshots and OPA tool data are generated from it.

**Pros**:
- One definition that mypy checks; tool servers, the gateway and tests import the same object.
- Validation rules (no identity fields on self tools, no forbidden output fields, write specs) run when the contract is built, so mistakes fail at import or in the first test.
- Pydantic already generates the JSON Schema the MCP `inputSchema` and `outputSchema` fields need.

**Cons**:
- Python only; a tool server in another language would need the generated JSON snapshots instead.
- Generated artifacts (snapshots, OPA data) must be regenerated and committed, adding a step.

### Contract option 2: JSON or YAML contract files with generated models

Contracts are written as files like the PRD example, and Pydantic models are generated from them.

**Pros**:
- Language neutral and readable by non engineers.
- Matches the PRD example literally.

**Cons**:
- A code generation step and two representations to keep in step; generated models are awkward to read and to type check.
- Rules like "no forbidden field anywhere in the nested output" have to be written against raw schema anyway.

### Contract option 3: Each tool server owns its own contract

No shared library; each server defines its tool models inline.

**Pros**:
- Teams are fully independent, which matches the PRD's team ownership story.

**Cons**:
- The gateway and agent can't import the contracts, so scopes and schemas are copied by hand or trusted from `tools/list` at runtime.
- FR-T1 checks (identity, never returns, versioning) get duplicated or skipped in each server.

## Rationale

The token decision turns on where the human and worker boundary is enforced. With one shared key (option 1), the boundary is a string in the payload, and the service most exposed to outside input holds the power to write that string. Binding kind to the key (option 2) moves enforcement to something an attacker can't edit: which private key exists in which namespace. It costs one extra key pair and a JSON env value, which is cheap next to the failure mode it removes. A dedicated mint service (option 3) is stronger still, but it adds a service and an availability dependency to every workflow write, for a threat (a compromised jml-worker process) that already has Temporal and write tool access anyway. It stays a reasonable step later if the worker grows. Authentik tokens (option 4) fit a login flow, and Tessaro has no login flow: the adapter acts on a webhook, so it would need impersonation machinery and custom claim mappings that are harder to get right than signing our own short lived token.

Within option 2, Ed25519 was chosen because it is asymmetric (verifiers can't mint), has no parameter choices to get wrong, and its keys fit on one env line. PyJWT was chosen as the most used, maintained Python JWT library with EdDSA support; it stays behind our own `issue` and `verify` functions, so swapping it later touches two modules. Signature checking is delegated to PyJWT, while time checks run against an injected `now`, so expiry tests need no clock patching. The 30 second leeway covers clock drift between nodes without meaningfully extending a 5 minute token. The 600 second lifetime cap guards against a misconfigured TTL rather than an attacker (an attacker holding a signing key can mint as many short tokens as they like). Roles are mapped at mint time so the token stays small and OPA reads exactly the role names in PRD 8.2; a role removal therefore lags by one token lifetime, which the engineer accepted as a documented gap against FR-G5 because scope and record revocation (OPA and OpenFGA, both live) remain immediate.

For contracts, Pydantic (option 1) wins because every consumer is Python and the project already treats frozen Pydantic models as its typed boundary (spec 0001, root `AGENTS.md`). Making the contract the single source for OPA tool scopes closes the gap where a tool server could declare a weaker scope at runtime: scopes reach OPA only through a generated, reviewed, CI checked file. Versioning keeps a tool name compatible forever and ships breaking changes under a new `_vN` name, because MCP clients and the agent's prompt key tools by name; changing a known tool's shape in place is the change most likely to produce a confident wrong answer. Snapshot tests make every schema change visible in review and turn an accidental break into a red build.

## Decisions made during writing

These smaller calls were made while writing the spec, each with the runner up:

- **Audience**: one audience, `tessaro-tools`, for every verifier, since the token is forwarded from the gateway to tool servers unchanged. Runner up: per server audiences, which would force the gateway to mint or exchange tokens.
- **Issuer names**: `tessaro-adapter` and `tessaro-jml-worker`, bound to keys in the JWK set. Runner up: a single issuer with kind only in the key entry, which loses a readable audit field.
- **Signing key format**: base64url of the 32 byte Ed25519 private key, one line in env. Runner up: PKCS8 PEM, which is multi line and fragile in `.env` files and Kubernetes Secrets.
- **Clock handling**: PyJWT checks the signature, audience and required claims; our code checks `iat` and `exp` against an injected `now`. Runner up: let PyJWT check times and patch the clock in tests.
- **Replay**: `jti` for audit correlation only, no replay cache, because reads are safe to repeat and writes are idempotent by key. Runner up: a Redis `jti` cache at the gateway, which adds a dependency for little gain at a 5 minute TTL.
- **Edge helper input**: a `Mapping` of headers rather than a Starlette `Request`, so MCP tool handlers and FastAPI routes can both use it. Runner up: a FastAPI dependency, which MCP handlers can't use.
- **Request ID binding**: bind the token's request ID into the structlog context inside the handler and leave the response header to the middleware. A cross check found that the middleware resets its context after the handler, and Starlette runs the handler in its own context, so pushing the token's ID back into the response header would need a mutable holder in `tessaro-core`. Runner up: that holder, which buys a matching header at the cost of shared mutable state.
- **Verify check order**: signature before any claim, then kind before issuer, then times, then claim shapes. Fixing the order makes every rejection reason testable and makes the forged worker token (AC-8) always report `kind_not_allowed`. Runner up: let PyJWT's exception order decide, which varies with its version.
- **Breaking change rule**: anything not on an explicit additive list is breaking. The cross check showed that listing breaking cases misses `$defs`, bounds, patterns and defaults; an allow list fails safe. Runner up: a full JSON Schema compatibility library, more precise but another dependency for one tool today.
- **Identity field names** forbidden on self tools: `employee_id`, `employee`, `user_id`, `user`, `email`, `sub`, `subject`, `person_id`. Runner up: a regex on string field values, which can't run at definition time.
- **`_meta` key prefix**: `tessaro/` for version, scope, owner, record IDs and error code. Runner up: unprefixed keys, which risk collisions with keys future MCP versions reserve.
- **Snapshot location**: `libs/tessaro-contracts/schemas/`, beside the code it comes from. Runner up: a root `contracts/` folder.
- **`upcoming` cap**: 50 entries with a `truncated` flag, since a tool result goes into a model prompt and one employee rarely has more than a handful of future leave entries.
- **Local keys**: `just keys` writes `DEV_ADAPTER_SIGNING_KEY` and `DEV_WORKER_SIGNING_KEY`, and `just dev` maps the right one onto `TOKEN_SIGNING_KEY` per service, because every local service shares one `.env`. Runner up: one `.env` per service, which breaks the shared `just dev` flow.
