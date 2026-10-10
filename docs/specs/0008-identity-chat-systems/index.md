# 0008. Identity and chat systems: Authentik and Zulip through GitOps, configured by blueprints, seeded from the dataset

**Date**: 2026-10-10
**Status**: In Progress

## Summary

Authentik (the identity provider, the one place people sign in) goes into `identity`, and Zulip (the chat system) goes into `chat`. Argo CD installs both from their upstream Helm charts, with our values and a few of our own manifests: each gets its own CNPG Postgres, and Zulip's Redis, RabbitMQ and memcached run from official images, not Bitnami. Authentik's fixed configuration (the Zulip sign in app, groups, admin and service accounts, admin TOTP) is kept in git as blueprints (Authentik's own declarative YAML), and the dataset's people are loaded by a new `tessaro-seed` command you run from your laptop through typed clients that feature 24 will reuse. You're done when a dataset employee signs in to Zulip through Authentik, the token Authentik issues carries their groups, and the bot that feature 12 will listen through exists.

## Requirements

**User stories**:
- As a dataset employee, I want to sign in to Zulip with my Authentik account, so that one identity governs every system (PRD 8.1).
- As the zulip adapter (feature 12), I want a webhook bot, a read only Authentik account and real sender emails, so that I can resolve who asked and sign their token (spec 0003).
- As the engineer, I want the people, groups and channels loaded from the dataset by one rerunnable command, so that the demo can be reset and no system disagrees with another (spec 0002).
- As the security reviewer, I want admin accounts behind a second factor, no internet egress from either system, and nothing secret in git, so that the identity layer is trustworthy.

**Acceptance criteria** (the contract, each criterion is IDed and independently checkable):

- **AC-1**: Argo CD Applications `authentik` (destination `identity`) and `zulip` (destination `chat`) exist in `deploy/argocd/`, in project `tessaro`, both at sync wave `0`, and are `Synced` and `Healthy`. Each is a multi source Application with four sources: the upstream chart at a pinned version (`authentik` chart `2026.8.3` from `https://charts.goauthentik.io`; `zulip` chart `2.3.0`, app `12.3-0`, from the OCI repository `ghcr.io/zulip/helm-charts`; if a newer patch release exists at build time, pin that and record it in the report), a `$values` reference to this repo's `deploy/platform/<system>/values.yaml`, this repo's `deploy/platform/<system>/manifests/` (a kustomize folder with `namespace:` set), and this repo's `deploy/secrets/<namespace>/` (a plain directory source holding that namespace's SealedSecrets). Sync policy: automated with `prune: true` and `selfHeal: true`, plus the `deploy/AGENTS.md` conventions (ServerSideApply, no resources finalizer). The AppProject `tessaro` in `k3sprox-gitops` and its reference copy `deploy/cluster-repo/ask-tessaro.yaml` add exactly these two upstream repositories to `sourceRepos`, and nothing else changes in the fence. Argo CD has a repository entry for `ghcr.io/zulip/helm-charts` with `enableOCI: "true"` (outside the fence, see *Configuration required*).
- **AC-2**: The Authentik values set `postgresql.enabled: false` and `serviceAccount.create: false`. The Zulip values set `postgresql.enabled`, `redis.enabled`, `rabbitmq.enabled` and `memcached.enabled` to `false`. Rendered, neither release contains a ClusterRole, ClusterRoleBinding or any other cluster scoped kind, and no image from a `bitnami` repository.
- **AC-3**: Each system has a CNPG `Cluster` in its manifests folder: `authentik-db` in `identity` (2Gi) and `zulip-db` in `chat` (5Gi), each `instances: 1`, `enablePDB: false`, storage class `longhorn`, image `ghcr.io/cloudnative-pg/postgresql` at major version 17 pinned by tag and digest, `bootstrap.initdb` with database and owner `authentik` and `zulip` respectively, and sync wave `-1` inside its Application. Authentik and Zulip read the password from the CNPG generated `<cluster>-app` Secret (key `password`) through `secretKeyRef` (Authentik: `AUTHENTIK_POSTGRESQL__PASSWORD`; Zulip: `SECRETS_postgres_password`), connect to the `<cluster>-rw` Service, and use `sslmode=require` (Zulip's remote Postgres default `verify-full` fails against CNPG's own certificate authority). No database credential is in git or in a sealed file. Argo CD's health for `postgresql.cnpg.io/Cluster` is checked at build; if Argo CD has no built in health check for it, the wave does not gate and the build adds one to the Argo CD Helm values in `terraform-proxmox-k3s` (as spec 0007 did for Applications).
- **AC-4**: Zulip runs on the stock CNPG image in Zulip's documented mode for Postgres without the hunspell stemming dictionaries. `just identity-smoke` posts a message holding a unique word to a seeded channel with the owner's API key and finds it with a Zulip search narrow using the same key. If docker-zulip has no such mode, the build stops and this criterion is reopened through `/architect` (the fallback: a CNPG image with hunspell) rather than switched silently.
- **AC-5**: `chat` runs Redis, RabbitMQ and memcached as one Deployment plus Service each, from the official `redis`, `rabbitmq` and `memcached` images pinned by version and digest, each with a memory request, no persistence (emptyDir only where the image needs a writable path), running as a non root user where the image supports it. Redis starts with `--requirepass "$REDIS_PASSWORD"` and RabbitMQ with `RABBITMQ_DEFAULT_USER=zulip` and `RABBITMQ_DEFAULT_PASS`, both passwords from the sealed `zulip-secrets` (AC-8); memcached has no password (its NetworkPolicy, which admits only the Zulip server, is the control). Zulip is pointed at all three through the chart's external service settings.
- **AC-6**: `https://auth.tessaro.toyintest.org` serves Authentik and `https://chat.tessaro.toyintest.org` serves Zulip, each through an Ingress of class `nginx` with a certificate from `letsencrypt-prod` that the system trust store accepts. The Zulip Ingress carries `nginx.ingress.kubernetes.io/proxy-read-timeout: "180"` (Zulip's long polling) and `nginx.ingress.kubernetes.io/proxy-body-size: "25m"` (uploads); Zulip runs with `DISABLE_HTTPS=true` and `LOADBALANCER_IPS` set to the ingress controller pods' range, so it trusts the forwarded scheme and builds `https://` redirect URIs. No other Ingress or LoadBalancer Service exists in either namespace.
- **AC-7**: Each namespace's allow policies sit in its manifests folder and follow spec 0007 *Network conventions*; together they allow exactly the paths in *Network paths* below. After both systems run, `just netpol-proof` still passes and its output is appended to `docs/environment-report.md`. Through `kubectl exec` into the real server pods (`curl` in the Zulip server, `python -c` with `urllib` in the Authentik server), `https://example.com` is blocked from both namespaces, and from the Zulip server `https://auth.tessaro.toyintest.org/application/o/zulip/.well-known/openid-configuration` answers 200. The commands and output go in the report.
- **AC-8**: The only secrets in git for this feature are the strict scope SealedSecrets `deploy/secrets/identity/authentik-secrets.sealed.yaml` and `deploy/secrets/chat/zulip-secrets.sealed.yaml` (each with sync wave `-2` so they exist before anything that reads them), written by `just seal` from git ignored env files under `.secrets/` and applied by the Applications' fourth source (AC-1). `just identity-secrets` creates those env files and the local values in *Configuration required*, generating only values that are missing, so a rerun never rotates an existing value; the Zulip OIDC client secret is generated once and written to both files, and values that appear under two names (see *Configuration required*) are copied, never generated twice. `.gitignore` ignores `.secrets/`.
- **AC-9**: Authentik's configuration comes from blueprints in `deploy/platform/authentik/manifests/blueprints/`, turned into the ConfigMap `authentik-blueprints` by the manifests folder's `configMapGenerator` (`disableNameSuffixHash: true`) and mounted through `blueprints.configMaps`. Read with `AUTHENTIK_BOOTSTRAP_TOKEN`, every blueprint instance whose path is one of these files shows status `successful`. The files declare what *Data model sketch* lists as written by a blueprint: every dataset group with `attributes.elevated`, the service account groups and roles with the permissions in *Security model*, the users `tessaro-admin`, `tessaro-seed` and `zulip-adapter`, their tokens, the OAuth2/OpenID provider and application `zulip`, the policy binding that lets only members of `staff` and the user `tessaro-admin` use the `zulip` application, and the admin TOTP flow (AC-15). The groups file `20-groups.yaml` (the dataset groups plus the seed role's per group permissions) is generated by `just blueprints`, and `just check` fails when it differs from a fresh render. The application blueprint also declares `staff` with `state: created` and no attributes, so the policy binding never depends on which file Authentik applies first.
- **AC-10**: Neither system calls out to the internet by configuration: Authentik has its update check, startup analytics and error reporting off and avatars set to initials (no Gravatar); Zulip has the push notification bouncer off, no SMTP server, email notifications off in the realm defaults, Gravatar off (`ENABLE_GRAVATAR=False`) and link previews off (`INLINE_URL_EMBED_PREVIEW=False`). A test over the rendered releases checks these settings are present.
- **AC-11**: `just zulip-bootstrap` (same `TESSARO_KUBE_CONTEXT` guard as the cluster scripts) brings Zulip to this state, in this order, and a second run changes nothing and rotates no key: (1) one realm named `Tessaro` on the root domain `chat.tessaro.toyintest.org` (string ID `""`), made with a realm creation management command if this Zulip has one, else `manage.py shell` calling `do_create_realm`; (2) realm user defaults set email visibility to everyone and turn push and email notifications off, before any user exists; (3) owner `tessaro-admin@tessaro.example`, full name `Tessaro Admin`, created through `manage.py shell` with the owner role (the same email as the Authentik admin, so the owner signs in by OIDC), then granted `can_create_users` with `manage.py change_user_role`; (4) through the owner's API key: realm authentication methods OIDC only, so a password login POST is refused; invitations off; only administrators create channels; (5) an outgoing webhook bot `tessaro-bot` (generic interface) whose payload URL is `http://zulip-adapter.assistant.svc.cluster.local:8080/zulip/webhook`. It reads the owner's API key through `manage.py shell` on every run (so a lost `.env` is recovered, not rotated) and the bot's webhook token from `GET /api/v1/bots` (`services[].token`), falling back to `manage.py shell` on the bot's service record. It writes `ZULIP_ADMIN_EMAIL` and `ZULIP_ADMIN_API_KEY` into `.env`, and `ZULIP_SITE`, `ZULIP_BOT_EMAIL`, `ZULIP_BOT_API_KEY` and `ZULIP_WEBHOOK_TOKEN` into `.secrets/assistant/zulip-adapter.env`, which `just identity-secrets` already seeded with `AUTHENTIK_URL` and `AUTHENTIK_API_TOKEN`; a failed step writes neither file.
- **AC-12**: `just seed-identity` runs `tessaro-seed identity`, which reconciles every seed employee of the dataset (demo input joiners excluded) to the dataset: in Authentik, matched on `attributes.employee_id`, username, name, email, groups (exactly the dataset's), `is_active: true` and the password `TESSARO_DEMO_PASSWORD`; in Zulip, matched on email, full name, active, and subscriptions to exactly the dataset's channels among the dataset's channel set, creating missing channels with their description. Missing users are created (Zulip users with a random unusable password). It never changes or deletes a user whose `employee_id` is missing or not a seed employee's (admins, service accounts, bots, and joiners the workflow created from demo inputs), a Zulip user whose email is not a seed employee's, or a channel outside the dataset. A second run reports zero changes. Before writing anything it exits 1 when a dataset group is missing in Authentik (naming every missing group) or when the Zulip realm does not exist yet (pointing at `just zulip-bootstrap`). It prints counts of created, updated and unchanged records per system.
- **AC-13**: `libs/tessaro-clients` gains two protocols with a real httpx client and an in memory fake each: `AuthentikDirectory` (list users with their attributes and groups, get a user by email, create and update a user, set a password, add and remove a user's group memberships, list groups) and `ZulipAdmin` (list users, create, update, deactivate and reactivate a user, list channels, create a channel, set and remove subscriptions, read the user list as the bot sees it). `tessaro-seed` is a new workspace package `libs/tessaro-seed` that depends on `tessaro-dataset` and `tessaro-clients`; its reconcile logic is unit tested against the fakes only, both packages reach 80% coverage and pass `mypy --strict`.
- **AC-14**: `just identity-smoke` passes against the live systems and its output is appended to `docs/environment-report.md`. It uses `AUTHENTIK_BOOTSTRAP_TOKEN` for every Authentik read and write it makes. (a) Headless Playwright (Chromium) opens `https://chat.tessaro.toyintest.org`, takes the "Log in with Tessaro" button (OIDC `display_name` `Tessaro`), signs in as the demo persona with `TESSARO_DEMO_PASSWORD`, and in that browser session `GET /json/users/me` returns the persona's dataset email. (b) The claims Authentik issues to the `zulip` provider for the demo persona carry `email` equal to the persona's dataset email and `groups` equal, as a set, to the persona's dataset groups, read through Authentik's claim preview for that provider; if this Authentik version has none, through the smoke only provider and application `tessaro-smoke` (declared in a blueprint with the `zulip` provider's scopes and mappings, a redirect URI on `localhost`, bound to `staff`). (c) The fixed user `tessaro-smoke-user` (created if missing, in `staff`, no Zulip account) signs in: Authentik passes it to Zulip, and Zulip gives it no session (`/json/users/me` returns 401); after removing it from `staff`, Authentik stops it on its access denied stage (the final page is on `auth.`) and Zulip again gives no session. In a `finally`, the smoke user is set inactive and removed from `staff`; it is never deleted. (d) A password login POST to Zulip is refused. (e) AC-4's search check and AC-16's token checks. `just smoke-deps` installs Playwright's Chromium (`uv run playwright install chromium`); it is not part of `just init`.
- **AC-15**: Signing in to Authentik as `tessaro-admin` or `akadmin` requires TOTP, forcing enrolment on first sign in; signing in as a dataset employee never asks for a second factor. Checked by hand once and recorded in the report (the smoke covers the employee side through AC-14 (a)).
- **AC-16**: With the `zulip-adapter` token, Authentik's API returns users with `attributes.employee_id` and their group names, and refuses (403) creating or changing a user or group. With the bot's API key, Zulip's user list shows each seeded user's real `@tessaro.example` address in the `email` field (not a `user<id>@` placeholder), which is the value Zulip puts in an outgoing webhook's `sender_email`.
- **AC-17**: Memory requests in `identity` and `chat` stay inside their quotas (2Gi and 3Gi) with the sizes in *Capacity*. The Zulip server runs one replica that never surges (a StatefulSet, or a Deployment with strategy `Recreate`), because a second pod would break the `chat` quota and its RWO volume; it carries `tessaro.io/heavy: "true"` and the preferred anti affinity from spec 0007. The report lists both chart and app versions, every PVC with its storage class, size and node, and the namespaces' summed memory requests.
- **AC-18**: `just charts` (part of `just check`, so CI runs it) renders each platform Application: `helm template` of the pinned upstream chart with its values file plus `kustomize build` of its manifests folder, validated by kubeconform against the vendored schemas (with CNPG's `postgresql.cnpg.io` schemas added to `charts/schemas/`), and tests assert: no cluster scoped kind at all, no `bitnami` image, every image pinned by tag and digest, every object in the Application's destination namespace, no Secret with `data` or `stringData` from our files, and the chart version in each Application equals the one the check rendered.

## Decision

**Chosen option**: Option 1: GitOps install of the upstream charts with our own backing services, Authentik configuration as blueprints, and a dataset seed through typed clients run from the laptop.

Argo CD installs pinned upstream Authentik and Zulip charts as multi source Applications with CNPG Postgres and own manifests for Zulip's Redis, RabbitMQ and memcached; blueprints in git hold Authentik's fixed configuration; `tessaro-seed identity` reconciles the dataset's people into both systems; `just zulip-bootstrap` creates the realm, owner and bot once.

**Implementation skills**: `gitops-workflow` (`wshobson/agents`, `.claude/skills/gitops-workflow/`) · `webapp-testing` (`anthropics/skills`, `.claude/skills/webapp-testing/`) · `async-python-patterns` (`wshobson/agents`, `.claude/skills/async-python-patterns/`)

## Rationale

Reasoning, options and the chart landscape check: see [rationale.md](rationale.md).

## Feature design

**Data model sketch** (target state; no database schema of our own, these are records in Authentik and Zulip):

| Entity | Key (unique) | Fields | Relationships | Written by |
|---|---|---|---|---|
| Authentik user (seeded person) | `attributes.employee_id` (`TES-NNNNN`) | `username` (email local part, required), `name`, `email` (`@tessaro.example`), `is_active`, password (`TESSARO_DEMO_PASSWORD`) | N:M group | seed (reconcile) |
| Authentik group (dataset) | `name` | `attributes.elevated` (bool, required) | N:M user | blueprint `20-groups.yaml` (generated, with demo inputs included so every group a joiner needs exists); members set by the seed |
| Authentik group `authentik Admins` | `name` | `is_superuser: true` (Authentik's default admin group) | members `akadmin`, `tessaro-admin` | Authentik default; blueprint adds `tessaro-admin` |
| Authentik groups `svc-tessaro-seed`, `svc-zulip-adapter` | `name` | none | 1:1 role (roles attach to groups); one member each | blueprint |
| Authentik roles `tessaro-seed`, `zulip-adapter` | `name` | permissions as in *Security model* | 1:1 group | blueprint (`20-groups.yaml` for the seed's per group permissions) |
| User `tessaro-admin` | `username` | email `tessaro-admin@tessaro.example`, name `Tessaro Admin`, password `TESSARO_ADMIN_PASSWORD` (blueprint; if this version's blueprints cannot set a password, `just identity-secrets` prints the step and the bootstrap sets it through `POST /api/v3/core/users/{id}/set_password/` with the bootstrap token), TOTP device (you enrol it) | member of `authentik Admins`; not in `staff` | blueprint |
| Service accounts `tessaro-seed`, `zulip-adapter` | `username` | type service account; API token (intent API, no expiry), keys `TESSARO_SEED_TOKEN` and `ZULIP_ADAPTER_AUTHENTIK_TOKEN` | member of `svc-tessaro-seed`, `svc-zulip-adapter` | blueprint |
| OAuth2 provider and application `zulip` | slug `zulip` | client type confidential, `client_id: zulip`, `client_secret` (`ZULIP_OIDC_CLIENT_SECRET`), redirect URI `https://chat.tessaro.toyintest.org/complete/oidc/` (strict), authorization flow `default-provider-authorization-implicit-consent`, invalidation flow `default-provider-invalidation-flow`, signing key `authentik Self-signed Certificate`, scopes `openid`, `email`, `profile` plus whichever built in mapping carries `groups` in this version (if `groups` needs a scope Zulip does not request, the build adds it to Zulip's OIDC scope setting), subject mode user email | 1:1; policy bindings to group `staff` and user `tessaro-admin` (engine mode any) | blueprint |
| Zulip realm | string ID `""` (root domain) | name `Tessaro`, auth methods OIDC only, invitations off, channel creation admins only, user defaults: email visibility everyone, push and email notifications off | 1:N users, channels | bootstrap |
| Zulip user | email (equals the Authentik email) | full name (the dataset display name, also the mention handle), active | N:M channel through subscriptions | seed (reconcile) |
| Zulip channel | name | description | N:M user | seed (dataset `channels.yaml`) |
| Zulip bot `tessaro-bot` | bot email (Zulip assigns it) | type outgoing webhook, interface generic, payload URL `http://zulip-adapter.assistant.svc.cluster.local:8080/zulip/webhook`, owner `tessaro-admin` | none | bootstrap |

Files per system: `deploy/platform/<system>/values.yaml` (chart values) and `deploy/platform/<system>/manifests/` (`kustomization.yaml` with `namespace:` set; the CNPG `Cluster`; NetworkPolicies and CiliumNetworkPolicies; for Authentik `blueprints/*.yaml` and the `configMapGenerator`; for Zulip the Redis, RabbitMQ and memcached Deployments and Services). Sealed secrets stay where `just seal` writes them, `deploy/secrets/<namespace>/`.

Zulip server settings (through the chart's values or its `SETTING_*` environment mapping, documented in `values.yaml`): `ZULIP_AUTH_BACKENDS` with `GenericOpenIdConnectBackend` and `EmailAuthBackend` (the server keeps both so the owner can exist before OIDC works; the realm allows only OIDC, AC-11); `SOCIAL_AUTH_OIDC_ENABLED_IDPS` with one entry `authentik`: `oidc_url` `https://auth.tessaro.toyintest.org/application/o/zulip/`, `display_name` `Tessaro`, `client_id` `zulip`, `secret` from `social_auth_oidc_secret`, `auto_signup` `False`; `SOCIAL_AUTH_OIDC_FULL_NAME_VALIDATED` `True`; `EXTERNAL_HOST` `chat.tessaro.toyintest.org`; `ROOT_DOMAIN_LANDING_PAGE` `False`; `REMOTE_POSTGRES_SSLMODE` `require`; plus the AC-6 and AC-10 settings.

**State transitions**: a seeded person is either active or inactive in each system. The seed always moves seeded people to active; the leaver workflow (feature 30) moves them to inactive; a later seed run is a demo reset and moves them back. Bootstrap is one way: no realm → realm with defaults → owner → realm rules → bot. The seed requires the realm.

**API surface** (recipes and CLI; no HTTP endpoints of our own):

| Command | Inputs | Outputs | Auth | Key errors |
|---|---|---|---|---|
| `just identity-secrets` | none | `.secrets/identity/authentik.env`, `.secrets/chat/zulip.env`, `.secrets/assistant/zulip-adapter.env`, missing keys in `.env` | local only | refuses if `.secrets/` is not git ignored |
| `just seal identity authentik-secrets .secrets/identity/authentik.env`, same for `chat zulip-secrets .secrets/chat/zulip.env` | env file | sealed files (spec 0007 AC-10) | committed certificate | as spec 0007 |
| `just blueprints` | dataset | `deploy/platform/authentik/manifests/blueprints/20-groups.yaml` | none | exit 1 on `DatasetError` |
| `just blueprints-check` (in `just check`) | dataset, committed file | none | none | exit 1 when stale |
| `just zulip-bootstrap` | `.env` (`TESSARO_KUBE_CONTEXT`), the Zulip server pod | realm, owner, bot; values written per AC-11 | kube context guard; `kubectl exec` for `manage.py`; the owner's API key for REST calls | exit 1 if the context differs, the pod isn't ready, or a step fails (nothing written to the env files) |
| `just seed-identity` → `tessaro-seed identity [--dry-run]` | dataset, `AUTHENTIK_URL`, `AUTHENTIK_SEED_TOKEN`, `ZULIP_SITE`, `ZULIP_ADMIN_EMAIL`, `ZULIP_ADMIN_API_KEY`, `TESSARO_DEMO_PASSWORD` | per system counts (created, updated, unchanged); `--dry-run` prints the plan and writes nothing | the seed token and the owner's key | exit 1 on a missing group, a missing realm, an API error (named record, status) or invalid settings; exit 2 on bad usage |
| `just smoke-deps` | none | Playwright's Chromium installed | local | as Playwright |
| `just identity-smoke` → `tessaro-seed smoke identity` | the seed's settings plus `AUTHENTIK_BOOTSTRAP_TOKEN`, `ZULIP_ADAPTER_AUTHENTIK_TOKEN`, and `ZULIP_BOT_EMAIL`, `ZULIP_BOT_API_KEY` read from `.secrets/assistant/zulip-adapter.env` | one line per check, exit 0 only if all pass | as listed | exit 1 naming the failed check; the smoke user is deactivated in a `finally` |

**Value sourcing**:

| Action | Value | Source |
|---|---|---|
| Seed | people, usernames, names, emails, `employee_id`, groups | `export_authentik(dataset)` (spec 0002 AC-7, AC-9) |
| Seed | Zulip users, channels, descriptions, subscriptions | `export_zulip(dataset)` |
| Seed | which people are seeded | `Dataset.seed_employees(include_demo_inputs=False)` at anchor now |
| Seed | demo password | `TESSARO_DEMO_PASSWORD` in `.env`, generated by `just identity-secrets` |
| Seed | Zulip password for new users | random 32 bytes per user, never stored (email login is off) |
| Blueprints | group names and `elevated` | `export_authentik(dataset, include_demo_inputs=True).groups` |
| Blueprints | tokens, client secret, admin password | `!Env` from `authentik-secrets` (AC-8) |
| Zulip OIDC | `oidc_url`, `display_name`, `client_id`, `auto_signup` | *Zulip server settings* above |
| Zulip OIDC | client secret | `ZULIP_OIDC_CLIENT_SECRET`, the same value in `zulip-secrets` as `social_auth_oidc_secret` |
| Zulip | trusted proxy range for `LOADBALANCER_IPS` | the cluster's pod CIDR that holds the `ingress-nginx` pods (read at build from the node `podCIDR`s, recorded in values) |
| Databases | host, database, user, password | CNPG: Service `<cluster>-rw`, `bootstrap.initdb` names, Secret `<cluster>-app` key `password` |
| Images | digests | the registry's multi arch manifest list digest for each pinned tag, resolved at build and written into values and manifests |
| Bootstrap | owner email and name | `tessaro-admin@tessaro.example`, `Tessaro Admin` (the blueprint's admin) |
| Bootstrap | owner API key | `manage.py shell` on the owner's user record, every run |
| Bootstrap | bot payload URL | `zulip-adapter` Service in `assistant`, chart port `8080` (`charts/tessaro-service` default), path `/zulip/webhook` (decided here; feature 12 must serve it) |
| Bootstrap | `ZULIP_BOT_EMAIL`, `ZULIP_BOT_API_KEY` | Zulip's create bot response, or `GET /api/v1/bots` on rerun |
| Bootstrap | `ZULIP_WEBHOOK_TOKEN` | `GET /api/v1/bots` `services[].token`, fallback `manage.py shell` on the bot's service record |
| Handoff | `AUTHENTIK_URL` for the adapter | `http://authentik-server.identity.svc.cluster.local` (chart Service `<release>-server`, release `authentik`) |
| Handoff | `AUTHENTIK_API_TOKEN` for the adapter | copy of `ZULIP_ADAPTER_AUTHENTIK_TOKEN` |
| Smoke | the persona to sign in as | the demo cast role "demo persona" (spec 0002 AC-15) |
| Smoke | expected groups | `authentik_groups(dataset, persona)` |
| Smoke | Authentik credential | `AUTHENTIK_BOOTSTRAP_TOKEN` (copied into `.env` by `just identity-secrets`) |
| Report | versions, PVC placement, memory sums | `kubectl` on the live cluster |

**Network paths** (each one a policy in that namespace's manifests folder; everything else is denied by spec 0007's baseline):

| From | To | Port | Why |
|---|---|---|---|
| `ingress-nginx` controller | Authentik server | 9000 | the UI and API through `auth.` |
| `ingress-nginx` controller | Zulip server | 80 | the UI and API through `chat.` (TLS ends at the ingress) |
| Authentik server and worker | `authentik-db` | 5432 | database |
| `assistant` pods `app.kubernetes.io/name: zulip-adapter` | Authentik server | 9000 | adapter user lookups (feature 12) |
| Zulip server | `zulip-db`, Redis, RabbitMQ, memcached | 5432, 6379, 5672, 11211 | backing services |
| Zulip server | `ingress-nginx` controller pods | 443 | OIDC discovery, token and JWKS calls to `auth.` (Cilium sees the backend pod after its load balancer translation; if the build shows it sees `172.16.70.40`, a CiliumNetworkPolicy `toCIDR: 172.16.70.40/32` port 443 replaces this rule) |
| Zulip server | `assistant` pods `app.kubernetes.io/name: zulip-adapter` | 8080 | outgoing webhook |
| `cnpg-system` operator | each CNPG instance | 8000, 5432 | operator status and control |
| each CNPG instance | Kubernetes API (`toEntities: [kube-apiserver]`) | 443, 6443 | CNPG instance manager |

**Capacity** (memory requests; limits left to the LimitRange maximum unless the chart needs one):

| Namespace | Pod | Request | Storage |
|---|---|---|---|
| `identity` | Authentik server | 512Mi | none |
| `identity` | Authentik worker | 384Mi | none |
| `identity` | `authentik-db` | 256Mi | 2Gi `longhorn` |
| `chat` | Zulip server (heavy, one replica, no surge) | 1536Mi | 5Gi `longhorn` (data and uploads) |
| `chat` | `zulip-db` | 256Mi | 5Gi `longhorn` |
| `chat` | RabbitMQ | 256Mi | none |
| `chat` | Redis | 64Mi | none |
| `chat` | memcached | 96Mi | none |

That is about 1.1 GiB in `identity` (quota 2Gi) and 2.2 GiB in `chat` (quota 3Gi), and 12Gi of 3 replica Longhorn of the 45 GiB budget (spec 0007). The Authentik server and worker may surge during a rollout (1.1 + 0.9 GiB stays under 2Gi).

**Key invariants**:
- After a seed run, every seeded person has the dataset's `employee_id`, email, groups and active state in Authentik, and a Zulip account with the same email, active, subscribed to exactly their dataset channels.
- The seed never changes or deletes a record it does not own (AC-12).
- Zulip creates no account on sign in; only the seed and the identity workflows create Zulip users.
- No group yields a role except through spec 0003's `GROUP_TO_ROLE`; `authentik Admins`, `svc-tessaro-seed` and `svc-zulip-adapter` map to none.
- No pod in `identity` or `chat` reaches the internet.
- No credential is in git except as a strict scope SealedSecret; database credentials never leave CNPG's generated Secrets.
- Rendered releases never contain a cluster scoped kind and never pull a Bitnami image.

**Security model**:
- Authentik superusers: `akadmin` (break glass, bootstrap password) and `tessaro-admin`, both in `authentik Admins` and behind TOTP through a blueprint managed authentication flow `tessaro-authentication` (identification, password, then an MFA validation stage bound by the expression policy `return request.context["pending_user"].is_superuser` with `re_evaluate_policies: true` and "not configured" set to force TOTP enrolment), set as the authentication flow of the brand for `auth.tessaro.toyintest.org` (its own brand, so Authentik's system blueprint for the default brand never fights it).
- Role `tessaro-seed` (on `svc-tessaro-seed`): model permissions `authentik_core.view_user`, `add_user`, `change_user`, `reset_user_password`, `view_group`; object permissions `authentik_core.add_user_to_group` and `remove_user_from_group` on each dataset group only (generated into `20-groups.yaml`), so its token cannot put anyone, itself included, into `authentik Admins`. No delete and no provider, flow or blueprint permissions.
- Role `zulip-adapter` (on `svc-zulip-adapter`): `authentik_core.view_user` and `view_group` only.
- `AUTHENTIK_BOOTSTRAP_TOKEN` is a superuser token kept in the sealed Secret and your git ignored `.env`; only the smoke and the admin password fallback use it.
- Who may sign in to Zulip: members of `staff` and the user `tessaro-admin` (Authentik policy binding), and only if a Zulip account already exists (no auto signup). Removing someone from `staff` or deactivating them in Authentik stops their next sign in; ending existing Zulip sessions is the leaver workflow's job (spec 0003).
- Dataset employees are ordinary Zulip members; `tessaro-admin` is the realm owner; the bot is a normal outgoing webhook bot with no admin rights. Real emails are visible to every realm member; the people are fictional.
- Exposure stays as spec 0007 set it: LAN and tailnet only. The seed token, the bootstrap token, Zulip's owner key and the demo password live only in your git ignored `.env`.
- Data is fictional (`.example` emails), so no compliance scope applies; audit of identity changes is Authentik's own event log here, and the identity tool server's audit (feature 24) later.

**Configuration required**:
- `.env` (local, git ignored; placeholders in `.env.example`; read by a pydantic settings class `SeedSettings` in `tessaro-seed`, failing fast on a variable the chosen subcommand needs): `AUTHENTIK_URL=https://auth.tessaro.toyintest.org`, `AUTHENTIK_SEED_TOKEN` (copy of `TESSARO_SEED_TOKEN`), `AUTHENTIK_BOOTSTRAP_TOKEN` (copy, smoke only), `ZULIP_ADAPTER_AUTHENTIK_TOKEN` (copy, smoke only), `ZULIP_SITE=https://chat.tessaro.toyintest.org`, `ZULIP_ADMIN_EMAIL`, `ZULIP_ADMIN_API_KEY` (both written by bootstrap), `TESSARO_DEMO_PASSWORD`.
- `authentik-secrets` (identity, sealed): `AUTHENTIK_SECRET_KEY`, `AUTHENTIK_BOOTSTRAP_PASSWORD`, `AUTHENTIK_BOOTSTRAP_TOKEN`, `TESSARO_ADMIN_PASSWORD`, `TESSARO_SEED_TOKEN`, `ZULIP_ADAPTER_AUTHENTIK_TOKEN`, `ZULIP_OIDC_CLIENT_SECRET`.
- `zulip-secrets` (chat, sealed): Zulip's secret key, `ZULIP_OIDC_CLIENT_SECRET` (mapped to `social_auth_oidc_secret`), `REDIS_PASSWORD`, `RABBITMQ_PASSWORD`. The exact chart keys follow its existing secret support; the build maps them and documents the mapping in `deploy/platform/zulip/values.yaml`.
- `.secrets/assistant/zulip-adapter.env` (git ignored, for feature 12 to seal with its signing key): `ZULIP_SITE`, `ZULIP_BOT_EMAIL`, `ZULIP_BOT_API_KEY`, `ZULIP_WEBHOOK_TOKEN`, `AUTHENTIK_URL` (internal), `AUTHENTIK_API_TOKEN`.
- Outside this repo: in `k3sprox-gitops`, add `https://charts.goauthentik.io` and `ghcr.io/zulip/helm-charts` to `sourceRepos` of AppProject `tessaro` (and the reference copy here), and an Argo CD repository Secret in `argocd` for `ghcr.io/zulip/helm-charts` with `type: helm` and `enableOCI: "true"` (anonymous, no credentials).

**Critical test scenarios**:
- Happy path: sync both Applications, run `just zulip-bootstrap` and `just seed-identity`, then `just identity-smoke` signs the demo persona in to Zulip through Authentik and finds their groups in the claims, verifies **AC-1**, **AC-6**, **AC-11**, **AC-12**, **AC-14**
- Rerun: a second seed and bootstrap report no changes and rotate no key; a seed after deactivating the leaver in Authentik reactivates them, verifies **AC-11**, **AC-12**
- Stale config: remove a group from `20-groups.yaml` locally and `just check` fails; in the fakes, a missing group or a missing realm stops the seed before any write, verifies **AC-9**, **AC-12**
- Denied: a `staff` user without a Zulip account gets no Zulip session, a non `staff` user is stopped by Authentik, a password login is refused, the adapter token gets 403 on writes, and the seed token cannot add a user to `authentik Admins`, verifies **AC-9**, **AC-14**, **AC-16**
- Isolation: `https://example.com` is blocked from both namespaces and the proof still passes; rendered releases hold no cluster scoped kind and no Bitnami image, verifies **AC-2**, **AC-7**, **AC-18**
- Admin: `tessaro-admin` is asked for TOTP, the demo persona is not, verifies **AC-15**

## Build plan

Tracer Bullet: first prove one person signs in to Zulip through Authentik with every layer real (Argo CD, CNPG, ingress, policies, sealed secrets, blueprints, OIDC), then thicken to the bot, the security extras and the proofs.

- [x] 1. Repo plumbing: add `.secrets/` to `.gitignore`; vendor CNPG's `postgresql.cnpg.io` schemas into `charts/schemas/`; extend `just charts` to render platform Applications (pinned chart plus values plus `kustomize build`) with the AC-18 tests, starting with zero platform Applications so CI stays green; scaffold `libs/tessaro-seed` with `SeedSettings` and the `identity-secrets` generator (TDD, mirrors `tessaro_auth.devkeys`, including the copied values), satisfies **AC-8**, **AC-18**
- [x] 2. Clients first: `AuthentikDirectory` and `ZulipAdmin` protocols, in memory fakes seeded from the dataset, and the real httpx clients (unit tested with `httpx.MockTransport`); the `tessaro-seed identity` reconcile logic against the fakes (missing group, missing realm, never touching unowned records, idempotent second run), satisfies **AC-12**, **AC-13**
- [ ] 3. Thin thread, Authentik: `deploy/platform/authentik/` with values (pinned chart, CNPG connection, no bundled Postgres, `serviceAccount.create: false`, phone home settings off, Ingress) and manifests (CNPG cluster, the identity network paths, blueprints for `tessaro-admin` in `authentik Admins`, the `zulip` provider and application with `staff` declared, the `staff` or `tessaro-admin` binding, `svc-tessaro-seed` with its role and token, and `20-groups.yaml` from `just blueprints` with `just blueprints-check` in `just check`); add the AppProject `sourceRepos` and the OCI repository entry in `k3sprox-gitops` and the reference copy; generate and seal `authentik-secrets`; add `deploy/argocd/authentik.yaml`; sync, check the blueprint status, sign in as `tessaro-admin`, satisfies **AC-1**, **AC-2**, **AC-3**, **AC-6**, **AC-7**, **AC-8**, **AC-9**, **AC-10**
- [ ] 4. Thin thread, Zulip: `deploy/platform/zulip/` with values (pinned chart, subcharts off, external Postgres, Redis, RabbitMQ and memcached, the *Zulip server settings*, the missing dictionaries mode, heavy label, one replica with no surge) and manifests (CNPG cluster, the three backing services, the chat network paths including the egress to the ingress controller); seal `zulip-secrets`; add `deploy/argocd/zulip.yaml`; write `just zulip-bootstrap` steps 1 to 4 (realm, defaults, owner, realm rules), satisfies **AC-1**, **AC-2**, **AC-3**, **AC-5**, **AC-6**, **AC-7**, **AC-8**, **AC-10**, **AC-11**, **AC-17**
- [ ] 5. First real sign in: run `just seed-identity` for the full seed (about 30 people), add `just smoke-deps` and the first slice of `tessaro-seed smoke identity` (check a: the demo persona signs in to Zulip), and fix anything here before thickening, satisfies **AC-12**, **AC-14**
- [ ] 6. Thicken Authentik: the `zulip-adapter` service account, group, role and token; the superuser TOTP flow on its own brand; enrol TOTP for both admins and record it, satisfies **AC-9**, **AC-15**, **AC-16**
- [ ] 7. Bot and the rest of the smoke: bootstrap step 5 (`tessaro-bot`) and the values written to `.secrets/assistant/zulip-adapter.env`; smoke checks b to e (claims, the smoke user refusals, password login refused, search, token checks), satisfies **AC-4**, **AC-11**, **AC-14**, **AC-16**
- [ ] 8. Prove and record: rerun `just netpol-proof` and the `kubectl exec` egress checks and append them; append `just identity-smoke`; add versions, PVC placement and memory sums to `docs/environment-report.md`; tick spec 0007's Zulip Postgres follow up and record the `enablePDB: false` choice there, satisfies **AC-7**, **AC-17**

## Consequences

**Positive**:
- One identity for every later system: features 10 and 11 add one blueprint provider each and reuse the same pattern.
- The dataset stays the single source: groups are generated from it and people are reconciled to it, so a demo reset is one command.
- `AuthentikDirectory` and `ZulipAdmin` are the clients feature 12 (lookups) and feature 24 (identity tools) need, so the seed is their first real user.
- No Bitnami images and no cluster scoped RBAC, so the fence from spec 0007 holds apart from two `sourceRepos` lines and one repository entry.

**Negative / tradeoffs**:
- Zulip search stems words less well without the hunspell dictionaries; if docker-zulip lacks that mode, a custom Postgres image becomes necessary (AC-4).
- Running Redis, RabbitMQ and memcached ourselves means three more images to pin and bump, and Zulip upgrades must check their versions against Zulip's supported list.
- The seed runs from the laptop, not inside the cluster: it is not GitOps, and it needs the ingress hostnames and admin credentials on your machine, including a superuser token for the smoke.
- One shared demo password means anyone holding it can be anyone; acceptable only because the people are fictional and the hosts are private.
- No backups: losing a Longhorn volume loses Zulip's message history; everything else is rebuilt from git and the dataset.
- `enablePDB: false` lets a drain take each database down for about a minute, and Zulip's single non surging replica means a minute of chat downtime on every upgrade.
- The bot answers DMs with a failure message until feature 12 deploys the adapter.
- Several details are confirmed only at build time (the Zulip chart's OIDC and secret value keys, the missing dictionaries setting, Authentik's claim preview, which mapping carries `groups`, blueprint support for user passwords and per object permissions, a CNPG health check in Argo CD); each has a stated fallback here, and a failed fallback routes back to `/architect`.

**Neutral**:
- A new workspace package `libs/tessaro-seed`; features 10 and 11 add `platform` and `teams` subcommands.
- `charts/schemas/` gains CNPG; `just charts` now pulls two upstream charts in CI.
- The webhook path `/zulip/webhook` is now a contract feature 12 must serve.
- Both Applications sync in the same wave; Zulip contacts Authentik only when someone signs in, so neither waits on the other.

## Follow-up

- [ ] Feature 12: seal `zulip-adapter-secrets` from `.secrets/assistant/zulip-adapter.env` plus the production `TOKEN_SIGNING_KEY`, and serve `POST /zulip/webhook` on port 8080; the adapter matches `sender_email` against Authentik.
- [ ] Feature 24: design the identity tool server's Authentik account and role (create and deactivate users, group membership, end sessions) as another blueprint service account, and reuse `AuthentikDirectory` and `ZulipAdmin`.
- [ ] Feature 32: the demo reset reruns `just seed-identity` and removes the demo only joiners (`demo_actions` IDs) from both systems.
- [ ] `webapp-testing` conventions are not yet in an `AGENTS.md`; they belong in `libs/tessaro-seed/AGENTS.md` (the smoke lives there), with a pointer from root `## Agent skills`.
- [ ] Declined for now: Authentik and Zulip Agent Skills (community, unproven) and the Authentik and Zulip MCP servers; record under `Declined:` in root `AGENTS.md`.
- [ ] Bump policy for the pinned charts and the three backing images (a Renovate style check or a monthly manual pass) once more platform systems land.
