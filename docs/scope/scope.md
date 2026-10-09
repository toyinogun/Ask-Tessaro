# Scope: Ask Tessaro

An AI employee service desk and lifecycle orchestrator for a fictional 2,400 person company. Employees ask questions in Zulip and a read only master agent answers from each team's system; when People records a joiner, mover or leaver in Frappe HR, a durable workflow sets up or removes access across six systems with approvals in chat. Built as a portfolio reference build on made up data, self hosted on an existing three node k3s cluster. Source documents: `PRD.md`, `Ask Tessaro 2027 project plan.pdf`, `Ask Tessaro proof of concept proposal.pdf`.

**Build approach:** Tracer Bullet (prove the whole chain from Zulip to a team system works on one real question, then thicken it one strand at a time).
**Workflow:** Beta (after `/develop`: `/check verify`, then `/test`). The project default level of rigor. `/architect` is the recommended first stop for a feature with a real decision, but skippable when you already know the build. Security core features carry `· GA` (adds a fresh model `/check review` and `/document`).

**Sharing:** after each milestone (every phase or slice below is one), share what you built, mainly on LinkedIn: one post plus one short video. See [Milestone posts](#milestone-posts).

**Build target:** the full demo script in PRD section 14.6, plus the mover workflow as the last slice.

**Cluster note:** you are away from the k3s cluster for now. The first phase, *Foundation (no cluster)*, is everything you can build and test on your laptop. *Foundation (cluster)* starts with the read only environment investigation once you are home, and nothing gets installed before that report exists. Features in Slice 1 and later can have their code started early against test doubles, but each one is only done once it runs against the real system on the cluster.

_These are recommendations to keep your build orderly, not requirements. Skip anything that does not fit: if you already know how to build a feature, use `/develop` and skip `/architect`. You decide when a feature is `done`._

## At a glance

| # | Feature | Phase | Status |
|---|---------|-------|--------|
| 1 | Stack & architecture | Foundation (no cluster) | done |
| 2 | Coding standards & tooling | Foundation (no cluster) | done |
| 3 | Fictional company dataset | Foundation (no cluster) | done |
| 4 | Identity token & tool contracts | Foundation (no cluster) | done |
| 5 | Record access model | Foundation (no cluster) | done |
| 6 | Tool policy | Foundation (no cluster) | in-progress |
| 7 | Privacy proxy | Foundation (no cluster) | planned |
| 8 | Cluster investigation & baseline | Foundation (cluster) | planned |
| 9 | Identity & chat systems | Foundation (cluster) | planned |
| 10 | Platform services | Foundation (cluster) | planned |
| 11 | Team systems | Foundation (cluster) | planned |
| 12 | Zulip adapter | Slice 1 | planned |
| 13 | Tool gateway | Slice 1 | planned |
| 14 | People tools: my leave | Slice 1 | planned |
| 15 | Master agent | Slice 1 | planned |
| 16 | Assistant deploy & isolation | Slice 1 | planned |
| 17 | IT tools | Slice 2 | planned |
| 18 | Finance tools | Slice 2 | planned |
| 19 | Workplace tools | Slice 2 | planned |
| 20 | Handbook search | Slice 2 | planned |
| 21 | Hand off to a team | Slice 2 | planned |
| 22 | Evaluation suites | Slice 2 | planned |
| 23 | JML intake | Slice 3 | planned |
| 24 | Workflow write endpoints | Slice 3 | planned |
| 25 | Approvals in Zulip | Slice 3 | planned |
| 26 | Joiner workflow | Slice 3 | planned |
| 27 | Workflow status in the assistant | Slice 3 | planned |
| 28 | Team leave for managers | Slice 4 | planned |
| 29 | Stand ins | Slice 4 | planned |
| 30 | Leaver workflow | Slice 5 | planned |
| 31 | Mover workflow | Slice 6 | planned |
| 32 | Runnable demo script | Showcase | planned |
| 33 | Evaluation report | Showcase | planned |
| 34 | Case study write up | Showcase | planned |
| 35 | Recorded walkthrough | Showcase | planned |

## Foundation (no cluster)

### 1. Stack & architecture · done
Decide languages, repo layout, local dev loop, how our own services are packaged and charted, and how secrets are kept, then scaffold a runnable repo. The PRD fixes the off the shelf systems; this decides everything around our own code. No cluster needed.
**Done when:** the stack is recorded in a spec, and the empty repo builds, runs its (empty) tests locally, and renders its charts without a cluster.
spec [0001](../specs/0001-stack-architecture/index.md) · code in `/` (workspace root: `libs/`, `services/`, `charts/`, `deploy/`)
- [x] Decide the stack (spec): `/architect stack & architecture`
- [x] Scaffold from the decision: `/develop stack & architecture`
- [x] Verify it: `/check verify stack & architecture`
- [x] Test it: `/test stack & architecture`

### 2. Coding standards & tooling · done
Capture conventions and tooling from the real scaffolded repo, then install lint, format, type checks, pre commit hooks and CI. No cluster needed.
**Done when:** root `AGENTS.md` reflects the real stack, and lint, format, type checks and CI run clean.
- [x] Capture conventions + tooling choices: `/audit`
- [x] Install pre-commit hooks and CI: `/develop tooling` (code in `.pre-commit-config.yaml`, `.github/workflows/ci.yml`)
- [x] First CI run on GitHub is green (needs a push)

### 3. Fictional company dataset · done
The single source of truth for the made up company: about 30 employees in five teams, managers, HR advisors, an expiring stand in, leave, claims, tickets, devices, bookings, about 20 handbook pages, the pending joiners, mover and leaver, and the three traps (injected ticket text, sick colleague, Dutch name). Every system and test loads from it. No cluster needed.
**Done when:** one dataset produces loadable records for every system plus OpenFGA tuples and the directory list, and covers every seed and trap in PRD 14.5.
spec [0002](../specs/0002-fictional-company-dataset/index.md) · code in `libs/tessaro-dataset/`, `dataset/`, `bundles/`
- [x] Design it (spec): `/architect fictional company dataset`
- [x] Build it: `/develop fictional company dataset`
  - [x] Date grammar and a thin thread from YAML to an exported file (AC-2, AC-3, AC-7, AC-8, AC-13)
  - [x] Full models, collecting validation, derivation and every exporter, including `demo_actions` and `standin` (AC-6 to AC-11, AC-14 to AC-16)
  - [x] Author the company, demo cast, traps, handbook pages and access bundles (AC-1, AC-4, AC-5, AC-11, AC-15)
  - [x] CLI, deterministic output, `just dataset`, and the CI load and anchor sweep tests (AC-12, AC-13)
- [x] Verify it: `/check verify fictional company dataset`
- [x] Test it: `/test fictional company dataset`

### 4. Identity token & tool contracts · done · GA
The signed token every call carries (human vs workflow worker, roles, request ID, 5 minute expiry) and the typed, versioned contract format every tool server publishes. Every service builds against these. No cluster needed.
**Done when:** token issue and verify work in a shared library with tests for expiry, tampering and kind; the contract format is defined and `get_my_leave` is written in it.
spec [0003](../specs/0003-identity-token-tool-contracts/index.md) · code in `libs/tessaro-auth/`, `libs/tessaro-contracts/`, `policy/`
- [x] Design it (spec): `/architect identity token & tool contracts`
- [x] Build it: `/develop identity token & tool contracts`
  - [x] Thin thread: mint a human token, verify it, project `get_my_leave` to an MCP tool (AC-1, AC-6, AC-15, AC-17)
  - [x] Full token: roles, mint refusals, worker tokens, signer kinds and every verify rejection in order (AC-2 to AC-8)
  - [x] Keys and edges: settings with fail fast key set parsing, `principal_from_headers`, `just keys` and per service dev keys (AC-9 to AC-12)
  - [x] Contract format: validators, registry, results and errors, snapshots, OPA tool data export and the version rule (AC-13, AC-14, AC-16, AC-18, AC-19)
- [x] Verify it: `/check verify identity token & tool contracts`
- [x] Test it: `/test identity token & tool contracts`
- [x] Review it (fresh model): `/check review identity token & tool contracts`
- [x] Document it: `/document identity token & tool contracts`

### 5. Record access model · done · GA
The OpenFGA model from PRD 8.3 (owner, team, manager, time boxed stand in, HR advisor, lifecycle case) with CLI test files. Decides whose records anyone may see or approve. No cluster needed.
**Done when:** the model passes CLI tests for self access, manager leave dates, expired stand ins, cross team attempts and HR advisor scope, using tuples generated from the dataset.
spec [0004](../specs/0004-record-access-model/index.md) · code in `authz/`, `libs/tessaro-dataset/`
- [x] Design it (spec): `/architect record access model`
- [x] Build it: `/develop record access model`
  - [x] Thin thread: model file, org IT approver export, registry check against the model, `just authz-test` with self access tests (AC-1, AC-2, AC-9, AC-10)
  - [x] Team access: managers, HR advisors and cross team checks (AC-3, AC-5, AC-6)
  - [x] Stand in window: start, inside, end and the second stand in (AC-4, AC-5)
  - [x] Lifecycle cases: fixture cases, separation of duties and the mover (AC-7, AC-8)
  - [x] Local load: `just authz-load` and the `.env.example` lines (AC-11)
- [x] Verify it: `/check verify record access model`
- [x] Test it: `/test record access model`
- [x] Review it (fresh model): `/check review record access model`
- [x] Document it: `/document record access model`

### 6. Tool policy · in-progress · GA
The OPA policy and data that decide which roles may call which tools, with write scopes usable only by workflow worker tokens. No cluster needed.
**Done when:** policy tests cover every role and scope in PRD 8.2, and every human token is denied every write scope.
spec [0005](../specs/0005-tool-policy/index.md) · code in `policy/`, `libs/tessaro-auth/`, `libs/tessaro-contracts/`
- [x] Design it (spec): `/architect tool policy`
- [ ] Build it: `/develop tool policy`
  - [ ] Thin thread: typed role scopes, flat `policy/` with generated data, the allow path and the Compose OPA check (AC-1, AC-2, AC-3, AC-11)
  - [ ] Deny paths: deny reasons, kind and role mismatch, invalid input and defaults (AC-4, AC-5, AC-6, AC-7)
  - [ ] Listing: `allowed_tools` on the shared helper (AC-8)
  - [ ] Guards: full role by scope grid, fmt, strict check and 100% coverage, enum and drift pytests (AC-9, AC-10)
- [ ] Verify it: `/check verify tool policy`
- [ ] Test it: `/test tool policy`
- [ ] Review it (fresh model): `/check review tool policy`
- [ ] Document it: `/document tool policy`

### 7. Privacy proxy · needs a decision · GA
OpenAI compatible proxy in front of the model: masks names, emails, phones, IBANs, addresses and employee IDs (plus a directory recognizer), keeps consistent encrypted placeholders per conversation, restores them in answers and tool arguments, and fails closed. The core runs locally. No cluster needed.
**Done when:** a leak scan over test conversations finds zero dataset names or emails in outgoing payloads, the Dutch name trap is caught, tool call arguments come back restored, and the proxy refuses to call the model when the analyzer is down.
- [ ] Design it (spec): `/architect privacy proxy`

## Foundation (cluster)

### 8. Cluster investigation & baseline · needs a decision
When you are home: inspect the cluster read only, write `docs/environment-report.md` (PRD 14.2 step 0), decide ingress, storage, hostnames, certificates and capacity, then lay down namespaces, default deny NetworkPolicies and any gaps found. The investigation inventory lives in the spec's rationale.
**Done when:** the environment report exists with its decisions, NetworkPolicy enforcement is proven with a test deny between two pods, and every planned namespace exists with default deny.
- [ ] Design it (spec): `/architect cluster investigation & baseline`

### 9. Identity & chat systems · needs a decision
Install Authentik and Zulip, wire Zulip sign in through Authentik, create the groups from PRD 8.1, and load the dataset's people.
**Done when:** a dataset employee signs in to Zulip through Authentik and their groups appear in the token; the bot user exists.
- [ ] Design it (spec): `/architect identity & chat systems`

### 10. Platform services · needs a decision
Install OpenFGA, Temporal (server and UI), Presidio, Redis, Langfuse, Grafana and Loki in their namespaces, with Authentik sign in for the UIs.
**Done when:** the access model and dataset tuples are loaded in OpenFGA, Temporal runs a hello workflow that survives a pod restart, and Langfuse and Grafana open through Authentik.
- [ ] Design it (spec): `/architect platform services`

### 11. Team systems · needs a decision
Install Zammad, Snipe-IT, Frappe HR with ERPNext, Seatsurfing and BookStack, connect each to Authentik, and load the dataset. Seatsurfing and Snipe-IT can wait until Slice 2 if the investigation shows capacity is short.
**Done when:** every system signs in through Authentik and shows the dataset's records; separate People and Finance API users exist in Frappe with limited permissions.
- [ ] Design it (spec): `/architect team systems`

## Slice 1: Leave balance end to end

The thinnest real thread: an employee asks "how many vacation days do I have left?" in Zulip and gets a private, correct, masked answer through every layer. Covers demo steps 1, 2 and 8.

### 12. Zulip adapter · needs a decision · GA
Receives the bot's outgoing webhook, verifies it, deduplicates, acknowledges at once, looks the sender up in Authentik, signs their token, replies privately, and keeps a short per person context. Approval code matching joins in Slice 3.
**Done when:** a direct message gets exactly one private reply; an inactive user and a bad webhook token are rejected; a channel mention gets a "sent privately" reply; emoji reactions are recorded as ratings.
- [ ] Design it (spec): `/architect zulip adapter`

### 13. Tool gateway · needs a decision · GA
The one door to every tool server: validates tokens, asks OPA, forwards the token, rate limits, and writes every call to Loki.
**Done when:** an allowed call is forwarded and logged with caller, roles, tool, record IDs, result and latency; a disallowed call is denied and logged; a revoked scope takes effect on the next call.
- [ ] Design it (spec): `/architect tool gateway`

### 14. People tools: my leave · needs a decision
The first team tool server, and the template the others follow: `get_my_leave` from Frappe HR, identity from the token only, an OpenFGA check per record, never any absence reason.
**Done when:** an employee gets their own balance and booked leave; no input can name another employee; the sick colleague's reason never appears in any output; its test set runs before deploy.
- [ ] Design it (spec): `/architect people tools: my leave`

### 15. Master agent · needs a decision · GA
The agent that understands the question, calls read tools through the gateway and model calls through the proxy, and writes the answer. It has no write tools.
**Done when:** "how many vacation days do I have left?" is answered from the tool result only; asking for a colleague's balance is refused by OpenFGA; the Langfuse trace shows only placeholders.
- [ ] Design it (spec): `/architect master agent`

### 16. Assistant deploy & isolation
Ship the adapter, agent, proxy, gateway and People tools to the cluster with their charts, secrets and NetworkPolicies, so the thread runs for real.
**Done when:** demo steps 1, 2 and 8 work on the cluster: the leave question is answered, the trace is masked, and a shell in the agent pod cannot reach Frappe or Zammad; the proxy is the only pod with internet access.
- [ ] Build it: `/develop assistant deploy & isolation`

## Slice 2: Every Phase 1 question

Thicken the thread to all read only use cases UC1 to UC7, then prove it with the PRD's safety and quality suites.

### 17. IT tools
`get_my_tickets` and `get_my_devices` from Zammad and Snipe-IT, following the People tools template.
**Done when:** "what's happening with my laptop repair?" returns ticket status and latest update; the ticket with injected instructions is treated as data.
- [ ] Build it: `/develop IT tools`

### 18. Finance tools
`get_my_expense_claims` from ERPNext with its own limited Frappe API user.
**Done when:** "when will my Berlin expense claim be paid?" returns status, approver and expected payment date.
- [ ] Build it: `/develop finance tools`

### 19. Workplace tools
`get_my_bookings` from Seatsurfing.
**Done when:** an employee sees their upcoming desk and room bookings and no one else's.
- [ ] Build it: `/develop workplace tools`

### 20. Handbook search · needs a decision
`search_handbook` over BookStack so policy answers come with the page link behind them.
**Done when:** "can I work from Spain for three weeks?" and "I'm sick, what do I do?" are answered from handbook pages with links, and the sick answer never asks about the illness.
- [ ] Design it (spec): `/architect handbook search`

### 21. Hand off to a team · needs a decision
`handoff_to_team` raises a request in the right team's Zammad queue with a summary, when the agent is unsure or a person is needed.
**Done when:** the Spain question offers a hand off to People and the ticket lands in People's queue only, with context attached.
- [ ] Design it (spec): `/architect hand off to a team`

### 22. Evaluation suites · needs a decision
The PRD 13 suites as automated gates: answer quality datasets per team, the safety suite, the masking leak scan, and masking on vs off comparison.
**Done when:** the safety suite and leak scan pass at 100% and zero leaks, quality datasets run with scores per team, and the suites block a deploy when they fail.
- [ ] Design it (spec): `/architect evaluation suites`

## Slice 3: Joiner

A new hire recorded in Frappe HR is onboarded by a durable workflow, with approvals in Zulip and clean undo on failure. Covers demo steps 3, 4 and 6.

### 23. JML intake · needs a decision · GA
Receives Frappe HR webhooks, verifies signatures, classifies joiner, mover or leaver events, and starts or signals workflows with deterministic IDs.
**Done when:** a new hire starts exactly one `joiner-<id>` workflow even when the event arrives twice; an unsigned webhook is rejected; a changed start date signals the running workflow.
- [ ] Design it (spec): `/architect JML intake`

### 24. Workflow write endpoints · needs a decision · GA
The identity tool server (Authentik, Zulip admin, OpenFGA writes) plus write endpoints on IT and Workplace tools, each idempotent, each with an undo where undo is possible, callable only by workflow worker tokens.
**Done when:** every joiner step's write and undo can be called twice with the same key safely; the master agent's token is denied every write.
- [ ] Design it (spec): `/architect workflow write endpoints`

### 25. Approvals in Zulip · needs a decision · GA
Approval requests with one time codes, matched in code before any model call, checked with OpenFGA `can_approve`, and sent to the workflow as a signal carrying the approver's identity.
**Done when:** `APPROVE 7KQ2` from the right manager approves once; a reused, expired or wrong person's code is refused; approval messages never reach the model; timeouts escalate.
- [ ] Design it (spec): `/architect approvals in zulip`

### 26. Joiner workflow · needs a decision · GA
The nine step joiner saga from PRD 9.2 with access bundles, manager and IT approvals, a timer until the start date and a day one readiness check.
**Done when:** a new hire ends with account, groups, Zulip, laptop, desk and welcome ticket; scaling Seatsurfing to zero mid run triggers retries, then undo in reverse order, then a clean rerun; a rejection undoes steps 1 and 2 and notifies People.
- [ ] Design it (spec): `/architect joiner workflow`

### 27. Workflow status in the assistant · needs a decision
`get_workflow_status` so managers, People advisors and IT can ask about a case they may see.
**Done when:** "is everything ready for Lisa on Monday?" is answered from live workflow state, and a People advisor sees only their teams' cases.
- [ ] Design it (spec): `/architect workflow status in the assistant`

## Slice 4: Manager views & stand ins

Covers UC8, UC9 and demo step 5.

### 28. Team leave for managers
`get_team_leave` returns team leave dates, never reasons, using the access model's manager and stand in relations.
**Done when:** a manager sees who in their team is off next week, without reasons; an employee cannot call it.
- [ ] Build it: `/develop team leave for managers`

### 29. Stand ins · needs a decision
A manager names a stand in between two dates; the stand in can approve for that team only inside the window.
**Done when:** the stand in approves the second joiner inside the window, and the same approval is refused once the window ends.
- [ ] Design it (spec): `/architect stand ins`

## Slice 5: Leaver

Covers UC15 and demo step 7.

### 30. Leaver workflow · needs a decision · GA
At 17:30 on the last working day, remove every access in every system, never undo, retry with backoff, and alert IT after three failed attempts.
**Done when:** every account is deactivated, sessions ended, relationships and stand in arrangements removed, bookings cancelled, laptop return ticket raised and Finance told, with the audit trail visible in Grafana; a failing system is retried until it succeeds.
- [ ] Design it (spec): `/architect leaver workflow`

## Slice 6: Mover

Covers UC14. Reuses the joiner and leaver steps.

### 31. Mover workflow · needs a decision
On the move date, grant the new team's access first, confirm it, then remove the old access, after the new manager approves the bundle.
**Done when:** the dataset's mover has new groups and channels before old ones are removed, and a failure keeps old access in place and retries.
- [ ] Design it (spec): `/architect mover workflow`

## Showcase

### 32. Runnable demo script
A repeatable run of the eight demo steps from PRD 14.6, with a reset to the starting dataset.
**Done when:** one command resets the data and each demo step can be run and shown in order.
- [ ] Build it: `/develop runnable demo script`

### 33. Evaluation report
The evaluation suites' latest results, published in a readable form.
**Done when:** a report shows each suite, its gate and its result, generated from a real run.
- [ ] Build it: `/develop evaluation report`

### 34. Case study write up · Prototype
The public story: problem, the four principles, architecture diagrams, what the demo proves, and what would change for real data.
**Done when:** a reader understands the system and its safety design without running it, and every claim links to a demo step or test result.
- [ ] Build it: `/develop case study write up`

### 35. Recorded walkthrough · Prototype
A video of the demo for people who will not run it.
**Done when:** a recording covers all eight demo steps with narration or captions.
- [ ] Build it: `/develop recorded walkthrough`

## Milestone posts

When the last feature in a milestone turns `done`, share it before you start the next one: one LinkedIn post and one short video (60 to 90 seconds, square or vertical, with captions so it works on mute). Drafts and renders live in `.bip/` at the repo root, which is gitignored, so they never land in the public repo.

How to make them (recommendations, swap in whatever you like):
- **Post:** `/build-in-public generate posts` for LinkedIn. Feed it the milestone's done lines, the specs it closed, and one real number or screenshot from `/check verify`.
- **Video:** `/faceless-explainer` from the final post text (narration, diagrams, captions). When the milestone shipped as one pull request, `/pr-to-video` on that PR is the alternative.
- **Repo link:** point readers to https://github.com/toyinogun/Ask-Tessaro.

- [ ] **Foundation (no cluster)** · ready when features 1 to 7 are done · angle: designing the safety layer before any infrastructure exists (signed tokens, record access model, tool policy, a privacy proxy that fails closed), all tested on a laptop.
- [ ] **Foundation (cluster)** · ready when features 8 to 11 are done · angle: moving onto a real three node k3s cluster, default deny networking, and every off the shelf system signing in through one identity provider.
- [ ] **Slice 1: Leave balance end to end** · ready when features 12 to 16 are done · angle: the first real answer in Zulip, traced through every layer, with the masked trace and the agent pod that cannot reach the HR system.
- [ ] **Slice 2: Every Phase 1 question** · ready when features 17 to 22 are done · angle: one assistant answering for IT, Finance, Workplace and the handbook, plus the safety suite and leak scan as deploy gates.
- [ ] **Slice 3: Joiner** · ready when features 23 to 27 are done · angle: a durable onboarding workflow with approvals in chat, and what happens when a system fails halfway (retries, then clean undo).
- [ ] **Slice 4: Manager views & stand ins** · ready when features 28 and 29 are done · angle: time boxed delegation, the stand in who can approve on Friday and is refused on Monday.
- [ ] **Slice 5: Leaver** · ready when feature 30 is done · angle: removing every access at 17:30 on the last day, never undone, with the audit trail to prove it.
- [ ] **Slice 6: Mover** · ready when feature 31 is done · angle: granting new access before removing the old, so nobody loses a working day.
- [ ] **Showcase** · ready when features 32 to 35 are done · angle: the full demo, the evaluation results, and what would change before real employee data.

## Deferred
Out of scope for the current build pass, kept so the plan stays honest.
- **EU hosted model**: replace the DeepSeek API before any real data (open question 1) · needs a decision
- **Self service actions**: leave requests, desk bookings, expense claims (2028) · needs a decision · GA
- **Retention settings**: bot message, Temporal history and audit log retention (open question 4) · needs a decision
- **Compliance paperwork**: DPIA, AI Act assessment, works council briefing (not code; owned by Legal and DPO in the case study)

## Legend

**The decision box.** Every feature carries exactly one, the sub task whose label ends with `(spec)`. Its wording varies (`Design it (spec)` normally, `Decide the stack (spec)` on Stack & architecture), so skills locate it by that `(spec)` suffix, never by an exact label. Every other box is an execution box and `/architect` never ticks one.

**Feature lifecycle**: the scope updates as a feature moves; each row is what it shows and who sets it:

| State | Set by | The feature shows |
|---|---|---|
| `planned` · needs a decision | `/scope` | one box: `Design it (spec): /architect <feature>` |
| `in-progress` (designed) | **`/architect` at spec capture** | `Design it` ticked; spec linked; `Build it: /develop <feature>` + **2 to 5 milestones**; the tier's closing boxes (`Verify it` Alpha+, `Test it` Beta+, `Review it` + `Document it` GA); any surfaced follow up enrolled |
| `in-progress` (building) | `/develop` | milestone sub boxes tick one by one; code pointer filled |
| `in-progress` (verified) | `/check verify` | `Build it` + milestones ticked; `Verify it` ticked |
| `done` | **you, when you decide it is** (any skill sets it when you say so); `/sync` reconciles | boxes you ran ticked, skipped ones marked skipped; the tier's last stage (`Prototype` → after `/develop`; `Alpha` → after `/check verify`; `Beta`/`GA` → after `/test`) is the suggested point to call it done; `/sync` captures conventions |

- **Next step** = the first unticked box (always a command or a tracked milestone).
- **Milestone posts** sit outside the features: they never block a feature's `done`, and the Next step rule above ignores them. When a milestone's last feature turns `done`, its post and video are the suggested step before the next feature.
- **needs a decision** = run `/architect` first; otherwise straight to `/develop` (or `/audit` for standards & tooling). The tag drops once the spec is captured.
- **Atomic build tasks live in the spec's `## Build plan`, not here**: the scope carries only the milestone rollup.
- **Status** `planned` → `in-progress` → `done`, plus `existing` (pre workflow) and `dropped` (de scoped, kept for history).
- **Approach tag** beside a heading (e.g. `· Facade`) overrides the project default for that feature; no tag = inherits it.
- **Workflow tier tag** beside a heading (e.g. `· GA`, `· Prototype`) sets that one feature's rigor above or below the project default; no tag inherits the default. It decides the feature's check boxes and each skill's next suggestion.
- **Workflow** (header line) is the project default, what runs after `/develop`: **Prototype** = nothing (trust develop's own build time self check); **Alpha** = `/check verify`; **Beta** = `/check verify` then `/test`; **GA** = adds a fresh model `/check review` then `/document`. A feature built on an unratified decision (an `Assumed` spec) stays flagged, but that never blocks `done`.
- **Pointer line** (`spec <n> · code in <path>`): the spec link added by `/architect`, the code path by `/develop`.
