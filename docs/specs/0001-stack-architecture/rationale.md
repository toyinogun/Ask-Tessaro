# 0001. Rationale: Python monorepo stack and architecture

Decision record for [index.md](index.md). Not needed to build.

## Context

> ⚠️ Premise note: The PRD splits our own code into about ten deployables for a solo builder, which looks like premature microservices (they usually cost about 3x the effort to build and run). Here the split is load bearing for a different reason. Team isolation by namespace and NetworkPolicy is a core claim of the demo (step 8: the agent pod cannot reach Frappe), and the PRD's security model depends on separate identities per tool server. So the split stays, and the cost is contained instead: one repo, one language, shared libraries, one chart, one service template. Separately, a container orchestration platform is normally overkill for a small team, but the k3s cluster already exists and running on it is part of the brief.

The PRD fixes every off the shelf system (Zulip, Authentik, Frappe HR, Zammad, Snipe-IT, Seatsurfing, BookStack, Temporal, OpenFGA, OPA, Presidio, Langfuse, Loki) and some code level tools (LangGraph, MCP, SOPS, Helm). Everything around our own code was undecided: language, repo shape, tooling, local loop, how services talk, packaging, delivery and secrets handling.

The forces that shaped the choice:

- **One builder, many components.** Every extra language, repo or chart template multiplies upkeep.
- **No cluster for now.** All of Foundation (no cluster) must be built and tested on a laptop. The cluster phase starts with a read only investigation whose findings could change delivery choices.
- **Security is the product.** Every tool call must be authorized and audited at one choke point; writes must be impossible for human tokens; isolation must be provable.
- **Portfolio audience.** Reviewers should find the code, the CI and the desired cluster state easily, and read the code without exotic tooling.
- **Fixed Python dependencies.** The Temporal Python SDK, LangGraph and Presidio are Python libraries.

## Options considered

### Option 1: Python uv monorepo, MCP everywhere, Compose locally, one shared chart, Argo CD (chosen)

Everything as described in the index.

**Pros**:
- One toolchain and lockfile; shared token and contract libraries change atomically with their users.
- One gateway and one protocol for reads and writes, so one place to enforce and audit.
- The laptop loop is light and needs no cluster.

**Cons**:
- An in cluster GitOps controller to run, and SOPS plus a KSOPS plugin to set up.
- In memory fakes can drift from the real systems.

### Option 2: Python services plus a Go gateway, helmfile delivery

The gateway in Go with OPA embedded as a library; everything else in Python; releases applied with helmfile and the helm-secrets plugin.

**Pros**:
- A faster, smaller gateway with no sidecar.
- No in cluster controller; helmfile is simple to reason about.

**Cons**:
- Two toolchains, and the token library written twice (a security sensitive duplication).
- No drift detection or visible desired state on the cluster.

### Option 3: k3d + Tilt local cluster from day one

Same code stack, but the inner loop is a local k3s cluster with the real charts and live update.

**Pros**:
- Charts, NetworkPolicies and probes are exercised from the first day.

**Cons**:
- Heavy on a laptop and slow to start, before any chart has meaningful content.
- Duplicates work the real cluster phase does anyway.

### Option 4: Plain HTTP reverse proxy gateway with separate REST write endpoints

Tool servers expose MCP for reads and REST for writes; the gateway routes by path.

**Pros**:
- A simpler gateway with no MCP awareness.

**Cons**:
- The gateway cannot cleanly see tool names inside MCP bodies, so OPA checks act on routes, not tools.
- Two protocols to secure, log and test.

## Rationale

**Language and repo.** Python everywhere follows directly from the fixed dependencies. The only credible second language (Go for the gateway) would duplicate the token library, the one piece where a mismatch is a security bug. A single uv workspace keeps the token library, contracts and every consumer in one atomic change, which matters most during the Foundation phase when those contracts are still moving. mypy strict was chosen over pyright for its pydantic plugin and familiarity to reviewers. The cost is slower checks and some ignores around LangGraph and Temporal typings.

