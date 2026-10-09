# 0006. Privacy proxy: rationale

## Context

Every model call in Tessaro goes to DeepSeek, a provider outside the EU, and carries employee questions and tool results. Those are full of personal data: names, emails, phones, IBANs, home addresses and employee IDs. The PRD requires that this data never reach the model or the traces unmasked (FR-P1 to FR-P8, NFR-5), that the same person keeps one placeholder through a conversation, and that the proxy refuses to call the model when it cannot mask. The data in this build is fictional, but the design has to hold for real data. Pseudonymised data that can be linked back is still personal data under GDPR, so masking is a safeguard on top of data residency, not a replacement for it.

Three things make this harder than running a detector over a string. First, generic name detectors miss names from other languages, and the dataset plants one on purpose (Daan de Wit, the `dutch_name` trap). Second, the model does not only write prose: it writes tool calls whose arguments must carry the real employee once they leave the proxy, and the agent then sends those restored arguments back in the next request. Third, masking too much ruins answers: "your Berlin claim of €120.50 is paid on 3 March" is useless if the city, amount and date disappear (FR-P6).

The proxy lives in the `assistant` namespace with the master agent and Redis (spec 0001), uses the Presidio analyzer already in `compose.yaml`, and reads the employee directory that spec 0002 exports for it. It must be testable on a laptop now; Authentik, Langfuse and the cluster arrive later. It is a GA tier feature: the core of Tessaro's privacy story.

## Options considered

### Option 1: Presidio end to end, per request

The proxy sends each text to the analyzer and then to Presidio's anonymizer service, with the directory and patterns passed as ad hoc recognizers in each analyzer request. The anonymizer's replace or encrypt operator produces placeholders; nothing is stored between requests.

**Pros**:
- The least code of our own: Presidio does detection and replacement.
- No state, so no Redis dependency and no key management for a mapping.

**Cons**:
- Placeholders are not consistent across turns: `<PERSON>` or a fresh number per request breaks FR-P4, and the model loses track of who is who.
- Restoring tool call arguments needs the mapping the anonymizer threw away; Presidio's encrypt operator could carry it inside the text, but then the ciphertext goes to the model.
- Sends the whole directory with every analyzer call.

### Option 2: Analyzer for detection, proxy owned recognizers and replacement, encrypted Redis mapping (chosen)

The analyzer finds `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER` and `IBAN_CODE`. The proxy adds directory matches and its own patterns, resolves overlaps, and swaps spans for `<TYPE_N>` placeholders from a per conversation mapping in Redis (HMAC lookup, AES-GCM values, sliding 24 hour expiry). It restores answers and tool call arguments from the same mapping.

**Pros**:
- Meets every FR-P requirement, including consistent placeholders and restored tool arguments.
- The directory and patterns are plain Python, tested without any container; the Dutch name trap does not depend on spaCy.
- Redis never holds plain text, and a leaked lookup key cannot decrypt anything.

**Cons**:
- More code of our own on a security critical path: span resolution, the allocation script, the cipher.
- Redis joins the analyzer as a hard dependency; either one down means no answers.

### Option 3: An off the shelf LLM gateway with a PII guardrail

