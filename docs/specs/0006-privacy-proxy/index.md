# 0006. Privacy proxy with directory aware masking and an encrypted per conversation mapping

**Date**: 2026-10-09
**Status**: In Progress

## Summary

The privacy proxy sits between Tessaro's code and the model (DeepSeek). It looks like the normal OpenAI chat API, so the agent needs no special client. Before a call leaves the cluster, it replaces names, emails, phones, IBANs, home addresses and employee IDs with placeholders such as `<PERSON_1>`. When the answer comes back, it puts the real values back, including inside tool call arguments. Detection combines three sources: the employee directory from the dataset (so a Dutch name like Daan de Wit is always caught), a few patterns of our own, and the Presidio analyzer. The placeholders stay the same for the whole conversation and are stored encrypted in Redis for 24 hours after the last call. If the analyzer or Redis is down, the proxy refuses the call and never sends unmasked text.

## Requirements

**User stories**:
- As the master agent, I want an OpenAI compatible endpoint, so that I can call the model through the proxy with a stock OpenAI client (FR-P1, FR-A5).
- As a privacy reviewer, I want every personal value in every outgoing payload replaced by a placeholder, so that the model provider never sees employee data (FR-P2, NFR-5).
- As the master agent, I want answers and tool call arguments restored, so that a tool call names the real employee and the reply to the employee reads naturally (FR-P5).
- As the model, I want the same person to keep the same placeholder through a conversation, so that I can reason about who is who (FR-P4).
- As an operator, I want the proxy to refuse rather than leak when a dependency is down (FR-P8).

**Acceptance criteria** (the contract, each criterion is IDed and independently checkable). "Outgoing payload" means the exact body the proxy sends upstream; "the conversation" means every call carrying the same `X-Conversation-ID`.

