# 1. Introduction and Goals

## 1.1 Requirements Overview

OpenArtifact is an open-source platform for orchestrating projects, workflows, and AI agents around structured artifacts.

**Key requirements:**

- Self-hosted distribution via Docker/Docker Compose
- Web interface served on configurable port (default 2909)
- HTTP API for frontend and external integrations
- Concurrent workflow execution with background processing
- Human-in-the-loop oversight and intervention
- Artifact-centric data model with full traceability
- Extensible agent and provider architecture
- Deterministic workflow orchestration

Technology decisions are documented in ADR-002 (Language), ADR-003 (Backend), ADR-004 (Frontend), ADR-005 (Database), ADR-006 (API), and ADR-007 (Docker Distribution).

## 1.2 Quality Goals

- **Maintainability:** Clear separation of concerns, type-safe Python, testable architecture
- **Extensibility:** Plugin/adapters architecture for agents and providers
- **Self-hosting simplicity:** Single `docker compose up` deployment
- **Reliability:** Graceful shutdown, health checks, restart policies
- **Transparency:** Full audit trail of artifact changes and workflow executions
- **Security:** Secrets externalized, no secrets in logs, non-root containers

## 1.3 Stakeholders

- **Project owners** — Define and manage project structure and artifacts
- **Workflow designers** — Create and orchestrate automated workflows
- **AI agent operators** — Configure and monitor autonomous agent execution
- **End users** — Interact with the platform through the web interface
- **Self-hosting users** — Deploy and maintain OpenArtifact on their infrastructure

---

*This chapter follows the arc42 template. TBD fields are limited to domain-specific content to be defined in WP-02 onward.*
