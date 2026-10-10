# 0008. Rationale: identity and chat systems

The decision record behind [index.md](index.md). `/develop` builds from the index; this file explains why.

## Context

Feature 9 is the first install on the cluster after the baseline (spec 0007). Every later system signs in through Authentik (PRD 8.1), and every question and approval reaches Ask Tessaro through Zulip (PRD 6.1, FR-Z1 to FR-Z7). So this feature fixes three things the rest of the build leans on: how an off the shelf system is installed into the fenced Argo CD project, how its configuration is kept as code, and how the fictional company's people get into it.

The forces are specific to this cluster and this repo. The fence (spec 0007 AC-3) allows only `Namespace` at cluster scope and only listed source repositories, so a chart that renders a ClusterRole cannot sync. Pods have no internet once default deny applies, and only the privacy proxy gets an exception, so anything that phones home must be switched off, not allowed. Memory is tight (about 6.5 GiB of request headroom), with quotas of 2Gi for `identity` and 3Gi for `chat`. Spec 0007 chose CNPG per namespace for Postgres but left Zulip's database open, because Zulip ships its own Postgres image with full text search dictionaries.

The people come from the dataset (spec 0002): `export_authentik` and `export_zulip` already produce users, derived groups, channels and subscriptions, and spec 0003 needs each Authentik user to carry an `employee_id` attribute and Authentik group names that map to roles. Later the joiner, mover and leaver workflows change these same records, so whatever loads them must not fight those workflows, and the demo reset (feature 32) must be able to put them back.

Emails are on the reserved `.example` domain, so nothing can be emailed: no magic links, no recovery mail, no invitations. The hosts are private (LAN and tailnet). The data is fictional, so no compliance scope applies, but the repo is public and is a security portfolio piece, so admin protection and secret handling are judged.

## Options considered

### Option 1: GitOps install, own backing services, blueprints for configuration, laptop seed through typed clients

Argo CD installs the pinned upstream charts as multi source Applications with our values and a kustomize folder of our own manifests: CNPG clusters, network policies, Zulip's Redis, RabbitMQ and memcached from official images. Authentik's fixed configuration lives in blueprints mounted from git. People, memberships and Zulip subscriptions are reconciled by `tessaro-seed identity` from the laptop, through new `AuthentikDirectory` and `ZulipAdmin` client protocols. Zulip's realm, owner and bot come from a one time bootstrap recipe.

**Pros**:
- Everything that can be declarative is declarative and reconciled by Argo CD or Authentik itself.
- People stay out of blueprints, so a blueprint reapply never undoes a leaver's deactivation.
- The clients the seed needs are exactly the ones features 12 and 24 need.
- No Bitnami images and no cluster scoped RBAC, so the fence holds.

**Cons**:
- Three backing services to run and pin ourselves.
- The seed is imperative and lives on the laptop, not in the cluster.
- Two mechanisms (blueprints and the seed) to understand instead of one.

### Option 2: One imperative seed for everything

A Python script creates providers, applications, groups, service accounts and people through the Authentik and Zulip APIs, after Argo CD installs the charts.

**Pros**:
- One mechanism and one language for all configuration.
- Easy to read top to bottom.

**Cons**:
- Configuration drift is never reconciled: a provider changed by hand stays changed.
- The Zulip provider, the TOTP flow and policy bindings become code to maintain instead of declarations Authentik understands.
- A failure halfway through leaves the system half configured until the next run.

### Option 3: Terraform for Authentik and Zulip configuration

The Authentik Terraform provider declares providers, groups, users and bindings; a community Zulip provider or scripts cover Zulip.

**Pros**:
- Mature, declarative, with plans that show the change before it happens.
- One tool could later cover other systems.

**Cons**:
- Brings Terraform and its state into this repo for one system, beside Argo CD (two reconcilers).
- People in Terraform state collide with the workflows that change them: every plan would want to undo a leaver.
- Zulip coverage is weak.

### Option 4: Charts as shipped

Install both charts with their bundled Bitnami subcharts (Postgres for both, Redis, RabbitMQ and memcached for Zulip) and configure everything by hand in the UIs.

**Pros**:
- Fewest files to write.
- Closest to each project's quick start.

**Cons**:
- Bitnami's 2025 catalog change makes the default images a pull risk, and the frozen legacy images get no updates.
- Diverges from spec 0007's CNPG per namespace.
- Nothing is reproducible, so the demo reset and the next reinstall are manual.

## Rationale

