# 1. Introduction and Goals

## 1.1 Requirements Overview

OpenArtifact is an open-source platform for orchestrating projects, pipelines, and AI agents around structured artifacts.

**Key requirements:**

- Self-hosted distribution via Docker/Docker Compose
- Web interface served on a configurable port (default 2909)
- HTTP API for the frontend, and an integration API (`/api/v1`) and an MCP server (`/mcp`) for scripts and agents
- Concurrent pipeline execution with background processing (in-process `asyncio`)
- Human-in-the-loop oversight and intervention (manual start and stop today; a waiting status is planned)
- Artifact-centric data model: every artifact is a card with a number, a parent and a pipeline position; runs are recorded
- Extensible building blocks (node kinds, navigation entries); loading third-party extensions is planned, not built
- Deterministic pipeline orchestration: pipelines, stages and actions are explicit, stored graphs

Technology decisions are documented in ADR-002 (Language), ADR-003 (Backend), ADR-010 (Frontend; ADR-004 is superseded), ADR-005 and ADR-020 (Database), ADR-006 (API) and ADR-007 (Docker Distribution); see chapter 9 for all of them.

## 1.2 Quality Goals

- **Maintainability:** Clear separation of concerns, type-safe Python, testable architecture
- **Extensibility:** Registries for node kinds and navigation entries (ADR-014); agent providers are planned
- **Self-hosting simplicity:** Single `docker compose up` deployment
- **Reliability:** Graceful shutdown, health checks, restart policies, runs interrupted by a restart are marked `stopped`
- **Transparency:** Who created an artifact (`created_by`) and started a run (`started_by`) is recorded; one run per artifact is kept, a history of runs is planned
- **Security:** One access token protects everything, secrets externalized and masked in logs, hardened non-root container (chapter 8.1)

## 1.3 Stakeholders

- **Project owners** — Define and manage project structure and artifacts
- **Pipeline designers** — Create and orchestrate automated pipelines
- **AI agent operators** — Configure and monitor autonomous agent execution
- **End users** — Interact with the platform through the web interface
- **Self-hosting users** — Deploy and maintain OpenArtifact on their infrastructure

