# ADR-026: Origin of a run (`started_by`)

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-013](013-execution-engine-and-runs.md), [ADR-016](016-access-protection-integration-api-and-mcp.md)  
**Amended by:** —  
**Implemented in:** migration 0024 (check constraint of `pipeline_runs.started_by`); `models` (`StartedBy`), `api/v1.py`, `mcp_server.py`, `engine/runner.py`  
**Affected chapters:** [05.01](../arc42/05-building-block-view/05.01-domain-model.md), [06.04](../arc42/06-runtime-view/06.04-processing-an-artifact.md); guide [execution history](../../guides/execution-history.md)

## 1. Title

How a run records who or what started it.

## 2. Context

ADR-013 allowed `user` and `system`; the integration API and MCP (ADR-016) both started runs as `system`. The
history (ADR-025) should show how an execution was started.

## 3. Decision

`started_by` is `user` (the browser), `api` (`/api/v1`), `mcp` (the MCP server) or `system` (reserved for starts the
application makes itself). The origin is passed by the entry point to `RunEngine.start` and copied to the execution.
Migration 0024 only widens the check constraint; rows written earlier keep `system`.

## 4. Consequences

- The origin is a filter in the global list and in MCP, and shown in the history.
- `system` is not produced by any code path today; an old `system` row means "not recorded", not "started by the
  application".
- The origin says which interface started the run, not which person or client: there is one token and no accounts
  (ADR-016).
