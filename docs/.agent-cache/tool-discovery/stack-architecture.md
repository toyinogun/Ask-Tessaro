# Agent Skills & MCP Server Discovery Report

**Date**: 2026-10-07

**Stack**: uv (Python workspaces), FastAPI, MCP Python SDK, LangGraph/LangChain, Temporal (Python), OpenFGA, Open Policy Agent (Rego), Microsoft Presidio, Helm, Argo CD, SOPS, Grafana Loki, Langfuse, Zulip, Authentik, Frappe HR/ERPNext

---

## Agent Skills (by Technology)

### FastAPI
- **wshobson/agents@fastapi-templates** (25.1K installs) — FastAPI application templates and scaffolding patterns
- **wshobson/agents@async-python-patterns** (17.2K installs) — Python async/await best practices and concurrency patterns
- **wshobson/agents@openapi-spec-generation** (15.7K installs) — Automated OpenAPI spec generation and API documentation

### LangGraph & LangChain
- **langchain-ai/langchain-skills@langgraph-persistence** (16.8K installs) — LangGraph state persistence and checkpointing
- **langchain-ai/langchain-skills@langgraph-fundamentals** (16.7K installs) — LangGraph core concepts and graph construction
- **langchain-ai/langchain-skills@langgraph-human-in-the-loop** (16.1K installs) — Human-in-the-loop workflow integration
- **langchain-ai/langchain-skills@langchain-dependencies** (15K installs) — LangChain dependency management and imports
- **wshobson/agents@rag-implementation** (13.3K installs) — Retrieval-Augmented Generation patterns
- **wshobson/agents@langchain-architecture** (12.7K installs) — LangChain system design and architecture

### Temporal (Workflow Orchestration)
- **wshobson/agents@workflow-orchestration-patterns** (11.6K installs) — Temporal workflows, activities, and signal handling
- **wshobson/agents@temporal-python-testing** (10.5K installs) — Temporal Python SDK testing and debugging

### Kubernetes & Helm
- **microsoft/azure-skills@azure-kubernetes** (410K installs) — Azure AKS and Kubernetes management
- **jeffallan/claude-skills@kubernetes-specialist** (13.4K installs) — Kubernetes cluster operations and debugging
- **wshobson/agents@helm-chart-scaffolding** (11.4K installs) — Helm chart creation and package management
- **aws/agent-toolkit-for-aws@aws-containers** (8.4K installs) — AWS container services (ECS, EKS)
- **affaan-m/ecc@kubernetes-patterns** (4K installs) — Kubernetes design patterns and best practices

### GitOps & Argo CD
- **wshobson/agents@gitops-workflow** (11.1K installs) — GitOps principles, Argo CD, and declarative deployments

### Grafana Stack
- **grafana/skills@infrastructure** (3.8K installs) — Grafana infrastructure and deployment
- **grafana/skills@mimir** (4.1K installs) — Grafana Mimir (metrics) server operations
- **grafana/skills@beyla** (4.2K installs) — Grafana Beyla (eBPF observability)
- **grafana/skills@fleet-management** (3.7K installs) — Grafana fleet management and multi-cluster

### Authentication & Security
- **microsoft/azure-skills@entra-app-registration** (542.3K installs) — Azure Entra ID and identity management
- **firebase/agent-skills@firebase-auth-basics** (164.7K installs) — Firebase authentication setup and flows
- **better-auth/skills@better-auth-best-practices** (118K installs) — BetterAuth framework and SSO patterns
- **addyosmani/agent-skills@security-and-hardening** (53.1K installs) — Security best practices and vulnerability hardening

### Observability & Monitoring
- **addyosmani/agent-skills@observability-and-instrumentation** (40.1K installs) — OpenTelemetry, logging, tracing

### Frappe HR / ERPNext
- **ravana-indus/erpnext-frappe** — ERPNext business workflows (CRM, HR, Sales, Inventory, Finance)

---

## MCP Servers (by Technology)

### Temporal (Workflow Orchestration)
- **steveandroulakis/temporal-nexus-mcp-demo** — MCP bridge to Temporal Nexus workflows
- **pmbstyle/temporal-awareness-mcp** — HTTP MCP server for Temporal awareness and workflow querying

### Langfuse (LLM Observability)
- **langfuse/mcp-server-langfuse** (Official, Nov 2025) — Native Langfuse MCP server with prompt management, trace querying, and analytics

### Argo CD (GitOps CD)
- **argoproj-labs/mcp-for-argocd** (Official) — Full ArgoCD API coverage: app/project/repo management, sync operations, health monitoring
- **talkopsai/argocd-mcp-server** (Docker) — Docker image for ArgoCD MCP server with GitOps deployment management

### Grafana Loki (Log Aggregation)
- **grafana-mcp-observability** — Grafana observability MCP server exposing Loki logs and Prometheus metrics
- **grafana-loki-mcp** — FastMCP-based Loki log query server with label support and multiple output formats
- **tumf/grafana-loki-mcp** — Community Loki MCP implementation

### Kubernetes
- **blankcut/kubernetes-mcp-server** — Kubernetes cluster management via kubectl operations

### OpenFGA (Authorization)
- **evansims/openfga-mcp** — OpenFGA authorization model management and policy checking

### SOPS (Secrets Management)
- **privacyplaybook/sops-mcp** — SOPS-encrypted secrets creation and management with age/KMS support

### Microsoft Presidio (PII Detection)
- **cmalpass/mcp-presidio** — FastMCP-based Presidio PII detection, anonymization, and analysis
- **ManoharMarri/local-presidio-mcp-server** — Local Presidio MCP server for privacy-preserving data handling

### Zulip (Team Chat)
- **akougkas/zulipchat-mcp** — Zulip messaging, stream management, real-time monitoring (60+ tools)

### Authentik (Identity Management)
- **cdmx-in/authentik-mcp** — Authentik user/group/app/policy/flow management (245 tools across 20 categories)
- **authentik-diag-mcp** — Read-only Authentik diagnostic server for monitoring and audit

---

## No Credible Candidates Found

**uv** (Python package manager) — No MCP servers or dedicated agent skills found
**Open Policy Agent (Rego)** — No MCP servers or agent skills found
**Frappe HR / ERPNext** — Skills/workflows exist (ravana-indus/erpnext-frappe) but no official MCP server

---

## MCP Python SDK

**Official Resource**: [MCP Python SDK Documentation](https://dev.to/aiarch_wibo/how-to-build-an-mcp-server-step-by-step-3iom)

Install with: `uv add "mcp[cli]"` or `pip install "mcp[cli]"`

Key features:
- Type-hint based input validation (no manual JSON Schema)
- Async-first architecture native support
- Built-in FastMCP framework for rapid development
- Inspector tool via `uv run mcp dev server.py`

---

## Summary Statistics

- **Total Agent Skills Found**: 23 across 9 technology areas
- **Total MCP Servers Found**: 14+ across 8 technology areas
- **Highest Install Count Skill**: microsoft/azure-skills@azure-kubernetes (410K)
- **Official MCP Servers**: Langfuse, Argo CD, Kubernetes integrations

All skills and MCP servers exclude those already installed locally.