Run an existing OpenAI compatible gateway (LiteLLM's proxy is the best known, as of my knowledge) with its Presidio guardrail, which masks requests and can unmask the output.

**Pros**:
- OpenAI compatibility, upstream handling, retries and logging come for free and are maintained by others.
- Built in hooks for tracing tools like Langfuse.

**Cons**:
- Its masking is per request; there is no per conversation, encrypted, expiring mapping, so FR-P4 needs custom plugin code anyway.
- Restoring inside tool call arguments and the directory recognizer would also be custom code, written against a large third party framework instead of our own small service.
- A large dependency with its own release pace sitting on the most sensitive path, outside our Clean Architecture and test conventions.

### Option 4: Presidio as a library inside the proxy

Same as Option 2, but import `presidio-analyzer` and a spaCy model into the proxy process instead of calling the analyzer container.

**Pros**:
- No network hop and one fewer moving part to be unreachable.

**Cons**:
- The proxy image grows by the spaCy model (around 1 GB) and starts slowly.
- The PRD places the analyzer in the `platform` namespace as its own workload; this would fold it in.
- Unit tests either load the model or need the same fake seam Option 2 already has.

## Rationale

Option 2 is the only option that satisfies the conversation level requirements without bending them. Consistent placeholders (FR-P4) and restored tool arguments (FR-P5) both need a mapping that outlives a single request, and once that mapping exists, it has to be stored somewhere other services cannot read in plain text. Spec 0001 already gave the proxy its own Redis prefix and `PROXY_MAPPING_KEY` for exactly this. Options 1 and 3 would each need the same mapping built as custom code around a framework that was not designed for it.

The directory recognizer and the patterns run in the proxy rather than as Presidio ad hoc recognizers because they are the part that must never fail: the Dutch name trap and the employee IDs are caught by code we test in milliseconds with no container. The analyzer adds what a directory cannot know: names of people outside Tessaro, and emails, phones and IBANs that are not in the dataset. Asking it for four types only, with `LOCATION` and `DATE_TIME` off, is what keeps FR-P6 answers useful; home addresses are caught by the street and postcode patterns plus the directory instead.

The smaller calls follow the same pull toward safety with the least machinery: HMAC with its own key so Redis contents cannot be checked against a list of 33 names; AES-GCM with the conversation and type as associated data so a value copied elsewhere fails to decrypt; a sliding expiry so a live conversation never renumbers; fail closed on both dependencies; no streaming, because the agent posts one finished reply and a split placeholder is a bug class worth avoiding. Option 4's fewer moving parts do not outweigh a 1 GB model in every proxy build and test run.

### Smaller calls made in this spec

- **Directory matcher**: one compiled, case insensitive regex alternation of all forms, longest first, bounded by Unicode word lookarounds, run on the original text. The directory is a few hundred forms, so this is fast and has no dependency. Runner up: an Aho-Corasick library, worth it only for tens of thousands of forms.
- **Overlap order**: directory, then proxy patterns, then the analyzer; then longer span, then earlier. The directory is exact, so it wins; the email case shows why nesting must never happen.
- **Score threshold 0.4**: a missed name is a leak, an extra mask costs a little quality.
- **Allowed models**: the existing `LLM_MODEL_AGENT` and `LLM_MODEL_TOOLS`, so model names stay configuration (PRD 11) without a third list. Runner up: a dedicated `PROXY_ALLOWED_MODELS`.
- **`PROXY_FAIL_CLOSED`**: kept because PRD 14.3 names it, but only `true` is accepted, so it documents the behaviour without being a switch. Runner up: remove the variable.
- **Analyzer fan out**: at most 8 concurrent analyzer calls per request, one per text segment. Enough for a long conversation history without flooding the analyzer.
- **Upstream**: 60 second timeout, no retry, since the agent's client already retries.
- **`reasoning_content` and `logprobs`**: dropped, fewer places for data to travel.
- **Restored form**: a directory employee's `PERSON` placeholder restores to their display name, not the first form seen, so a tool argument always carries the full name.
- **Partial overlaps**: merged into one span with the winner's type; a half masked name would be a leak.
- **Expiry consistency**: a `touch` script plus `noeviction` keeps the three keys living and dying together; partly present keys fail closed rather than renumber.
- **Test doubles**: `fakeredis[lua]` for the store (the allocation script needs Lua) and `httpx.MockTransport` for the analyzer and upstream, so `just check` needs no containers; the real analyzer runs under the `presidio` marker in its own CI job.

## Update 2026-10-09: findings from /check verify

Running the real proxy against live Presidio and Redis showed three gaps in the contract, and one spot where the code was looser than the spec. The engineer chose each fix below.

**Merged span key (AC-5 vs AC-15).** "Jan Bakker" (not an employee) is found by the analyzer, and its surname "Bakker" is a directory form. The old AC-15 merged the two and kept the employee's key, so the reply named Pieter Bakker. That breaks AC-5 ("any value outside the directory is keyed by its text") and would point a tool call at the wrong person.
- Chosen: a merged span wider than an employee's directory form is keyed by its own text. Still fully masked; restores exactly what was written. Con: a real employee written with extra words loses the link to their usual placeholder.
- Rejected: keep the employee key. Simple, but restores the wrong person.
- Rejected: do not merge, mask the parts apart. Leaks the extra words (the first name) and still restores the wrong person.

**Possessive.** Presidio includes `'s` in a name span ("Daan de Wit's"). With the new merge rule that would give Daan a second placeholder. Trimming a trailing `'s` or `’s` off analyzer spans lets the directory match win cleanly. Con: a name that truly ends in `'s` loses two characters from its analyzer span; the directory and patterns still cover dataset values.

**Redis retry (AC-8).** After a Redis restart, one request failed on a stale pooled connection. One retry on a connection error or timeout, with health checks on idle connections, removes that without weakening fail closed: both Lua scripts are safe to repeat, and a second failure still gives 503. Rejected: no retry, which leaves a spurious 503 after every Redis restart.

**Fail closed setting (AC-8).** The spec already said only `true` is allowed; pydantic's bool parsing also accepts `yes`, `1` and `on`. The criterion now names the literal rule so the code can be tightened.

**Log line on failure (AC-12).** Failed requests already logged `model_call_failed`; AC-12 now says so, so "one line per request" holds for errors too.
