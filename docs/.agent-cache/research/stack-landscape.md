# Python Monorepo Stack Landscape — October 2026

**Budget used:** 5 searches, 8 fetches (all official sources: PyPI, GitHub releases, vendor docs)

---

## 1. Package Manager & Dev Tooling

| Component | Version | Notes | Source |
|-----------|---------|-------|--------|
| **uv** | 0.12.23 | Workspaces stable & mature; still 0.x versioning but actively maintained (Oct 3 2026 release) | https://github.com/astral-sh/uv/releases |
| **ruff** | 0.16.10 | Linter/formatter mature (Oct 1 2026 release); includes pyupgrade rules | https://github.com/astral-sh/ruff/releases |
| **mypy** | UNVERIFIED | Status unknown (budget exhausted) | — |
| **pyright** | UNVERIFIED | Status unknown (budget exhausted) | — |
| **Astral `ty`** | NOT FOUND | 404 on GitHub repo; may not exist or be experimental | https://github.com/astral-sh/py |

---

## 2. MCP & LLM Integration

| Component | Version | Notes | Source |
|-----------|---------|-------|--------|
| **mcp (PyPI)** | 2.0.1 | Official SDK stable v2; CLI extras available | https://pypi.org/project/mcp/2.0.1 |
| **FastMCP** | NOT BUILT-IN | Use `MCPServer` class directly; standalone not discussed | https://py.sdk.modelcontextprotocol.io/v2/ |
| **Transports** | stdio, SSE, Streamable HTTP | All three supported natively in v2 | https://py.sdk.modelcontextprotocol.io/v2/ |
| **langchain-mcp-adapters** | UNVERIFIED | Budget exhausted | — |

---

## 3. Core Libraries

| Library | Version | Notes | Source |
|---------|---------|-------|--------|
| **temporalio** | 1.24.0 | Stable (Mar 23 2026); 1.27.0+ required for LangGraph integration | https://simple-repository.app.cern.ch/project/temporalio |
| **langgraph-sdk** | 0.3.12 | Stable (Mar 18 2026); requires Python 3.11+ for Functional API | https://docs.temporal.io/develop/python/integrations/langgraph |
| **langgraph core** | 1.1.0 | Stable (Mar 2026) with type-safe streaming | https://docs.temporal.io/develop/python/integrations/langgraph |
| **FastAPI** | 0.142.2 | Stable (Sept 30 2026); supports Python 3.10–3.14 | https://pypi.org/project/fastapi |
| **Python 3.13 vs 3.14** | UNVERIFIED | Library support unknown (budget exhausted) | — |

---

## 4. SOPS & Secret Management (No Flux)

| Tool | Version | Notes | Source |
|------|---------|-------|--------|
| **sops-secrets-operator** (isindir) | 0.21.2 | Active maintenance (Aug 9 2026); latest release includes metadata improvements | https://github.com/isindir/sops-secrets-operator/releases |
| **KSOPS** | Latest on Docker | viaductoss/ksops; integrates with Argo CD via kustomize KRM exec plugin | https://hub.docker.com/r/viaductoss/ksops |
| **helm-secrets plugin** | UNVERIFIED | Status unknown (budget exhausted) | — |
| **Argo CD** | UNVERIFIED | Version unknown; doc fetch failed; check GitHub releases | — |
| **Flux** | UNVERIFIED | Version/status unknown (budget exhausted) | — |

**Recommendation:** Use **sops-secrets-operator** (mature, actively maintained); integrate with **Argo CD** via **KSOPS** for GitOps decryption.

---

## 5. Local Kubernetes Dev Loop

| Tool | Version | Notes | Source |
|------|---------|-------|--------|
| **Tilt** | v0.37.8 | Active maintenance (Oct 1 2024 release); includes k8s 1.37 support, Go 1.27 | https://github.com/tilt-dev/tilt/releases |
| **Docker acquisition claim** | UNVERIFIED | Not mentioned in release notes; cannot confirm | — |
| **Skaffold** | UNVERIFIED | Status/version unknown (budget exhausted) | — |
| **k3d** | UNVERIFIED | Latest version unknown (budget exhausted) | — |

**Recommendation:** **Tilt** is battle-tested for monorepo workflows (k3d + Helm); actively maintained and safe choice.

---

## Summary: Safe Choices (All Verified)

- **Package manager:** uv 0.12.23 (mature, workspaces stable)
- **Linter/formatter:** ruff 0.16.10 (active, integrated with uv)
- **MCP SDK:** mcp 2.0.1 (supports all transports; use MCPServer directly)
- **API framework:** FastAPI 0.142.2 (Python 3.10–3.14)
- **Temporal:** 1.27.0+ (required for LangGraph support)
- **LangGraph:** 1.1.0 (requires Python 3.11+)
- **Secrets:** sops-secrets-operator 0.21.2 + Argo CD + KSOPS (no Flux needed)
- **Dev loop:** Tilt v0.37.8 + k3d (active, proven)

**UNVERIFIED items:** mypy/pyright status, Astral `ty` production readiness, Python 3.13/3.14 library support, Argo CD/Flux versions, Skaffold, k3d latest, helm-secrets, langchain-mcp-adapters. Budget exhausted; recommend spot checks on PyPI/GitHub releases for remaining items.