- **AC-1**: `POST /v1/chat/completions` accepts an OpenAI chat completion request with `Authorization: Bearer <PROXY_CLIENT_KEY>` and an `X-Conversation-ID` header. It sends the masked body to `{PROXY_UPSTREAM_URL}/chat/completions` with `Authorization: Bearer <PROXY_UPSTREAM_API_KEY>` and returns the upstream JSON response with placeholders restored (AC-7). No inbound header is forwarded upstream, and the request's `user` field is removed from the outgoing payload.
- **AC-2**: Masking covers every string the model reads that can carry personal data: `content` of `system`, `user`, `assistant` and `tool` messages (a plain string, or each `text` part of a content array), and every string value inside the JSON of earlier `assistant` messages' `tool_calls[].function.arguments` (keys, numbers and booleans are not masked; the arguments are rebuilt with `json.dumps(..., ensure_ascii=False)`; arguments that are not valid JSON are masked as raw text). The optional `name` field of every message is removed from the outgoing payload. `tools` (definitions written by us, treated as trusted static content), `tool_choice`, `model`, `temperature` and every other parameter pass through unchanged.
- **AC-3**: The proxy masks these types: `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `IBAN_CODE` (from the analyzer, at a score of at least `PROXY_SCORE_THRESHOLD`, default 0.4, and from directory matches), `EMPLOYEE_ID` (pattern `TES-` plus five digits), `HOME_ADDRESS` (a street: one or more words, each capitalized or a lowercase particle such as `van`, `de`, `der`, the last ending in `straat`, `weg`, `laan`, `plein`, `gracht`, `kade`, `kreek`, `singel`, `dijk`, `pad`, `hof`, `steeg`, `park` or `plantsoen`, then a house number `\d+[A-Za-z]?(-\d+)?`; every street in `dataset/` must match it. Also a Dutch postcode `[1-9]\d{3} ?[A-Z]{2}`, and directory matches). The proxy also has its own `PHONE_NUMBER` patterns (Dutch mobile `(\+31|0) ?6` plus eight digits, and Dutch landline `(\+31|0)` plus a two or three digit area code and the rest up to nine digits, spaces or hyphens allowed) and its own `IBAN_CODE` pattern (`NL\d{2}[A-Z]{4}\d{10}`, optionally in groups of four separated by spaces), so these types never depend on the analyzer alone. The analyzer is asked for those four types only, so dates, amounts, cities, office names, team names and policy text stay readable: in "Daan de Wit's Berlin claim of €120.50 from 3 March for the Payments team", only the name is masked (FR-P6).
- **AC-4**: At startup the proxy loads the directory from `PROXY_DIRECTORY_PATH` (the dataset's `directory.json` export) and refuses to start if the file is missing or invalid. Every directory form (every entry in `forms`, plus `phone`, `iban`, `street` and `postcode`) is matched on the original text with a case insensitive regex bounded by Unicode word lookarounds (`(?<!\w)` and `(?!\w)`), with or without the analyzer. Matching never runs on a normalized copy, so offsets stay true. A form shared by several employees is still masked (keyed by its text, AC-5). Every form of the `dutch_name` trap employee (Daan de Wit) is masked even when the analyzer returns no results.
- **AC-5**: Placeholders have the form `<TYPE_N>`, numbered from 1 per type within a conversation. Within one conversation the same entity always gets the same placeholder: every directory name form of one employee (display name, first name, last name with and without tussenvoegsel, Zulip handle) shares one `PERSON` placeholder; that employee's email, employee ID, phone, IBAN, street and postcode each get their own placeholder of their own type; a directory name form shared by more than one employee (such as a common first name) and any value outside the directory are keyed by their normalized text. A placeholder issued in one conversation never restores in another.
- **AC-6**: The mapping lives in Redis under `proxy:conv:{<cid>}:fwd`, `:rev` and `:seq` (see *Feature design*). After any test conversation, no Redis key or value contains any directory string in plain text (entity type names in `seq` are allowed). All three keys expire `PROXY_MAPPING_TTL_HOURS` (default 24) hours after the latest call in that conversation: a `touch` script refreshes all three at the start of every request. If only some of the three keys exist, the request fails with 503 `mapping_store_unavailable` and the upstream is not called.
- **AC-7**: In the upstream response, every placeholder known to the conversation is replaced by its stored original (for a directory employee's `PERSON` placeholder, the employee's display name) in `choices[].message.content`, `choices[].message.refusal`, and every string value inside the JSON of `choices[].message.tool_calls[].function.arguments` (rebuilt with `json.dumps(..., ensure_ascii=False)`; raw text replacement if not valid JSON). Restore is one regex pass over `<[A-Z_]+_\d+>` with a function replacer, so restored text is never expanded again. `reasoning_content` and `logprobs` are removed. A placeholder shaped string the conversation never issued, and any altered form (lowercase, missing bracket), is left unchanged; an unissued well formed placeholder is logged as `unknown_placeholder` with the request ID and the placeholder only.
- **AC-8**: Fail closed. If the analyzer is unreachable, times out (`PROXY_ANALYZER_TIMEOUT_SECONDS`, default 5) or returns a non 200 status, the proxy returns 503 `analyzer_unavailable`. If Redis fails, it returns 503 `mapping_store_unavailable`. In both cases, and on any other error while masking, the upstream is never called. `PROXY_FAIL_CLOSED` must be `true`; any other value stops the service at startup.
- **AC-9**: Request errors use the OpenAI error shape `{"error": {"message", "type", "code"}}`: a missing or wrong bearer key gives 401 `invalid_api_key` (constant time comparison); a missing or malformed `X-Conversation-ID` (1 to 128 characters from `A-Z a-z 0-9 . _ : -`) gives 400 `missing_conversation_id`; `stream: true` gives 400 `streaming_not_supported`; a `model` other than `LLM_MODEL_AGENT` or `LLM_MODEL_TOOLS` gives 400 `model_not_allowed`; a content part that is not `text`, or the legacy `function_call` or `functions` fields, gives 400 `unsupported_content`; any other body that fails validation gives 400 `invalid_request` (FastAPI's default 422 handler is replaced, and no error body echoes any part of the input); a body over 1 MiB gives 413 `request_too_large`. None of them calls the analyzer, Redis or the upstream.
- **AC-10**: Upstream failures: a non 2xx upstream status gives 502 `upstream_error` (the upstream body is logged by status only, never returned); no response within `PROXY_UPSTREAM_TIMEOUT_SECONDS` (default 60) gives 504 `upstream_timeout`. The proxy never retries.
- **AC-11**: `/readyz` reports not ready (503) when the analyzer's `/health` or a Redis `PING` fails, using the `tessaro_core` readiness checks.
- **AC-12**: Each request logs one `model_call` line with request ID, conversation ID, model, a count of masked entities per type, upstream status and duration. No log line from the proxy contains message text, an original value or a decrypted mapping: a test runs the leak corpus with log capture and finds no directory string in any log line.
- **AC-13**: Leak scan. A test generates conversations from the real `dataset/`: every directory form, phone, IBAN, street and postcode of every person, placed in user sentences, in tool results (JSON) and in earlier tool call arguments, across several turns of one conversation. It runs them through the proxy against a capturing fake upstream and asserts that no outgoing payload contains any of those strings (case insensitive). In `just check` it runs with the in memory analyzer fake; with the `presidio` marker it runs against the real analyzer, locally after `just up` (`just leak-scan`) and in a CI job with the analyzer as a service container.
- **AC-14**: Two concurrent calls in one conversation that introduce the same new value get the same placeholder, and calls that introduce different new values of one type never share a number.
- **AC-15**: Overlapping detections never nest or double replace: the winner is the directory match, then a proxy pattern, then the analyzer; between equals, the longer span, then the earlier one. A span fully inside the winner is dropped; a span that only partly overlaps it is merged into one span covering both, with the winner's type and entity key (over masking is the safe direction). "daan.dewit@tessaro.example" is masked once, as `EMAIL_ADDRESS`, not as an email with a `PERSON` inside it.
- **AC-17**: A text segment longer than 10,000 characters is sent to the analyzer in chunks split on line breaks (a single longer line is split on whitespace), each at most 10,000 characters, with offsets shifted back to the segment. Directory and pattern matching always run on the whole segment.
- **AC-16**: The dataset's `directory` export gains `phone`, `iban`, `street` and `postcode` on every entry, in the existing deterministic, sorted output; the sensitive field test in `tessaro-dataset` still passes (none of these fields is marked `Sensitive`).

## Decision

**Chosen option**: Option 2: analyzer for detection, proxy owned recognizers and replacement, encrypted Redis mapping

The proxy is a FastAPI service that asks the Presidio analyzer where the personal data is, adds its own directory and pattern matches, swaps every span for a per conversation placeholder kept encrypted in Redis, calls DeepSeek, and restores the answer.

**Implementation skills**: `fastapi-templates` (`wshobson/agents`, `.claude/skills/fastapi-templates/`) · `async-python-patterns` (`wshobson/agents`, `.claude/skills/async-python-patterns/`)

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Feature design

**Code layout** (folder by feature, Clean Architecture: `masking/` is plain Python with no FastAPI, httpx, Redis or cryptography imports; it talks to ports):

```
services/privacy-proxy/src/tessaro_privacy_proxy/
  settings.py                 Settings (env only, fail fast)
  main.py                     build_app(settings): wires adapters, readiness checks, the route
  chat/                       the edge: route, request and response models, OpenAI error mapping, bearer check
  masking/                    domain: EntityType, Span, Placeholder, Directory and its matcher,
                              pattern recognizers, overlap resolution, normalization,
                              mask_request and restore_response use cases, ports
                              (Analyzer, MappingStore), typed errors
  analyzer/                   HttpAnalyzer (httpx) and FakeAnalyzer
  mapping/                    RedisMappingStore (redis asyncio, Lua), MappingCipher (AES-GCM, HMAC),
                              MemoryMappingStore (tests)
  upstream/                   UpstreamClient (httpx)
