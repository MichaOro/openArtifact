# ADR-086: The dry run: a run under real conditions that skips what writes, with every node declaring its effect

**Status:** Accepted  
**Date:** 2026-11-26  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-054](054-node-kinds-as-yaml-manifests.md) (the manifest gets an `effect` block), [ADR-070](070-versions-of-actions-and-pipelines.md) (a run may take the draft), [ADR-076](076-stop-switch.md) (the stop also blocks a dry run)  
**Amended by:** —  
**Implemented in:** `graph/effects.py`, `graph/manifest.py` (`EffectSpec`), `graph/nodes/*.yaml` (`effect:`), `engine/dry_run.py` (the skipped step), `engine/runner.py` (`start`, `_entry_inputs`, the skip), `engine/context.py` (`bind_given`, the missing-result rule, `RunView.dry_run`), `engine/executors.py` (the timer, the agent), `engine/snapshot.py` and `graph/publishing.py` (`draft`), `agents/tools.py` (`Tool.writes`), `agents/local_tools.py`, `agents/mcp_client.py`, `agents/board_toolbox.py`, `engine/history_query.py` (filter and counters), `engine/guard_views.py`, migration `0066_dry_run.py`, `static/js/executions/`  
**Affected chapters:** guides [execution nodes](../../guides/execution-nodes.md), [execution history](../../guides/execution-history.md), [api reference](../../guides/api-reference.md)

## 1. Context

A pipeline that writes (comments, HTTP calls, scripts, GitHub, Postgres) cannot be tried without doing what it does. Authors need a test run that follows the
real conditions (the branches, the inputs, the reads) but changes nothing, and they need to know which nodes would have changed something.

## 2. Decision

- **Every node kind declares its effect** in its manifest (`effect:`): `none` (it only decides or shapes data), `read`, `write`, or `mixed` (only the Agent and the tool
  kinds whose tools decide). The declaration may follow a setting (`setting` and the values that `reading` lists: the HTTP method, the operation of GitHub and of the
  Artifact node) or a switch (`flag` and `flag_true`: Postgres *Allow changes*, Execute Command *Read only*, the tools' write switches). **What is not declared, an
  unknown value and an unknown kind count as writing.** Execute Command is writing unless its new setting *Read only* is ticked.
- **A run has a persisted `dry_run` flag** (`pipeline_runs`, `executions`; migration 0066, existing rows are real runs). The engine decides per step: a node whose effect is
  `write` is not executed; its step is recorded as passed with `reason` and `data` (`dry_run: true`, `would_have`) saying what it would have done. Its inputs are
  still resolved first, so a wrong reference fails as it would for real. Nodes that read or decide run as always: conditions, branches, reads and calls of called pipelines
  are real.
- **A skipped node has no result.** What it leaves is the fact that it was skipped (`success`, `data.dry_run`, `data.would_have`). A later node that asks for something it
  would have produced (`.output`, `.exit_code`, another `data` field) fails with a message naming the node and pointing at mock data (card #140) instead of working with
  an invented value.
- **Timers do not wait.** The step passes at once and records the wait it skipped (`skipped_seconds`). **Guards take part**: their actions and views see the same flag
  (`v_guard_runs.dry_run`). **An agent runs**, but the tools it calls that change something are answered with "Dry run: ... was not executed", as a normal answer, so the
  model goes on. A tool counts as changing by the same declaration (MCP tools by the server's `readOnlyHint`; a tool that is not announced as read only is changing).
- **The emergency stop blocks a dry run** like any start (ADR-076).
- **The version:** `version` is `draft` or `published`. The editor's start defaults to the draft (it tests what is being edited), the Integration API and the MCP tool to the
  published version. The snapshot of the run is built from that version for the pipeline and everything it calls. `inputs` and `version` without `dry_run` are 422.
- **Inputs:** with an `action_id` the values are for the declared inputs of that action's Trigger (checked like a mapping, ADR-083, used once); without it they are for the
  pipeline's own Trigger. The values are taken as text: they are **never read for `${...}`** (`bind_given`), so a value cannot reach a secret.
- **The artifact stays as it is.** A dry run does not move the artifact's pipeline, stage and action, and its stage states do not count when a real run starts later.
  Execution numbers continue; retention treats a dry run like any execution.
- **History:** `dry_run` is in the list and the detail, the rows show a chip (*Dry run*, *Testlauf*), the list filters by `dry_run=only|exclude`, and the counters
  *failed* and *done in 24 hours* count real runs only (a dry run is no failure of a pipeline); *running* and *total* count every execution.

## 3. Consequences

- A new node kind has to declare its effect or it is skipped in every dry run (the safe side); the manifest test checks the declaration.
- A step of a dry run proves the conditions and the reads, not the result of a write; the missing-result rule makes that visible instead of hiding it.
- Not decided here: the *Dry run* tab of the editor's Trigger window (the next card) and mock data for skipped nodes (card #140).
