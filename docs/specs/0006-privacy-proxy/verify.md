# Verify: privacy proxy · spec 0006 · updated 2026-10-09
_Steps derived from spec 0006 acceptance criteria and its Value sourcing table. `/check verify` runs these; `/test` locks the durable ones._

Setup for the manual steps: `just up`, `just keys`, `just dataset --anchor 2026-10-07T10:00+02:00`, then `just dev privacy-proxy` (port 18082). Point `PROXY_UPSTREAM_URL` at a local echo server (or a capturing stub) so you can read the outgoing payload; send requests with `Authorization: Bearer $PROXY_CLIENT_KEY` and `X-Conversation-ID: verify-1`.

## UI / manual
- [ ] POST "Is Daan de Wit in today?" → the upstream receives "Is <PERSON_1> in today?"; a reply of `<PERSON_1>` comes back as "Daan de Wit" → AC-1, AC-5, AC-7
- [ ] Reply with a tool call `{"name": "<PERSON_1>"}` after a turn that only said "Daan" → the agent receives `{"name": "Daan de Wit"}` → AC-7
- [ ] Send a system, a user (content array, with `name`), an assistant tool call and a tool message, plus `user` and `tools` → only `tools` keeps names; `name` and `user` are gone upstream → AC-2
- [ ] Send "Daan de Wit's Berlin claim of €120.50 from 3 March for the Payments team" → only the name becomes a placeholder → AC-3
- [ ] Send every form of Daan de Wit (display name, first, last with and without `de`, email, `TES-01005`, `@**Daan de Wit**`, phone, IBAN, street, postcode) → none reaches the upstream (the directory catches them without the analyzer; `test_detectors.py` proves that with no analyzer at all) → AC-4
- [ ] Stop the analyzer (`docker compose stop presidio-analyzer`) → 503 `analyzer_unavailable`, the upstream stub sees nothing → AC-8
- [ ] Stop Redis → 503 `mapping_store_unavailable`, the upstream stub sees nothing → AC-8
- [ ] `redis-cli DEL 'proxy:conv:{verify-1}:seq'` after a call → the next call in `verify-1` gives 503 `mapping_store_unavailable` → AC-6
- [ ] Wrong key 401, no `X-Conversation-ID` 400, `stream: true` 400, model `gpt-4o` 400, an `image_url` part 400, a 2 MiB body 413, invalid JSON 400 `invalid_request` with no echo → AC-9
- [ ] Upstream stub returns 500 → 502 `upstream_error`; stub sleeps past `PROXY_UPSTREAM_TIMEOUT_SECONDS` → 504 `upstream_timeout`; the stub is called once (no retry) → AC-10
- [ ] `curl localhost:18082/readyz` with everything up → 200; with the analyzer stopped → 503 with `"analyzer": false` → AC-11
- [ ] The proxy's stdout holds one `model_call` line per request (conversation ID, model, entity counts, upstream status, duration) and no message text → AC-12

## Value sourcing
- [ ] Two different `X-Conversation-ID` values naming the same person → each gets its own mapping; a placeholder from one does not restore in the other → conversation from the header
- [ ] A shared first name (two employees) → masked, keyed by its text; a full name → keyed by the employee → which spans: directory, patterns, analyzer
- [ ] `redis-cli HGETALL 'proxy:conv:{verify-1}:fwd'` → hex HMAC fields only; `:rev` → ciphertext only; `:seq` → type counters → lookup field and stored ciphertext
- [ ] Change `PROXY_MAPPING_KEY` and restart, then reply with an old placeholder → 503 `mapping_store_unavailable` (it no longer decrypts) → stored ciphertext key
- [ ] Set `PROXY_SCORE_THRESHOLD=0.9` → a weak analyzer guess passes unmasked; back at 0.4 it is masked → score threshold
- [ ] Set `LLM_MODEL_TOOLS` to a new name → that model is accepted, the old one refused → allowed models
- [ ] `redis-cli TTL` on all three keys right after a call → `PROXY_MAPPING_TTL_HOURS` × 3600 on each → expiry
- [ ] The upstream stub sees only `Authorization: Bearer $PROXY_UPSTREAM_API_KEY` and no `X-Request-ID` or caller header → upstream URL and key
- [ ] The `model_call` line's `request_id` matches the `X-Request-ID` response header → request ID

## Commands
- [ ] `uv run pytest services/privacy-proxy/tests -q` → all pass, coverage above 80% → AC-1 to AC-17
- [ ] `just leak-scan` (after `just up`) → 1 passed against the real analyzer → AC-13
- [ ] `uv run pytest libs/tessaro-dataset/tests/test_exports.py -k proxy -q` → passes → AC-16
- [ ] `just check` → green → all
- [ ] The CI `privacy leak scan` job passes on the PR → AC-13

## Acceptance-criteria coverage
- AC-1 manual 1, `test_thin_thread.py` · AC-2 manual 3, `test_scope_and_restore.py` · AC-3 manual 4, `test_detectors.py`, `test_guards.py` · AC-4 manual 5, `test_detectors.py`, `test_startup.py` · AC-5 manual 1, value sourcing 1 and 2, `test_mapping.py` · AC-6 manual 8, value sourcing 3 and 7, `test_mapping.py` · AC-7 manual 1 and 2, `test_scope_and_restore.py` · AC-8 manual 6 and 7, `test_guards.py`, `test_startup.py` · AC-9 manual 9, `test_guards.py` · AC-10 manual 10, `test_guards.py` · AC-11 manual 11, `test_tessaro_privacy_proxy_health.py` · AC-12 manual 12, `test_guards.py` · AC-13 `just leak-scan`, `test_leak_scan.py`, CI · AC-14 `test_mapping.py` · AC-15 `test_detectors.py` · AC-16 `test_exports.py` · AC-17 `test_detectors.py`
