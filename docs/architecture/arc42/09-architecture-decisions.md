# 9. Architecture Decisions

## Overview of Decisions

Architecture decisions are documented as Architecture Decision Records (ADRs) in the [`docs/architecture/adr/`](../adr/) directory.

| # | ADR | Status | Relations |
|---|-----|--------|-----------|
| 1 | [001-project-initialization](../adr/001-project-initialization.md) | Accepted | — |
| 2 | [002-application-language](../adr/002-application-language.md) | Accepted | — |
| 3 | [003-backend-framework](../adr/003-backend-framework.md) | Accepted | — |
| 4 | [004-frontend-approach](../adr/004-frontend-approach.md) | Superseded by ADR-010 | — |
| 5 | [005-database-persistence](../adr/005-database-persistence.md) | Accepted | Amended by ADR-020 |
| 6 | [006-api-design](../adr/006-api-design.md) | Accepted | Amended by ADR-010, ADR-016 |
| 7 | [007-docker-distribution](../adr/007-docker-distribution.md) | Accepted | Amended by ADR-020 |
| 8 | [008-security-operations](../adr/008-security-operations.md) | Accepted | Amended by ADR-016, ADR-017 |
| 9 | [009-technology-summary](../adr/009-technology-summary.md) | Accepted | Amended by ADR-011, ADR-020 |
| 10 | [010-frontend-without-htmx](../adr/010-frontend-without-htmx.md) | Accepted | — |
| 11 | [011-board-interactions-sse-and-pointer-dnd](../adr/011-board-interactions-sse-and-pointer-dnd.md) | Accepted | — |
| 12 | [012-workflow-definition-editor](../adr/012-workflow-definition-editor.md) | Accepted | Amended by ADR-014, ADR-015; file name kept (pipeline and action definitions) |
| 13 | [013-execution-engine-and-runs](../adr/013-execution-engine-and-runs.md) | Accepted | Amended by ADR-015, ADR-018 |
| 14 | [014-building-blocks-and-extension-points](../adr/014-building-blocks-and-extension-points.md) | Accepted | Amended by ADR-019 |
| 15 | [015-vocabulary-and-storage-names](../adr/015-vocabulary-and-storage-names.md) | Accepted | Amends ADR-012, ADR-013; amended by ADR-016 |
| 16 | [016-access-protection-integration-api-and-mcp](../adr/016-access-protection-integration-api-and-mcp.md) | Accepted | Amends ADR-006, ADR-015 §6; amended by ADR-017 |
| 17 | [017-request-hardening-and-signed-sessions](../adr/017-request-hardening-and-signed-sessions.md) | Accepted | Amends ADR-016 |
| 18 | [018-typed-runs-one-error-one-persistence-rule](../adr/018-typed-runs-one-error-one-persistence-rule.md) | Accepted | Amends ADR-013 |
| 19 | [019-module-boundaries-and-single-sources](../adr/019-module-boundaries-and-single-sources.md) | Accepted | Amends ADR-014 |
| 20 | [020-sqlite-stays-postgres-as-data-source](../adr/020-sqlite-stays-postgres-as-data-source.md) | Accepted | Amends ADR-005, ADR-007, ADR-009 |

## Detailed Decisions

Each referenced ADR provides the full context, options considered, decision rationale, and consequences.

The format and the rules for updating an accepted ADR are in the [template](../adr/TEMPLATE.md) and [docs/README.md](../../README.md).