Option 1 is the only one that respects both kinds of state in this system. Configuration (providers, flows, groups, roles) changes rarely and should be reconciled from git, which is what blueprints are for and what Argo CD already does for Kubernetes objects. People change constantly and on purpose (joiners, movers, leavers), so they must be written by code that knows the dataset and leaves workflow changes alone except when you ask for a reset. Options 2 and 3 put both kinds in one mechanism and so either never reconcile configuration (2) or fight the workflows (3). Option 4 fails the cluster's own constraints: the fence, the image supply and spec 0007's database choice.

The sub decisions follow the same reasoning, and each was put to you with a runner up:

| Decision | Pick | Why | Runner up |
|---|---|---|---|
| Delivery | Multi source Application per system (chart, values, manifests, and the namespace's sealed secrets folder) | Shows exactly which upstream chart and version runs, in the fence's `sourceRepos`, as spec 0007 planned; the fourth source is what applies the sealed files, which nothing synced before | Wrapper chart with a vendored tarball (offline, but hides the upstream in the fence) |
| Authentik configuration | Blueprints from git | Authentik's native declarative format, reapplied on change, secrets through `!Env` | API seed (no drift reconciliation) |
| People | Laptop CLI `tessaro-seed` through typed clients | No image pipeline needed yet; the clients are reused by features 12 and 24 | In cluster Job (needs our own image and more egress) |
| Seed home | New package `libs/tessaro-seed` | Keeps `tessaro-dataset` free of HTTP; one place for features 10 and 11 to add systems | A subcommand in `tessaro-dataset` |
| Zulip's Redis, RabbitMQ, memcached | Own small manifests, official images | Avoids the Bitnami image risk and RabbitMQ's Kubernetes peer discovery RBAC | Bitnami subcharts with `bitnamilegacy` images |
| Zulip Postgres | CNPG, stock image, missing dictionaries mode | Matches spec 0007, needs no image build; search quality is not part of the demo | CNPG with a custom hunspell image |
| CNPG disruption budget | `enablePDB: false` | Drains stop needing the manual dance from spec 0007; a minute of downtime is fine for a demo | Keep the budget |
| Who gets accounts | All seed employees, joiners excluded | Matches PRD 14.5; the joiner workflow owns new accounts | Demo cast only |
| Passwords | One shared demo password, local only | Demo as anyone; fictional people on private hosts | One generated password per person |
| Zulip accounts | Preloaded, no auto signup | Deactivation holds; account creation has one owner | Created on first sign in |
| Zulip sign in | OIDC only (realm setting); break glass through `manage.py` | One identity path makes the leaver demo honest | OIDC plus email and password |
| Admins | `tessaro-admin` outside the dataset, `akadmin` kept for break glass | Keeps demo personas ordinary and the real person out of the fiction | Your personal account |
| Service accounts | `zulip-adapter` (read) now, `tessaro-seed` for the seed; the identity tool account waits for feature 24 | Creates only what has a user today | Both PRD accounts now |
| Bot | Outgoing webhook bot wired to the adapter's future URL | Done criteria satisfied, feature 12 just consumes it | Generic bot, webhook later |
| Secret handoff | Git ignored `.secrets/assistant/zulip-adapter.env`; feature 12 seals | One Secret sealed once, whole, by the feature that uses it | Seal now with a production signing key |
| Rerun | Reconcile seeded people, never touch others, never delete | Makes the demo reset one command | Create missing only |
| Email visibility | Real emails visible to everyone in the realm (you chose real emails visible to members; the cross check showed only the `everyone` setting puts the real address in `sender_email`, so the setting follows your intent) | `sender_email` matches Authentik directly | Hidden, adapter resolves by user ID |
| App access | `staff` members plus `tessaro-admin` | Refuses strays at Authentik; group removal cuts access | Any active user |
| Zulip rules | Locked to provisioning | Accounts only from seed and workflows; no channel sprawl | Zulip defaults with invitations off |
| Admin MFA | TOTP for superusers only | Cheap, strong signal; personas stay password only | No MFA |
| Proof | `just identity-smoke` with Playwright plus claims | Rerunnable after every upgrade | Claims only, sign in by hand |
| Backups | None, reseed | Everything but message history is rebuilt from git and the dataset | CNPG backups to object storage (needs internet) |
| Seed credential | Dedicated `tessaro-seed` account with a narrow role | The seed never runs as superuser | The bootstrap token |
| OIDC network path | Through the ingress hostname | Issuer and TLS match what the browser sees | Internal Service with a CoreDNS rewrite (outside the fence) |
| Bot gap | Accept failure replies until feature 12 | Nobody uses the bot yet; the reply proves the webhook fires | Create the bot deactivated |
| CI | Pull pinned charts in CI and render | Catches a fence breaking ClusterRole or a Bitnami image before sync | Vendored tarballs |

Calls made while writing, not asked separately: the webhook path `/zulip/webhook` on the adapter's existing chart port 8080 (runner up: `/webhook`, less clear once Frappe webhooks arrive); Zulip's server keeping both login backends with the realm limited to OIDC, so `manage.py` can create the owner before OIDC works (runner up: OIDC only at server level, which makes the first owner harder to create); generating the groups blueprint from the dataset with a staleness check, the same pattern as the contract snapshots (runner up: hand written groups, which drift); the groups blueprint built with demo inputs included, so groups a joiner needs exist before the joiner does.

### Cross check (2026-10-10)

An independent read of the draft on a second model found gaps that the spec now closes: nothing applied the sealed secrets (fixed with a fourth Application source) and the blueprints sat outside their kustomize folder; the build plan seeded people before their groups and seed account existed; the `members` email visibility would still have hidden real addresses from the webhook; the smoke deleted a user the seed role could not delete (now a fixed smoke user, run with the bootstrap token); the seed role could have added itself to the admin group (now per group permissions on dataset groups only); and many build time details (realm creation fallback, owner API key source, `LOADBALANCER_IPS`, Postgres `sslmode`, CNPG `initdb` names, backing service passwords, Authentik group based roles and flow slugs, the OCI repository entry, a non surging Zulip replica) are now named in the index. The Zulip after Authentik sync wave was dropped as unnecessary.

### Chart landscape check (2026-10-10)

A web check run during the design conversation found:

- Authentik chart 2026.8.3 (app 2026.8.3) on the chart's main branch. It has no Redis dependency (Authentik removed Redis in 2025.10, with about 50% more Postgres connections as the cost). Its one bundled subchart is Bitnami Postgres, off with `postgresql.enabled: false`; external Postgres is set through `authentik.postgresql.*`. `serviceAccount.create` (default true) pulls in a remote cluster subchart for managed outposts, which is the likely source of cluster RBAC. Blueprints mount through `blueprints.configMaps` and `blueprints.secrets`, keys ending in `.yaml`.
- Zulip chart 2.3.0 (app `12.3-0`) bundles Bitnami Postgres, RabbitMQ, Redis and memcached, each gated by `<name>.enabled`, and documents external services (`externalPostgresql` and similar). External Postgres needs the database and user created first; full text search works without extensions but stemming dictionaries matter.
- Zulip generic OIDC: `zproject.backends.GenericOpenIdConnectBackend`, `SOCIAL_AUTH_OIDC_ENABLED_IDPS` with `oidc_url`, `display_name`, `client_id`, `secret`, `auto_signup`; redirect URI `/complete/oidc/`; the secret is `social_auth_oidc_secret`.
- Zulip's REST `POST /api/v1/users` needs an administrator with `can_create_users`, granted through `manage.py change_user_role`.
- Not confirmed (each has a fallback in the index): whether either chart renders cluster scoped RBAC with our settings, Authentik's bootstrap and phone home variable names, Authentik's claim preview API and which mapping carries `groups` in this version, the Zulip chart's values key for OIDC, and a `manage.py` command that creates a realm without the web form.

## References

**Project sources**:
- PRD sections 6.1, 7.1, 8.1, 14.2 to 14.5
- Spec 0002 (dataset exporters, derived groups, demo cast), spec 0003 (`employee_id` attribute, `GROUP_TO_ROLE`), spec 0007 (fence, namespaces, quotas, hostnames, network conventions, Sealed Secrets, CNPG per namespace)
- `deploy/AGENTS.md` (Application conventions), `deploy/values/zulip-adapter.yaml` (adapter port and paths)
- Installed skills `gitops-workflow`, `webapp-testing`

**Practices & standards**:
- Reconcile declarative configuration from git; keep frequently changing business records out of declarative reconcilers
- Least privilege service accounts with scoped API tokens
- Second factor for administrative accounts
- Pin images by version and digest

**Links** (checked during the design conversation):
- Authentik chart definition: https://raw.githubusercontent.com/goauthentik/helm/main/charts/authentik/Chart.yaml
- Zulip chart definition: https://raw.githubusercontent.com/zulip/docker-zulip/main/helm/zulip/Chart.yaml
- docker-zulip, using existing services with Helm: https://zulip.readthedocs.io/projects/docker/en/latest/how-to/helm-existing-services.html
- Zulip authentication methods: https://zulip.readthedocs.io/en/latest/production/authentication-methods.html
- Zulip management commands: https://zulip.readthedocs.io/en/latest/production/management-commands.html
- Zulip API, create a user: https://zulip.com/api/create-user
- Anthropic `webapp-testing` skill: https://skills.sh/anthropics/skills/webapp-testing