```

**Data model sketch** (Redis, under the proxy's `proxy:*` ACL prefix from spec 0001; `<cid>` is the conversation ID, and the braces are a literal Redis hash tag so the three keys always share one slot):

| Key | Type | Field → value | Notes |
|---|---|---|---|
| `proxy:conv:{<cid>}:fwd` | hash | hex `HMAC_SHA256(PROXY_LOOKUP_KEY, entity_key)` → placeholder | "Seen this before?" without the plain value |
| `proxy:conv:{<cid>}:rev` | hash | placeholder → base64(nonce ‖ AES-256-GCM ciphertext of the original text) | Associated data: `<cid>|<TYPE>`, so a value copied into another conversation or type fails to decrypt |
| `proxy:conv:{<cid>}:seq` | hash | entity type → last number issued | Counts each type separately |

- `entity_key` is `TYPE|emp:{employee_id}` for an employee's name forms, `TYPE|emp:{employee_id}:{field}` for that employee's other directory values (`email`, `employee_id`, `phone`, `iban`, `street`, `postcode`), and `TYPE|text:{normalized}` for everything else. Normalized means NFKC, casefolded, runs of whitespace collapsed to one space; for `PHONE_NUMBER` and `IBAN_CODE`, also all spaces and hyphens removed.
- The original stored in `rev` is the matched text, except for a directory employee's `PERSON` placeholder, whose original is the employee's display name (so a tool argument always carries the full name).
- Allocation is one Lua script (`allocate`): return the existing `fwd` field if present; otherwise `HINCRBY seq TYPE 1`, build `<TYPE_N>`, `HSET fwd` and `HSET rev` (the ciphertext computed before the call; a losing concurrent ciphertext is simply discarded), then `EXPIRE` all three keys.
- A second Lua script (`touch`) runs at the start of every request: if none of the three keys exists it does nothing (a new conversation); if all exist it sets the expiry on all three (sliding window); if only some exist it returns an error and the request fails closed (AC-6).
- Redis must run with `maxmemory-policy noeviction`, so keys never vanish one at a time under memory pressure (local compose and the cluster values both set it).
- In memory: `Directory`, a frozen model built from `directory.json`; each entry holds `employee_id`, `forms`, `email`, `phone`, `iban`, `street`, `postcode`. A name form shared by several entries is marked ambiguous at load time.

**State transitions**: a conversation mapping is either absent or live; it becomes live on the first allocation and returns to absent when the keys expire. Nothing deletes it early.

**Request flow** (`mask_request`, then upstream, then `restore_response`):
1. Validate auth, header, body size and body (AC-9).
2. Run `touch` (AC-6). Collect the text segments (AC-2). For each segment: directory and pattern matches on the whole segment, analyzer results per chunk (AC-17), at most 8 analyzer calls at once per request; resolve overlaps (AC-15).
3. Allocate placeholders (AC-5, AC-14), replace spans from the end of each segment backwards, rebuild the request.
4. Only now call the upstream (AC-8, AC-10).
5. Restore the response in one regex pass, using the `rev` hash (`HMGET` of the placeholders found, then decrypt), and remove `reasoning_content` and `logprobs` (AC-7).

**API surface**:

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/v1/chat/completions` | POST | header `X-Conversation-ID` (req); body `model` (req), `messages` (req), `tools` (opt), `stream` (opt, must be false) | OpenAI chat completion JSON, restored | bearer `PROXY_CLIENT_KEY` | 400, 401, 413, 502, 503, 504 (AC-8 to AC-10) |
| `/healthz` | GET | none | `{"status": "ok"}` | none | none |
| `/readyz` | GET | none | `{"status", "checks": {"analyzer", "redis"}}` | none | 503 not ready |