**Service shape.** Making the gateway MCP aware is what turns "one door" into real enforcement. OPA sees the exact tool name and scope, and the PRD's `write_from_human` rule applies to writes without a second mechanism. That only works if writes are MCP tools too, so both decisions go together. The Redis Stream between adapter and agent costs almost nothing (Redis is already required for the proxy) and removes the "restart loses the question" failure that a background HTTP call would have. One `jml-worker` keeps Temporal simple. Team ownership is expressed in the tool servers the activities call, which is where the PRD's isolation actually lives.

**Local loop.** The cluster is out of reach, so the loop must not need one. Compose for the platform dependencies plus in memory fakes for the team systems lets features 3 to 7 reach `done` locally and lets Slice 1 code start early, exactly as the scope's cluster note intends. k3d and Tilt were rejected for now because the charts carry little until Slice 1 deploys. They can be added later without changing anything else.

**Delivery.** One shared chart is the strongest guard against isolation drift, since every service gets the same default deny and probes from the same template. Argo CD with KSOPS was chosen over helmfile because the portfolio benefits from visible, diffable desired state and because KSOPS keeps decryption inside the cluster, as PRD 14.3 requires. If the investigation finds Argo CD missing and capacity tight, helmfile with helm-secrets is the fallback.

**Recommendations I settled myself** (pick, then runner up):
- httpx for HTTP clients (runner up: aiohttp, which has a weaker typing story).
- pydantic-settings for config (runner up: plain `os.environ`, with no validation).
- Port 8080 and `/healthz` plus `/readyz` everywhere (runner up: per service ports, which add noise to values files).
- Image tags by git SHA (runner up: semver per service, needless for a monorepo that deploys together).
- kubeconform for chart validation (runner up: helm unittest, worth adding once templates have logic).
- One shared Redis with key prefixes (runner up: a Redis per use, more pods for no isolation gain since all users sit in `assistant`).

**Cross check (2026-10-07, a different model, read only).** It found 11 gaps that the first draft left for the builder to guess. You applied all the recommended fixes: Redis moves to `assistant` with per service ACL users and app level encryption; enqueue before ack; the gateway is limited to `tools/list` and `tools/call`; OPA policy ships as a ConfigMap; there's a NetworkPolicy values schema; namespace is a required chart value; fixed token key env names; the audit line and request ID contracts; the root context image build; an MCP spike before pinning; and the coverage gate applies only to packages with code. Moving Redis out of `platform` departs from PRD 14.2. It's worth it because no service in `platform` uses Redis, and keeping it in `assistant` removes a cross namespace path.

## References

**Project sources**:
- `PRD.md` sections 6 (architecture), 10 (tools), 12 (NFRs), 14.1 to 14.4 (stack, install, secrets, isolation)
- `docs/scope/scope.md` feature 1 and the cluster note
- Your global rules: 80% coverage, conventional commits

**Practices & standards**:
- Single choke point for authorization and audit (policy enforcement point)
- GitOps (desired state in git, reconciled by a controller)
- Hermetic tests with in memory fakes behind a client protocol
- Default deny networking

**Links** (verified in the landscape check on 2026-10-07):
- uv releases: https://github.com/astral-sh/uv/releases
- ruff releases: https://github.com/astral-sh/ruff/releases
- MCP Python SDK on PyPI: https://pypi.org/project/mcp/2.0.1
- MCP Python SDK v2 docs: https://py.sdk.modelcontextprotocol.io/v2/
- FastAPI on PyPI: https://pypi.org/project/fastapi
- Temporal LangGraph integration docs: https://docs.temporal.io/develop/python/integrations/langgraph
- KSOPS image: https://hub.docker.com/r/viaductoss/ksops

## Evidence: landscape check (2026-10-07)

Verified: uv 0.12.23 (workspaces stable), ruff 0.16.10, `mcp` 2.0.1 (Streamable HTTP built in), FastAPI 0.142.2 (Python 3.10 to 3.14), langgraph 1.1.0, Tilt 0.37.x maintained, sops-secrets-operator 0.21.2 active, KSOPS available.
Unverified: the production status of Astral's `ty`, Python 3.14 support in temporalio and Presidio, current Argo CD and k3d versions, `langchain-mcp-adapters` version, and the exact current `temporalio` release (sources disagreed between 1.24 and 1.27). Full notes: `docs/.agent-cache/research/stack-landscape.md`.
