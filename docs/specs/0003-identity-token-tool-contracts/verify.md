# Verify: Identity token & tool contracts · spec 0003 · updated 2026-10-08
_Steps derived from spec 0003 acceptance criteria. `/check verify` runs these; `/test` locks the durable ones._

## Commands
- [ ] `uv run pytest libs/tessaro-auth/tests --cov=tessaro_auth -q` → all pass, coverage at least 80%      → AC-1 to AC-12
- [ ] `uv run pytest libs/tessaro-contracts/tests --cov=tessaro_contracts -q` → all pass, coverage at least 80%      → AC-13 to AC-19
- [ ] `just check` → lint, mypy strict, tests, policy and charts all green      → every AC
- [ ] Mint a human token for `TES-01007` in groups `staff`, `managers`, `team-payments`; decode it unverified → header exactly `alg=EdDSA`, `kid=adapter-1`, `typ=JWT`; claims exactly the ten AC-1 names, `roles=["employee","manager"]`, `exp - iat = 300`, `jti` 32 hex      → AC-1, AC-2
- [ ] Mint with an inactive user, no `employee_id`, and only `team-payments` → `MintRefused` with `inactive`, `missing_employee_id`, `no_role`      → AC-3
- [ ] Mint a worker token for `joiner-TES-01042` approved by `TES-01003` → `sub=workflow:joiner-TES-01042`, `on_behalf_of=TES-01003`, `roles=["workflow_worker"]`; with `joiner-TES-01042-2026-02-30` → `malformed_workflow_id`      → AC-4
- [ ] Pass the adapter signer to `issue_worker_token`, and the worker signer to `issue_human_token` → `wrong_signer_kind` both times      → AC-5
- [ ] Verify both tokens with a two key `TOKEN_VERIFY_KEYS` → a frozen `HumanPrincipal` and `WorkerPrincipal`, times as UTC datetimes      → AC-6
- [ ] Sign a `kind=workflow_worker`, `iss=tessaro-jml-worker` token with the adapter key as `adapter-1` → `kind_not_allowed`      → AC-8
- [ ] Tamper set: flip a payload byte (`bad_signature`), `alg=none` (`bad_algorithm`), HS256 with the public key bytes (`bad_algorithm`), an embedded `jwk` header (`malformed`), an expired token with the wrong audience (`wrong_audience`)      → AC-7
- [ ] Clock edges: at `exp + 30s` accepted, at `exp + 31s` `expired`; `exp - iat = 601` → `lifetime_too_long`; `iat = now + 31s` → `not_yet_valid`      → AC-7
- [ ] Start `TokenVerifySettings` with an empty set, a duplicate kid, a `worker-1` key marked `human`, and an `x` of 3 bytes → each fails at construction; `TokenSigningSettings` with `TOKEN_TTL_SECONDS=601` fails      → AC-9
- [ ] Copy `.env.example` to a scratch file, run `uv run python -m tessaro_auth.devkeys --env-file <copy>` twice → first run writes the three keys (JSON single quoted on one line), second run says unchanged; a token minted with each key verifies with the written `TOKEN_VERIFY_KEYS`      → AC-10
- [ ] `just dev zulip-adapter` (once the service mints) sees `TOKEN_SIGNING_KID=adapter-1` and the adapter dev key; no other service gets a signing key      → AC-10
- [ ] Call a FastAPI route using `principal_from_headers` with no header, `Basic`, and an expired token → three identical 401s, body `{"detail": "invalid token"}`, `WWW-Authenticate: Bearer error="invalid_token"`; logs show `token_rejected` with the reason and never the token      → AC-11
- [ ] Call it with a valid token and `X-Request-ID` set to something else → `request_id_mismatch` warning, later log lines carry the token's request ID, response header unchanged      → AC-12
- [ ] Build a self tool with an `employeeId` alias input, and one whose output nests a `reason` field → both raise `ContractError`      → AC-13
- [ ] `build_registry` with two `get_my_leave` contracts, and with an `undo_tool` that is not a write tool → `ContractError`      → AC-14
- [ ] `to_mcp_tool(GET_MY_LEAVE)` → `name`, `description`, `inputSchema`, `outputSchema`, `_meta.tessaro/version|scope|owner`; `grep -r "import mcp\|from mcp" libs/tessaro-contracts/src` finds nothing      → AC-15
- [ ] `to_mcp_result` and `to_mcp_error` for each of the six codes → the AC-16 shapes      → AC-16
- [ ] `get_my_leave` 1.0: owner, scope, identity, authorization, empty input, output limits (1 balance, 50 upcoming) and `never_returns` exactly as AC-17      → AC-17
- [ ] `just contracts` then `git status` → no changes; edit the snapshot by hand → the drift test fails      → AC-18
- [ ] Remove `taken_days` and bump to 2.0 → `just contracts` refuses and names `get_my_leave_v2`; add an optional output field at 1.1 → accepted      → AC-19

## Value sourcing
- [ ] `sub` comes from `DirectoryIdentity.employee_id`: change it to `TES-01008` → the token's `sub` and the Principal's `employee_id` follow      → value sourcing
- [ ] `roles` derive from `groups` only: swap `managers` for `MANAGERS` → `manager` disappears      → value sourcing
- [ ] `iat`/`exp` come from the `now` argument truncated to whole seconds: mint at `.999999` → `iat` is the whole second      → value sourcing
- [ ] Allowed kind and issuer come from the key set entry, not the token: change an entry's `tessaro_kind` → `TOKEN_VERIFY_KEYS` refuses to load      → value sourcing
- [ ] Verify time comes from `now`; `principal_from_headers` with no `now` uses the wall clock: a token minted now passes, one minted an hour ago fails      → value sourcing
- [ ] OPA `data.tools[name].scope` comes from `ToolContract.scope`: change the scope → `policy/data/tools.json` changes only through `just contracts`      → value sourcing
- [ ] `get_my_leave` balance numbers, working days, the Amsterdam "today" and `record_ids` are produced by the People tool server (feature 14), not this library      → value sourcing (feature 14)

## Acceptance-criteria coverage
- AC-1, AC-2: tests `test_thin_thread.py`, `test_issue.py` · AC-3 to AC-5: `test_issue.py` · AC-6 to AC-8: `test_verify.py` · AC-9: `test_settings_and_keys.py` · AC-10: `test_devkeys.py` · AC-11, AC-12: `test_edge.py`
- AC-13, AC-14, AC-17: `test_contract.py` · AC-15: `test_thin_thread.py` · AC-16: `test_results.py` · AC-18, AC-19: `test_snapshots.py`