Analyzer call: `POST {PRESIDIO_ANALYZER_URL}/analyze` with `{"text", "language": "en", "entities": ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE"], "score_threshold": PROXY_SCORE_THRESHOLD}`; the response's `start` and `end` are Python string offsets.

**Value sourcing**:

| Action | Value produced / displayed | Source |
|---|---|---|
| mask | conversation the mapping belongs to | `X-Conversation-ID` header |
| mask | which spans are personal data | directory (`PROXY_DIRECTORY_PATH`), proxy patterns (code constants), analyzer response |
| mask | employee behind a name form | `Directory` entry's `employee_id` |
| mask | placeholder number | `proxy:conv:{<cid>}:seq` via the `allocate` script |
| mask | lookup field | HMAC of `entity_key` with `PROXY_LOOKUP_KEY` |
| mask | stored ciphertext | AES-GCM with `PROXY_MAPPING_KEY`, random 96 bit nonce, associated data `<cid>|<TYPE>` |
| mask | score threshold | `PROXY_SCORE_THRESHOLD` |
| forward | upstream URL and key | `PROXY_UPSTREAM_URL`, `PROXY_UPSTREAM_API_KEY` |
| forward | allowed models | `LLM_MODEL_AGENT`, `LLM_MODEL_TOOLS` |
| restore | original text | `proxy:conv:{<cid>}:rev`, decrypted |
| any | expiry | `PROXY_MAPPING_TTL_HOURS` |
| log | request ID | `tessaro_core` request ID middleware |
| log | entity counts | derived from the resolved spans |

**Key invariants**:
- The upstream is called only after every segment of the request has been masked successfully. There is no code path that forwards a segment the analyzer did not see.
- Redis never holds a personal value in plain text, in a key, a field or a value.
- A placeholder resolves only within its own conversation.
- Restore never introduces a value the conversation did not mask.
- The proxy never logs message text, originals or decrypted values.
- Fail closed cannot be switched off.

