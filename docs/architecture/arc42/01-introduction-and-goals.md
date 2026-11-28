# 1. Introduction and Goals

## 1.1 Requirements Overview

OpenArtifact is a self-hosted board of artifacts that run through pipelines. An artifact is a card with a number,
an optional parent and a pipeline target; a pipeline is a stored graph of stages and actions; an action is defined
by an action definition whose execution nodes (timer, Code, HTTP) do the work. The state of every part is listed in
[chapter 4.3](04-solution-strategy.md#43-built-and-planned).

**Key requirements:**

- Self-hosted distribution via Docker/Docker Compose; one container, one volume, one SQLite file
- Web interface served on a configurable port (default 2909)
- HTTP API for the frontend, an integration API (`/api/v1`) and an MCP server (`/mcp`; its tools depend on the configuration) for scripts and agents
- Concurrent pipeline execution with background processing (in-process `asyncio`)
- Execution nodes that do real work: **Code** (a shell or Python script as a child process) and **HTTP** (one request with an SSRF guard), next to the timer
- A credential store: named secrets, encrypted at rest, used by nodes by reference only (named secrets through the API; managed credentials on *Settings › Credentials*, ADR-051)
- An execution history: every start of an artifact is kept as an execution with its steps, a retention policy per artifact, a read-only flow view on the editor canvas and a global list of all executions
- Human oversight and intervention (manual start and stop; a waiting status is planned)
- Artifact-centric data model: every artifact is a card with a number, a parent and a pipeline position
- Extensible building blocks (node kinds, executors, navigation entries); loading third-party extensions is planned, not built
- Deterministic pipeline orchestration: pipelines, stages and actions are explicit, stored graphs

Technology decisions are documented in ADR-002 (Language), ADR-003 (Backend), ADR-010 (Frontend; ADR-004 is superseded), ADR-005 and ADR-020 (Database), ADR-006 (API) and ADR-007 (Docker Distribution); the decisions about execution nodes, credentials and history are ADR-021 to ADR-028. See [chapter 9](09-architecture-decisions.md) for all of them.

## 1.2 Quality Goals

- **Maintainability:** Clear separation of concerns, type-safe Python, testable architecture
- **Extensibility:** Registries for node kinds, executors and navigation entries (ADR-014, ADR-021); agent providers are planned
- **Self-hosting simplicity:** Single `docker compose up` deployment
- **Reliability:** Graceful shutdown, health checks, restart policies; runs interrupted by a restart are marked `stopped`, and leftover Code processes of a hard-killed application are cleaned up at the next start
- **Traceability:** Who created an artifact (`created_by`), how a run was started (`started_by`: `user`, `api`, `mcp`) and what every node did (a step per node with outcome, output and duration) is recorded and kept as an execution history with a retention policy (ADR-025)
- **Security of execution:** Code and HTTP nodes run foreign instructions. Child processes are resource-limited, HTTP requests are guarded against SSRF, secrets are encrypted and masked, Execute Command nodes and credentials need an API token. There is no sandbox; see [8.1](08-cross-cutting-concepts/08.01-security.md) for what is and is not covered (ADR-023, ADR-024)
- **Security of access:** One access token protects everything; secrets and tokens are masked in logs; hardened non-root container ([chapter 8.1](08-cross-cutting-concepts/08.01-security.md), [SECURITY.md](../../../SECURITY.md))

## 1.3 Stakeholders

- **Project owners** — Define and manage the artifacts on the board
- **Pipeline designers** — Create pipelines and action definitions, including Code and HTTP nodes
- **Operators of agents and scripts** — Drive artifacts and read executions through the integration API and the MCP server
- **End users** — Interact with the platform through the web interface
- **Self-hosting users** — Deploy and maintain OpenArtifact on their infrastructure; they also hold the API token and the secret key
