# Review, feat/privacy-proxy, 2026-10-10

**Reviewed by**: claude-sonnet-5-5 (author on a different session; model not recorded)
**Scope**: 61 files (about 1,620 source lines in services/privacy-proxy), branch vs main
**Verdict**: Changes requested

## Summary
The privacy proxy masks chat requests with directory, pattern and Presidio spans, keeps per conversation placeholders encrypted in Redis, and restores answers including tool call arguments. Design and fail closed behaviour are solid and match spec 0006; 119 tests pass at 99% coverage. One real defect: a crash on user controlled input in the directory matcher (poisons a conversation permanently). The remaining findings are narrow leak paths (Unicode normalization, chunk boundaries, silently dropped analyzer hits) and crypto/config hardening.

## Major
### 🟠 Directory matcher raises KeyError on dotless i and dotted capital I, `services/privacy-proxy/src/tessaro_privacy_proxy/masking/directory.py:112`
**Problem**: The pattern is compiled with `re.IGNORECASE`, but `_span` looks the match up with `text[start:end].casefold()`. Python's `re` treats `i` as equal to `ı` (U+0131) and `İ` (U+0130), whose `casefold()` is not `i` (`ı` stays `ı`, `İ` becomes `i` plus a combining dot). So a form such as `bakir` matches the text `BAKıR` or `BAKİR`, then `self.targets[...]` raises `KeyError`. Reproduced against `Directory.find`.
**Why it matters**: The route catches it as a 500 `internal_error`. Because the agent resends the full history each turn, one message containing such a string (any employee name with an `i`, written with Turkish or similar letters) makes every later call in that conversation fail. It is fail closed (nothing leaks), but it is a trivially triggerable denial of service. No test covers it.
**Suggested fix**: Make matching and lookup use the same folding: either look up by the matched text through the same function used to build `by_form` and fall back safely when the key is missing, or build the pattern from a deliberately folded alphabet. A missing key should never raise; treat a regex match with no target as masked text keyed by its own text. Add a test with `ı`/`İ`.

## Minor
### 🟡 Directory and pattern matching is not Unicode normalized, `masking/directory.py:89`, `masking/patterns.py:20`
**Problem**: Matching runs on the raw text by design (AC-4), so a decomposed (NFD) name misses. Verified: `"Zoé Bakir"` against a `Zoë Bakir` form masks only `Bakir`; the first name is left to the analyzer alone. Only the key normalization (`entities.normalize`) uses NFKC.
**Why it matters**: macOS or copy pasted NFD text can send a known employee's first name upstream if the analyzer misses it.
**Suggested fix**: NFC normalize every string at the request boundary (before detection and before sending), so offsets stay true and the outgoing text is the normalized one. Add the form variants to the leak corpus.

### 🟡 Analyzer chunks have no overlap, `masking/chunks.py:23`
**Problem**: Long single lines (typical for JSON tool results, which have no newlines) are split on word boundaries with no overlap, so a multi word name or a spaced non Dutch IBAN that straddles a 10,000 character boundary is analyzed as two fragments.
**Why it matters**: Dutch IBANs, directory forms and the proxy patterns still run on the whole text, so the exposure is non directory names and foreign IBANs or phone numbers; low probability per value, but this is the one place a long tool result can leak.
**Suggested fix**: Overlap chunks by a few hundred characters and dedupe spans in `resolve`, or at least split JSON tool results per string leaf first.

### 🟡 Out of range analyzer hits are dropped silently, `masking/mask.py:145`
**Problem**: `_analyze` filters `0 <= r.start < r.end <= len(piece)` and discards anything else with no error or log.
**Why it matters**: A malformed or differently encoded reply (offset unit mismatch, a truncated chunk) turns into unmasked text with a 200 response, the opposite of the fail closed rule. The same holds for a reply the HTTP layer cannot detect as wrong.
**Suggested fix**: Raise `AnalyzerUnavailable` (503) when any hit for a requested type has invalid offsets; keep silently ignoring only unrequested types and low scores.

### 🟡 Top level parameters other than `tools` are forwarded unmasked, `masking/models.py:63`, `masking/mask.py:119`
**Problem**: Everything not declared passes through. Spec AC-2 trusts `tools`, but `prediction` (carries message text), `metadata`, `stop`, `logit_bias`, `response_format` and `tool_choice` are forwarded too.
**Why it matters**: `prediction.content` is free text and would reach the provider unmasked; the others are low risk today but unchecked.
**Suggested fix**: Replace the pass through with an allowlist of numeric and enum parameters plus `tools`, `tool_choice`, `response_format`; reject or mask `prediction` and `metadata`.