**Security model**:
- Compliance scope: GDPR personal data (fictional in this build, treated as real). Pseudonymised data that can be linked back is still personal data (PRD 11), so masking is defence in depth, not permission to send real data abroad.
- Callers: anyone holding `PROXY_CLIENT_KEY` (the master agent, later the tool servers' summaries). On the cluster, NetworkPolicy also allows only those pods in, and the proxy is the only pod allowed out to `api.deepseek.com` (NFR-12).
- The identity token from spec 0003 is not part of model traffic. The proxy forwards no inbound header, so a token sent by mistake never reaches DeepSeek.
- Keys: `PROXY_MAPPING_KEY` and `PROXY_LOOKUP_KEY` are separate 32 byte secrets, so a leaked lookup key cannot decrypt and a leaked mapping key cannot test guesses. Holding Redis data and both keys re-identifies at most 24 hours of conversations.
- Redis access is the `proxy:*` ACL user from spec 0001.

**Configuration required** (names from PRD 14.3 kept; new ones added to `.env.example`):
- `PROXY_CLIENT_KEY`: bearer key callers must present (at least 32 characters). New; `just keys` fills it.
- `PROXY_MAPPING_KEY`: base64url, 32 bytes, AES-256-GCM key. `just keys` fills it.
- `PROXY_LOOKUP_KEY`: base64url, 32 bytes, HMAC key. New; `just keys` fills it.
- `PROXY_DIRECTORY_PATH`: path to `directory.json`. New; locally `dataset/build/directory.json`.
- `PROXY_UPSTREAM_URL`, `PROXY_UPSTREAM_API_KEY`: DeepSeek base URL and key (the key may stay empty locally; tests use a fake upstream).
- `PROXY_MAPPING_TTL_HOURS` (24), `PROXY_FAIL_CLOSED` (must be `true`).
- `PROXY_SCORE_THRESHOLD` (0.4), `PROXY_ANALYZER_TIMEOUT_SECONDS` (5), `PROXY_UPSTREAM_TIMEOUT_SECONDS` (60): new, with defaults.
- `LLM_MODEL_AGENT`, `LLM_MODEL_TOOLS`, `PRESIDIO_ANALYZER_URL`, `REDIS_URL`: existing.
- New dependencies: `redis` (asyncio client) and `cryptography` (already in the lock) for the service; `fakeredis[lua]` for tests (the `allocate` script needs Lua). The upstream and analyzer are faked with `httpx.MockTransport`, no extra library.

**Critical test scenarios**:
- Happy path: a two turn conversation about Daan de Wit; the outgoing payloads hold `<PERSON_1>` both times, and a tool call `get_colleague(name="<PERSON_1>")` comes back as `"Daan de Wit"`, verifies **AC-1**, **AC-5**, **AC-7**
- Dutch name trap: every form of Daan de Wit masked with the analyzer fake returning nothing, verifies **AC-4**
- Leak scan over the generated corpus, fake and real analyzer, verifies **AC-13**, **AC-2**, **AC-3**
- Usefulness: the "Berlin claim of €120.50" sentence keeps everything but the name, verifies **AC-3**
- Analyzer down, Redis down: 503, capturing upstream saw zero calls, verifies **AC-8**
- Wrong key, no conversation ID, `stream: true`, unknown model, image part, 2 MiB body: the matching 4xx and zero upstream calls, verifies **AC-9**
- Concurrency: 20 parallel allocations of one value give one placeholder, verifies **AC-14**
- A turn that names only "Daan", then a tool call with `<PERSON_1>`: the argument comes back as "Daan de Wit", verifies **AC-7**
- Partly present keys (delete `seq` by hand): 503 and zero upstream calls, verifies **AC-6**
- Redis scan and log capture after the corpus contain no directory string, verifies **AC-6**, **AC-12**

## Build plan

Ordered as a tracer bullet: one real request through every layer first (directory match, Redis mapping, fake upstream, restore), then the other detectors, then the guards, then the proof.

1. [x] Extend the `directory` export with `phone`, `iban`, `street`, `postcode`, with its tests, satisfies **AC-16**
2. [x] Thin thread: `Settings` (all variables above, fail fast, `PROXY_FAIL_CLOSED` only `true`), `just keys` filling the three proxy keys when empty, `.env.example`; the `Directory` loader and matcher; `MappingCipher`; `RedisMappingStore` with the `allocate` script and sliding expiry; `mask_request` and `restore_response` for plain string content; `UpstreamClient`; the route with bearer and conversation ID checks. One test (fakeredis, fake upstream) masks and restores Daan de Wit across two turns; one manual run against `just up` Redis, satisfies **AC-1**, **AC-4**, **AC-5**, **AC-6**
3. [x] Detectors: `HttpAnalyzer` (with chunking) and `FakeAnalyzer`, the `EMPLOYEE_ID`, `HOME_ADDRESS`, Dutch phone and NL IBAN patterns, overlap resolution with merging, the score threshold, the usefulness sentence, satisfies **AC-3**, **AC-15**, **AC-17**
4. [x] Full scope: system and tool roles, content arrays, earlier tool call arguments, dropping `user`, message `name` and inbound headers; single pass restore of content, `refusal` and tool call arguments, removing `reasoning_content` and `logprobs`, the unknown placeholder warning, satisfies **AC-2**, **AC-7**
5. [x] Guards: fail closed on analyzer and Redis errors (including partly present keys), request validation with the replaced 422 handler and the 1 MiB limit, upstream 502 and 504, readiness checks, OpenAI error shape, satisfies **AC-8**, **AC-9**, **AC-10**, **AC-11**
6. [x] Concurrency test for `allocate`, the `touch` expiry test, and `maxmemory-policy noeviction` in `compose.yaml`, satisfies **AC-14**, **AC-6**
7. [x] The `model_call` log line and the log capture test, satisfies **AC-12**
8. [x] Leak scan: corpus generated from `dataset/`, the `presidio` marker (skipped unless `PRESIDIO_LIVE=1`), `just leak-scan`, and a second CI job that runs it with the analyzer as a service container, satisfies **AC-13**

## Consequences

**Positive**:
- The model never sees a dataset name, email, phone, IBAN, address or employee ID, and the leak scan proves it on every run.
- The Dutch name trap is caught by construction, whatever the analyzer's language model does.
- The agent uses a stock OpenAI client; the proxy is invisible apart from the base URL, the key and one header.
- Fail closed: the worst case is an outage, never a leak.

**Negative / tradeoffs**:
- The analyzer and Redis are now on the critical path of every answer. If either is down, Tessaro cannot answer anything (by design, FR-P8).
- Over masking: a last name that is also an ordinary word (for example "Wit", "Vos") is masked wherever it appears as a whole word. Answers may read a little oddly; this is the safe direction.
- With `LOCATION` off, a city on its own ("I live in Utrecht") passes unmasked. Accepted under FR-P6; the street and postcode are what identify a home.
- A directory employee's `PERSON` placeholder restores to their display name, so "Daan" in a question may come back as "Daan de Wit" in the answer.
- No streaming. A later need for streamed replies means a buffered restore design.
- Redis plus both keys is a re-identification store for up to 24 hours of conversations; the keys must be handled like any other secret.
- Masked data that can be linked back is still personal data; real employee data still needs an EU hosted model (PRD 11).
- No rate limiting on the proxy: its only callers are our own services behind a key and NetworkPolicy. A runaway agent loop costs DeepSeek credit until the agent's own limits stop it.

**Neutral**:
- The `directory.json` contract grows four fields; the proxy reads the export, never the dataset library, so the cluster can feed it from Authentik later with the same shape.
- A user who types a placeholder shaped string (`<PERSON_1>`) sees it restored if that placeholder exists in their own conversation; it only ever reveals values already in that conversation.
- New dependencies: `redis`, `fakeredis[lua]` (dev).

## Follow-up

- [ ] Feature 15 (master agent): send `X-Conversation-ID` (the LangGraph thread ID), use `PROXY_CLIENT_KEY` as the OpenAI `api_key`, and never set `stream`.
- [ ] Tool servers' summaries (DeepSeek Flash) must also go through the proxy; decide their conversation ID (likely the request ID) when the first tool server summarizes.
- [ ] Cluster (features 9 to 11): a nightly job builds `directory.json` from Authentik in the same shape (FR-P3), mounts it, and restarts the proxy.
- [ ] Features 15 and 16: emit Langfuse generations from the proxy with masked payloads only (FR-P7); this spec logs entity counts and nothing else.
- [ ] Pin the `presidio-analyzer` image version in `compose.yaml` and the CI job (it is `latest` today).
- [ ] Spec 0003 says the privacy proxy "passes the token along opaquely"; the proxy never sees the token. Update that line with `/architect`.
- [ ] Check during `/develop` whether Presidio's phone recognizer covers Dutch numbers in its default regions (as of my knowledge it does not; the Dutch mobile pattern and directory matches cover the dataset either way).
- [ ] Agent Skills and MCP servers for Presidio and `cryptography`: not searched (engineer chose "later").
