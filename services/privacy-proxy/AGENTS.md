# privacy-proxy

## Overview

OpenAI compatible proxy in front of the LLM that pseudonymises personal data with Presidio and stores encrypted mappings in Redis.

## Stack

- Python 3.13, FastAPI via `tessaro_core.create_app`, import name `tessaro_privacy_proxy` (src layout)
- Dependencies: tessaro-core, fastapi, httpx, redis (asyncio), cryptography (AES-GCM, HMAC), pydantic-settings; tests use `fakeredis[lua]`
- Spec: [0006](../../docs/specs/0006-privacy-proxy/index.md); runtime checks in its `verify.md`
- Listens on `8080` in the cluster; `just dev privacy-proxy` serves it on `18082` locally

## Commands

```bash
just dev privacy-proxy
uv run pytest services/privacy-proxy/tests --cov=tessaro_privacy_proxy -q
just image privacy-proxy
just leak-scan   # the presidio marked leak scan, against the real analyzer from `just up`
```

To run it locally, `.env` needs `PROXY_CLIENT_KEY`, `PROXY_MAPPING_KEY` and `PROXY_LOOKUP_KEY` (`just keys`) and a current `dataset/build/directory.json` (`just dataset --anchor 2026-10-07T10:00+02:00`); without them startup refuses. `PROXY_UPSTREAM_API_KEY` is required too, unless `PROXY_UPSTREAM_URL` is a loopback stub (plain `http` is accepted only there).

## Conventions

- `main.py` exposes `build_app(settings)` for tests and `app` for uvicorn; settings live in `settings.py` (a `ServiceSettings` subclass).
- Release values: `deploy/values/privacy-proxy.yaml`, rendered by the shared chart.
- Layout: `chat/` is the edge (route, OpenAI error shape), `masking/` the domain (plain Python, no FastAPI, httpx, Redis or cryptography imports; it talks to the `Analyzer` and `MappingStore` ports), `analyzer/`, `mapping/` and `upstream/` are adapters.
- Fail closed: the upstream is called only after every segment is masked; any analyzer or Redis error is a 503, and `PROXY_FAIL_CLOSED` accepts only the literal `true`.
- Overlaps (`masking/spans.py`): directory beats pattern beats analyzer; a merged span wider than its best span is keyed by its own text, never by an employee; analyzer possessives (`'s`) are trimmed first.
- Redis: `mapping_redis()` retries once on a dropped connection (both Lua scripts are safe to repeat); `readiness_redis()` never retries. Nothing personal is stored in plain text (HMAC fields, AES-GCM values).
- Mapping integrity: each `rev` value is `<lookup field>:<ciphertext>` with the lookup field in the AES-GCM associated data, and `originals()` checks `fwd[field]` still names the placeholder; changing the stored format means changing both `mapping/cipher.py` and `mapping/redis_store.py`.
- Request boundary: every string is NFC normalized before detection and sent upstream as NFC; only the top level parameters in `masking/models.py` `FORWARDED_PARAMETERS` go upstream, every other one is dropped.
- Logs: one `model_call` or `model_call_failed` line per request, counts and codes only, never message text or exception messages.
- Tests use the `FakeAnalyzer`, fakeredis and a capturing fake upstream (`tests/conftest.py`); `PRESIDIO_LIVE=1` enables the `presidio` marker.
- MCP servers: redis/mcp-redis (recommended, for inspecting mapping keys while debugging) · Declined: `redis-core` (redis/agent-skills), `presidio-pii-detection` (testland, third party); no credible skill found for `cryptography`.
- Root `AGENTS.md` rules apply.

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
