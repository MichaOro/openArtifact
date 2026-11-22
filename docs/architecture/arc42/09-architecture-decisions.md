# 9. Architecture Decisions

## Overview of Decisions

Architecture decisions are documented as Architecture Decision Records (ADRs) in the [`docs/architecture/adr/`](../adr/)
directory. The table lists every ADR with its status and its relations to the others; the ADR files are the source, the
header lines of each ADR and this table are kept in step. An accepted ADR keeps its text: when reality changes, a dated
`Update` section is added at the end and the relation lines are filled on both ADRs ([template](../adr/TEMPLATE.md)).

| # | ADR | Status | Relations |
|---|-----|--------|-----------|
| 1 | [Project Initialization](../adr/001-project-initialization.md) | Accepted | — |
| 2 | [Application Language](../adr/002-application-language.md) | Accepted | — |
| 3 | [Backend Framework](../adr/003-backend-framework.md) | Accepted | — |
| 4 | [Frontend Approach](../adr/004-frontend-approach.md) | Superseded | Superseded by [ADR-010](../adr/010-frontend-without-htmx.md) |
| 5 | [Database and Persistence](../adr/005-database-persistence.md) | Accepted | Amended by [ADR-020](../adr/020-sqlite-stays-postgres-as-data-source.md) |
| 6 | [API Design](../adr/006-api-design.md) | Accepted | Amended by [ADR-010](../adr/010-frontend-without-htmx.md) (HTMX), [ADR-016](../adr/016-access-protection-integration-api-and-mcp.md) (authentication) |
| 7 | [Docker Distribution and Deployment Model](../adr/007-docker-distribution.md) | Accepted | Amended by [ADR-020](../adr/020-sqlite-stays-postgres-as-data-source.md) |
| 8 | [Security and Operations Foundation](../adr/008-security-operations.md) | Accepted | Amended by [ADR-016](../adr/016-access-protection-integration-api-and-mcp.md), [ADR-017](../adr/017-request-hardening-and-signed-sessions.md), [ADR-023](../adr/023-safety-model-of-execution-nodes.md) (execution nodes), [ADR-024](../adr/024-credential-store.md) (credential store) |
| 9 | [Technology Summary and Implementation Roadmap](../adr/009-technology-summary.md) | Deprecated | Amended by [ADR-011](../adr/011-board-interactions-sse-and-pointer-dnd.md) (real-time updates), [ADR-020](../adr/020-sqlite-stays-postgres-as-data-source.md) |
| 10 | [Frontend without HTMX — Server-rendered Shell with Vanilla JavaScript](../adr/010-frontend-without-htmx.md) | Accepted | Supersedes [ADR-004](../adr/004-frontend-approach.md); Amends [ADR-006](../adr/006-api-design.md) (HTMX); Amended by [ADR-029](../adr/029-dialog-system.md) (dialogs) |
| 11 | [Board interactions — SSE-driven UI and Pointer-Events drag & drop](../adr/011-board-interactions-sse-and-pointer-dnd.md) | Accepted | Amends [ADR-009](../adr/009-technology-summary.md) (real-time updates) |
| 12 | [Pipeline and action definitions as a graph, edited on a canvas](../adr/012-workflow-definition-editor.md) | Accepted | Amended by [ADR-014](../adr/014-building-blocks-and-extension-points.md) (routing select), [ADR-015](../adr/015-vocabulary-and-storage-names.md) (vocabulary), [ADR-030](../adr/030-accessibility-scope.md) (accessibility) |
| 13 | [Execution engine and pipeline runs](../adr/013-execution-engine-and-runs.md) | Accepted | Amended by [ADR-015](../adr/015-vocabulary-and-storage-names.md) (vocabulary), [ADR-018](../adr/018-typed-runs-one-error-one-persistence-rule.md) (run model, atomic start), [ADR-021](../adr/021-execution-nodes-as-executors.md) (executors), [ADR-025](../adr/025-execution-history-and-retention.md) (history), [ADR-026](../adr/026-origin-of-a-run-started-by.md) (origin) |
| 14 | [Building blocks and extension points](../adr/014-building-blocks-and-extension-points.md) | Accepted | Amends [ADR-012](../adr/012-workflow-definition-editor.md) (routing select); Amended by [ADR-019](../adr/019-module-boundaries-and-single-sources.md) (module boundaries, registry-derived settings), [ADR-021](../adr/021-execution-nodes-as-executors.md) (executors), [ADR-022](../adr/022-node-settings-as-json-config.md) (settings as JSON), [ADR-030](../adr/030-accessibility-scope.md) (accessibility) |
| 15 | [Vocabulary and storage names](../adr/015-vocabulary-and-storage-names.md) | Accepted | Amends [ADR-012](../adr/012-workflow-definition-editor.md), [ADR-013](../adr/013-execution-engine-and-runs.md); Amended by [ADR-016](../adr/016-access-protection-integration-api-and-mcp.md) (resolves §6) |
| 16 | [Access protection, integration API and MCP](../adr/016-access-protection-integration-api-and-mcp.md) | Accepted | Amends [ADR-006](../adr/006-api-design.md), [ADR-008](../adr/008-security-operations.md), [ADR-015](../adr/015-vocabulary-and-storage-names.md) §6; Amended by [ADR-017](../adr/017-request-hardening-and-signed-sessions.md) (sessions, hardening), [ADR-026](../adr/026-origin-of-a-run-started-by.md) (origin of a run) |
| 17 | [Request hardening and signed, expiring sessions](../adr/017-request-hardening-and-signed-sessions.md) | Accepted | Amends [ADR-016](../adr/016-access-protection-integration-api-and-mcp.md), [ADR-008](../adr/008-security-operations.md); Amended by [ADR-023](../adr/023-safety-model-of-execution-nodes.md) (code nodes), [ADR-024](../adr/024-credential-store.md) (secret key) |
| 18 | [Typed runs, one refusal error, one persistence rule](../adr/018-typed-runs-one-error-one-persistence-rule.md) | Accepted | Amends [ADR-013](../adr/013-execution-engine-and-runs.md); Amended by [ADR-032](../adr/032-removal-of-the-unused-workspace-model.md) (unused errors removed) |
| 19 | [Module boundaries and single sources](../adr/019-module-boundaries-and-single-sources.md) | Accepted | Amends [ADR-014](../adr/014-building-blocks-and-extension-points.md); Amended by [ADR-022](../adr/022-node-settings-as-json-config.md) (settings), [ADR-032](../adr/032-removal-of-the-unused-workspace-model.md) (unused code removed) |
| 20 | [SQLite stays; PostgreSQL only as a data source](../adr/020-sqlite-stays-postgres-as-data-source.md) | Accepted | Amends [ADR-005](../adr/005-database-persistence.md), [ADR-007](../adr/007-docker-distribution.md), [ADR-009](../adr/009-technology-summary.md) |
| 21 | [Execution nodes as executors](../adr/021-execution-nodes-as-executors.md) | Accepted | Amends [ADR-013](../adr/013-execution-engine-and-runs.md), [ADR-014](../adr/014-building-blocks-and-extension-points.md) |
| 22 | [Node settings as JSON config](../adr/022-node-settings-as-json-config.md) | Accepted | Amends [ADR-014](../adr/014-building-blocks-and-extension-points.md) (update of 2026-11-22), [ADR-019](../adr/019-module-boundaries-and-single-sources.md) §3.1 |
| 23 | [Safety model of execution nodes](../adr/023-safety-model-of-execution-nodes.md) | Accepted | Amends [ADR-008](../adr/008-security-operations.md), [ADR-017](../adr/017-request-hardening-and-signed-sessions.md) |
| 24 | [Credential store](../adr/024-credential-store.md) | Accepted | Amends [ADR-008](../adr/008-security-operations.md) §5, [ADR-017](../adr/017-request-hardening-and-signed-sessions.md) §5.2 |
| 25 | [Execution history and retention](../adr/025-execution-history-and-retention.md) | Accepted | Amends [ADR-013](../adr/013-execution-engine-and-runs.md) §3, §4; Amended by [ADR-027](../adr/027-execution-flow-by-replay-over-the-frozen-snapshot.md), [ADR-028](../adr/028-global-executions-page-and-keyset-paging.md) |
| 26 | [Origin of a run (`started_by`)](../adr/026-origin-of-a-run-started-by.md) | Accepted | Amends [ADR-013](../adr/013-execution-engine-and-runs.md), [ADR-016](../adr/016-access-protection-integration-api-and-mcp.md) |
| 27 | [Execution flow by replay over the frozen snapshot](../adr/027-execution-flow-by-replay-over-the-frozen-snapshot.md) | Accepted | Amends [ADR-025](../adr/025-execution-history-and-retention.md) |
| 28 | [Global executions page and keyset paging](../adr/028-global-executions-page-and-keyset-paging.md) | Accepted | Amends [ADR-025](../adr/025-execution-history-and-retention.md) |
| 29 | [Dialog system](../adr/029-dialog-system.md) | Accepted | Amends [ADR-010](../adr/010-frontend-without-htmx.md) §6 |
| 30 | [Accessibility scope](../adr/030-accessibility-scope.md) | Accepted | Amends [ADR-012](../adr/012-workflow-definition-editor.md) (update of 2026-11-22), [ADR-014](../adr/014-building-blocks-and-extension-points.md) §4 |
| 31 | [Licence Apache-2.0](../adr/031-licence-apache-2-0.md) | Accepted | — |
| 32 | [Removal of the unused workspace model (Project/WorkItem) and repositories](../adr/032-removal-of-the-unused-workspace-model.md) | Accepted | Amends [ADR-018](../adr/018-typed-runs-one-error-one-persistence-rule.md) §3.1, [ADR-019](../adr/019-module-boundaries-and-single-sources.md) §4 |
| 33 | [Run context](../adr/033-run-context.md) | Accepted | Amends [ADR-021](../adr/021-execution-nodes-as-executors.md), [ADR-025](../adr/025-execution-history-and-retention.md) |
| 35 | [Artifact types and card parameters](../adr/035-artifact-types-and-card-parameters.md) | Accepted | Amends [ADR-022](../adr/022-node-settings-as-json-config.md), [ADR-033](../adr/033-run-context.md) |

## Reading Guide

| Topic | Start with | Then |
|-------|-----------|------|
| Why this stack | ADR-003 (FastAPI), ADR-005 (SQLite), ADR-010 (vanilla JS), ADR-020 (SQLite stays) | ADR-009 is deprecated; ADR-007 (Docker) |
| Pipelines, actions and the engine | ADR-012, ADR-013, ADR-014 | ADR-018 (typed runs, atomic start), ADR-021, ADR-022 |
| Execution history | ADR-025 | ADR-026 (origin), ADR-027 (flow replay), ADR-028 (global list) |
| Security | ADR-008, ADR-016, ADR-017 | ADR-023 (execution nodes), ADR-024 (credential store) |
| Frontend | ADR-010, ADR-011 (board), ADR-029 (dialogs) | ADR-030 (accessibility scope) |
| Structure and conventions | ADR-015 (vocabulary), ADR-019 (module boundaries) | ADR-032 (unused model removed) |
| Legal | ADR-031 (Apache-2.0) | `LICENSE` |

Each ADR gives the context, the decision and the consequences; ADR-021 to ADR-032 are written in the short form and each
names where it is implemented (a migration, a module).