### 🟡 Ciphertext is not bound to its placeholder, `mapping/cipher.py:34`
**Problem**: Associated data is `cid|TYPE`, so two entries of one type in one conversation are interchangeable. Anyone with Redis write access can swap `rev` values for `<PERSON_1>` and `<PERSON_2>` and the proxy restores the wrong person without noticing.
**Why it matters**: Wrong value restored (the risk named in the brief), only under Redis tampering, so not a blocker. It matches the spec as written.
**Suggested fix**: Allocate the number first (or encrypt inside the script path), then include the placeholder in the associated data; update spec 0006.

### 🟡 Key handling is lenient, `mapping/cipher.py:18`, `settings.py:38`
**Problem**: `urlsafe_b64decode` is called without validation, so stray characters are discarded and a malformed value that still decodes to 32 bytes is accepted. Nothing rejects `PROXY_MAPPING_KEY == PROXY_LOOKUP_KEY`, which defeats the two key separation the docstring promises. `decrypt` also lets `UnicodeDecodeError` from `opened.decode()` escape (outside the `try`), giving a 500 rather than the mapped error.
**Suggested fix**: Use `validate=True` on a re-padded input, reject equal keys at startup, and widen the `try` in `decrypt`.

### 🟡 Upstream settings do not fail fast, `settings.py:25`
**Problem**: `proxy_upstream_api_key` defaults to an empty `SecretStr`, and `proxy_upstream_url` accepts plain `http://`. AGENTS.md requires config to fail at startup on a missing variable.
**Why it matters**: A missing key surfaces only as a 502 per request; an `http` URL would send masked traffic and the API key in clear.
**Suggested fix**: Make the key required (minimum length) and require `https` outside a loopback host.

### 🟡 Word boundary lets IDs and numbers slip when glued to word characters, `masking/patterns.py:20`, `masking/directory.py:89`
**Problem**: `(?<!\w)`/`(?!\w)` treat `_` and letters as word characters. Verified: `employee_TES-00012`, `x TES-00012abc` and `phone_0612345678` produce no span. Spec AC-4 mandates these lookarounds, so this is a spec level gap.
**Why it matters**: Snake case keys, filenames and log fragments in tool results can carry employee IDs and phone numbers past the proxy (the analyzer may still catch phones).
**Suggested fix**: For `TES-\d{5}` and digit patterns use boundaries on alphanumerics or digits only (`(?<![A-Za-z0-9])`), keep `_` as a separator.

## Nits
- ⚪ `masking/jsontext.py:11`, JSON keys and non string scalars in tool call arguments are never masked (matches AC-2); a phone number sent as an integer would pass. Worth a sentence in the spec risks.
- ⚪ `devkeys.py:33`, an `export NAME=value` line is not recognised, so a duplicate line would be appended; the write is not atomic and does not set file mode.
- ⚪ `mapping/redis_store.py:65`, the Lua source goes with every `EVAL`; `register_script` would save bandwidth.

## Strengths
- Fail closed is applied consistently: analyzer errors, bad replies, Redis errors, partial key sets and unexpected exceptions all end in a non 2xx before the upstream call, and `PROXY_FAIL_CLOSED` only accepts a literal `true`.
- Placeholder allocation is a single atomic Lua script that is safe to retry, with hash tagged keys; per conversation AES-256-GCM with random nonces, separate HMAC lookup key, and associated data binding conversation and type.
- Restore is one pass with a function replacer (no second expansion), rebuilds tool call arguments through `json.dumps` so restored values cannot break JSON escaping, and drops `reasoning_content` and `logprobs`.
- Request logging is limited to codes, counts, placeholders and exception class names; error bodies echo nothing, the 422 handler is replaced, and upstream bodies are never returned.
- Strong test suite: 119 tests, 99% coverage, a corpus driven leak scan against a capturing upstream and an optional real Presidio run, plus log capture assertions.

## Test coverage
119 passed, 1 skipped (live Presidio), 99% on the package (only `devkeys.py:68`, the `__main__` guard, is uncovered). Covered well: fail closed paths, concurrency, restore, scope of masking, logs. Missing: Unicode edge cases in the directory matcher (the Major above), NFD input, a chunk boundary straddling a multi word name or spaced IBAN, an analyzer reply with out of range offsets, and passthrough parameters such as `prediction`.
