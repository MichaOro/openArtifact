# Architecture Decision Records

One file per decision, numbered in sequence (`NNN-short-kebab-title.md`). The format and the rules for changing
an accepted ADR are in [`TEMPLATE.md`](TEMPLATE.md) and [docs/README.md](../../README.md). Accepted ADRs keep their
history: when reality changes, a dated `Update (YYYY-MM-DD): title` section and the relation lines on both ADRs
record it. The index in [arc42 chapter 9](../arc42/09-architecture-decisions.md) follows this one.

**Status values:** *Proposed*; *Accepted*; *Superseded* (replaced entirely by a newer ADR); *Deprecated* (no longer
relevant, nothing replaces it). **Relations** are written on both sides.

| ADR | Title | Status | Date | Relations |
|-----|-------|--------|------|-----------|
| [001](001-project-initialization.md) | Project Initialization | Accepted | 2026-11-18 | — |
| [002](002-application-language.md) | Application Language | Accepted | 2026-11-18 | — |
| [003](003-backend-framework.md) | Backend Framework | Accepted | 2026-11-18 | — |
| [004](004-frontend-approach.md) | Frontend Approach | Superseded | 2026-11-18 | superseded by ADR-010 |
| [005](005-database-persistence.md) | Database and Persistence | Accepted | 2026-11-18 | amended by ADR-020 |
| [006](006-api-design.md) | API Design | Accepted | 2026-11-18 | amended by ADR-010, ADR-016 |
| [007](007-docker-distribution.md) | Docker Distribution and Deployment Model | Accepted | 2026-11-18 | amended by ADR-020 |
| [008](008-security-operations.md) | Security and Operations Foundation | Accepted | 2026-11-18 | amended by ADR-016, ADR-017, ADR-023, ADR-024 |
| [009](009-technology-summary.md) | Technology Summary and Implementation Roadmap | Deprecated | 2026-11-18 | amended by ADR-011, ADR-020 |
| [010](010-frontend-without-htmx.md) | Frontend without HTMX — Server-rendered Shell with Vanilla JavaScript | Accepted | 2026-11-20 | supersedes ADR-004; amends ADR-006; amended by ADR-029 |
| [011](011-board-interactions-sse-and-pointer-dnd.md) | Board interactions — SSE-driven UI and Pointer-Events drag & drop | Accepted | 2026-11-20 | amends ADR-009 |
| [012](012-workflow-definition-editor.md) | Pipeline and action definitions as a graph, edited on a canvas | Accepted | 2026-11-21 | amended by ADR-014, ADR-015, ADR-030 |
| [013](013-execution-engine-and-runs.md) | Execution engine and pipeline runs | Accepted | 2026-11-21 | amended by ADR-015, ADR-018, ADR-021, ADR-025, ADR-026 |
| [014](014-building-blocks-and-extension-points.md) | Building blocks and extension points | Accepted | 2026-11-21 | amends ADR-012; amended by ADR-019, ADR-021, ADR-022, ADR-030 |
| [015](015-vocabulary-and-storage-names.md) | Vocabulary and storage names | Accepted | 2026-11-21 | amends ADR-012, ADR-013; amended by ADR-016 |
| [016](016-access-protection-integration-api-and-mcp.md) | Access protection, integration API and MCP | Accepted | 2026-11-21 | amends ADR-006, ADR-008, ADR-015; amended by ADR-017, ADR-026 |
| [017](017-request-hardening-and-signed-sessions.md) | Request hardening and signed, expiring sessions | Accepted | 2026-11-22 | amends ADR-008, ADR-016; amended by ADR-023, ADR-024 |
| [018](018-typed-runs-one-error-one-persistence-rule.md) | Typed runs, one refusal error, one persistence rule | Accepted | 2026-11-22 | amends ADR-013; amended by ADR-032 |
| [019](019-module-boundaries-and-single-sources.md) | Module boundaries and single sources | Accepted | 2026-11-22 | amends ADR-014; amended by ADR-022, ADR-032 |
| [020](020-sqlite-stays-postgres-as-data-source.md) | SQLite stays; PostgreSQL only as a data source | Accepted | 2026-11-22 | amends ADR-005, ADR-007, ADR-009 |
| [021](021-execution-nodes-as-executors.md) | Execution nodes as executors | Accepted | 2026-11-22 | amends ADR-013, ADR-014 |
| [022](022-node-settings-as-json-config.md) | Node settings as JSON config | Accepted | 2026-11-22 | amends ADR-014, ADR-019 |
| [023](023-safety-model-of-execution-nodes.md) | Safety model of execution nodes | Accepted | 2026-11-22 | amends ADR-008, ADR-017 |
| [024](024-credential-store.md) | Credential store | Accepted | 2026-11-22 | amends ADR-008, ADR-017 |
| [025](025-execution-history-and-retention.md) | Execution history and retention | Accepted | 2026-11-22 | amends ADR-013; amended by ADR-027, ADR-028 |
| [026](026-origin-of-a-run-started-by.md) | Origin of a run (`started_by`) | Accepted | 2026-11-22 | amends ADR-013, ADR-016 |
| [027](027-execution-flow-by-replay-over-the-frozen-snapshot.md) | Execution flow by replay over the frozen snapshot | Accepted | 2026-11-22 | amends ADR-025 |
| [028](028-global-executions-page-and-keyset-paging.md) | Global executions page and keyset paging | Accepted | 2026-11-22 | amends ADR-025 |
| [029](029-dialog-system.md) | Dialog system | Accepted | 2026-11-22 | amends ADR-010 |
| [030](030-accessibility-scope.md) | Accessibility scope | Accepted | 2026-11-22 | amends ADR-012, ADR-014 |
| [031](031-licence-apache-2-0.md) | Licence Apache-2.0 | Accepted | 2026-11-22 | — |
| [032](032-removal-of-the-unused-workspace-model.md) | Removal of the unused workspace model (Project/WorkItem) and repositories | Accepted | 2026-11-22 | amends ADR-018, ADR-019 |
| [033](033-run-context.md) | Run context | Accepted | 2026-11-22 | amends ADR-021, ADR-025 |
| [034](034-branching-nodes-and-reference-suggestions.md) | Branching nodes and reference suggestions | Accepted | 2026-11-22 | amends ADR-021, ADR-022 |
| [035](035-artifact-types-and-card-parameters.md) | Artifact types and card parameters | Accepted | 2026-11-22 | amends ADR-022, ADR-033 |
| [036](036-ui-conventions-and-lane-settings.md) | UI conventions and lane settings | Accepted | 2026-11-22 | amends ADR-011, ADR-029 |
| [037](037-agent-harness.md) | Agent harness: agents, LLM providers, the agent node | Accepted | 2026-11-22 | amends ADR-021, ADR-022, ADR-024, ADR-025, ADR-027, ADR-033 |
| [038](038-repository-layout.md) | Repository layout: one Python project at the root | Accepted | 2026-11-23 | amends ADR-001, ADR-019 |
| [039](039-edit-fields-switch-rules-and-run-limits.md) | Edit Fields node, a rule per Switch case, run limits as settings | Accepted | 2026-11-23 | amends ADR-013, ADR-033, ADR-034 |
| [040](040-agent-tools.md) | Tools for agents: tool nodes, MCP Client Tool, a bounded loop | Accepted | 2026-11-23 | amends ADR-012, ADR-037 |
| [041](041-github-and-postgres-nodes.md) | The GitHub node and Postgres: an action node and a tool for agents | Accepted | 2026-11-23 | amends ADR-012, ADR-020, ADR-040 |

## Notes

- The file name of ADR-012 keeps the word "workflow"; the content uses the vocabulary of
  [ADR-015](015-vocabulary-and-storage-names.md). Links stay valid, so the file is not renamed.
- ADR-009 is deprecated: it was the bootstrap plan. ADR-004 is superseded by ADR-010.
- ADR-001 to ADR-016 are written in the long form of the template (drivers and options), later ones partly in the
  short form. Old ADRs are not rewritten.
- Quarantine of unused code is part of [ADR-014](014-building-blocks-and-extension-points.md) §3.6, not a separate ADR.
