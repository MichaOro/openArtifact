# ADR-084: Data storage: limits the user sets, a pass that does exactly what the preview shows, and shrinking

**Status:** Accepted  
**Date:** 2026-11-26  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-052](052-retention-rules-and-rule-builder.md) (the retention rules stay; limits and a pass are added around them), [ADR-066](066-modular-navigation.md) (the Personal settings page gets a section)  
**Implemented in:** `engine/storage.py` (policy, classification, plan, pass, shrink, `Cleaner`), `engine/runner.py` (the limits a step stores, frozen at the start), `engine/history.py` (`prune` reads the user's number), `api/settings.py` (`/settings/storage`), `api/mcp.py` (two read tools), `ui/forms/personal.yaml`, `static/js/settings/storage-panel.js`  
**Affected chapters:** guides [operations](../../guides/operations.md), [execution history](../../guides/execution-history.md), [API reference](../../guides/api-reference.md)

## 1. Context

Executions keep a frozen snapshot, every step with its output (up to 256 KiB, 1 MiB per execution) and its details (an agent's prompts and attempts)
and the run context. Retention (ADR-052) deletes whole executions by rules, and the operator's guard keeps the newest 50 per artifact. There was no way to
limit what is *stored*, to empty the heavy text of old executions while keeping their summary, to see how large the database is, or to give space back
on demand. The owner's principle: **what a user can see or fetch (the interface, the API, MCP) is removed only by rules and limits the user knows and has
set; only purely technical data, which nobody can reach, may be cleaned without asking.** The application does not decide for the user how long data lives.

## 2. Decision

- **Where the limits live:** a section *Data storage* in Settings, Personal (form manifest `personal.yaml`, values saved when the typing pauses). Seven
  settings, **all empty by default, and empty changes nothing**: `storage_keep_executions` (empty: the operator's `OPENARTIFACT_EXECUTION_HISTORY_DEFAULT_KEEP`,
  `0` keeps all), `storage_step_data_days`, `storage_run_data_mib`, `storage_step_output_kib` (at most today's 256 KiB), `storage_run_output_kib` (at most
  today's 1024 KiB), `storage_clean_interval_hours`, `storage_warn_mib`. The names are prefixed so they can be split between personal and global later.
  The retention rules stay under Executions, Retention; the section points to them.
- **What is visible and what is technical** (decided from the code, enforced by a test that fails when a new table is in neither list):
  *Visible* (UI, API or MCP reach it): `agents`, `agent_versions`, `app_settings`, `artifact_fields`, `credentials` (and `external_credentials`,
  `internal_credentials`), `credential_events` (the history of a credential), `internal_tokens` (listed on the credentials page), `secrets` (the names),
  `executions`, `pipeline_runs`, `run_stages`, `run_node_results` (the steps), `graphs`, `graph_nodes`, `graph_edges`, `graph_versions`, `guard_definitions`,
  `guard_attachments`, `guard_versions`, `lanes`, `llm_providers`, `llm_models`, `tasks`, `task_comments`, `task_activity`. *Technical*: `alembic_version` and
  `task_number_seq` (one row each, nothing grows), the write-ahead log file and free pages of the database file.
  The only technical data that grows is therefore the log and the free pages; the pass deals with them (see below). **Visible data is removed only by the
  user's limits and rules. Cards, comments and the activity are never removed by any of this.**
- **One plan is the preview and the pass.** `plan()` computes, for the user's policy: (1) executions beyond the number kept per artifact (the newest and a
  running one never), (2) executions a retention rule matches, (3) the **step data** (outputs and details of the steps, and the run context) of finished
  executions older than N days, (4) the same for the oldest finished executions until the data of all executions fits the size limit. The preview shows the
  categories with entries and bytes; `clean()` carries out exactly that plan, then truncates the log. A step whose data was emptied keeps its row and its
  result and says so in `data.data_pruned`; the execution keeps its number, status, snapshot (the flow can still be drawn) and step count. A running execution is
  never touched. The retention rules are still applied when an execution starts or ends, and the number kept is applied there too (it reads the user's setting).
- **What a step stores:** the user's lower limits freeze into the snapshot of an execution at its start (like the run limits, an execution keeps the ones it
  started with). An output longer than the step limit is cut with the existing marker and `data.output_truncated`; every long text inside the *details* of a step
  (prompts, tool results) is cut too, marked `[truncated: N characters left out]`, and `data.detail_truncated` counts them. The user's limit never exceeds the hard one.
- **The cleaner:** `Cleaner` runs a pass when *Clean automatically every N hours* has passed (checked every minute); empty is off, **Clean now is always
  available**. It deletes only what the policy hits and nothing else; every pass logs one line (counts and bytes, never content) and publishes `storage.cleaned`.
  One pass at a time (`409 busy`).
- **Shrinking:** after every pass the write-ahead log is truncated (`PRAGMA wal_checkpoint(TRUNCATE)`; `truncated: false` when a reader holds it, tried again at
  the next pass). `auto_vacuum = FULL` already returns freed pages. *Shrink database* is a deliberate action (`VACUUM`): it needs about as much free disk space as
  the file and the log take and holds the database for a moment, so it is refused (`409 not_enough_space`) when the disk has less, and the page asks first and
  advises a backup. The section shows the file size, the log size, the free pages, the biggest tables (`dbstat` when the SQLite build has it, else row counts),
  the data of all executions and the last pass; a warning appears when the file is larger than `storage_warn_mib`.
- **API and MCP:** `GET /api/settings/storage` (and under `/api/v1`) the numbers; `POST .../preview`, `.../clean`, `.../shrink`. MCP has two **read** tools
  (`get_storage_status`, `preview_storage_cleanup`); **no MCP tool cleans, shrinks or deletes**.

## 3. Consequences

- A user who never opens the section gets exactly today's behaviour; one who sets a limit sees what it does before it does it.
- Emptying step data loses the outputs of old steps for good (the summary stays): that is why it is a limit the user sets, with a preview and a question.
- The step data of an execution that was emptied shows empty outputs in the history; `data.data_pruned` explains it.
- The size limit counts outputs, details and contexts of all executions, not the snapshots (they are needed to draw the flow).
- The classification list has to be kept up to date: a new table must be put in `VISIBLE_TABLES` or `TECHNICAL_TABLES` (a test enforces it).

## 4. Not in this decision

The event log written *during* a run (its own card), a separate SQLite file (not needed), deleting cards, comments or their history, and any MCP tool that deletes.

## Addendum 1: the page in tabs, defaults as values, switches (card #100)

The first page was one long form, a card with seven empty number fields, and the panel of the database below it; its fieldset was wider than its card and lay over the edge.
The owner asked for sub-navigation like the agent page, default values instead of empty fields, and a way to switch the cleaner on. The data, the API and the engine of this ADR are unchanged.

- **Tabs:** *Settings → Personal* has *General* (display, the emergency stop), *Data storage* (the limits) and *Database* (the facts and the three actions). The shared `Tabs`
  component switches them; the tab is kept in the address (`#general`, `#storage`, `#database`), so a reload and a link open the same one. The form manifest `personal.yaml` names the
  tab of each section (`tab:` on a section, a new optional key); the page draws one `FormView` per tab over the same values. The cards are content-sized, one column, and the form
  fills its card (nothing lies over another element or leaves the card: a browser test measures the boxes at 1280 and 390 px).
- **Defaults are values:** a field nobody set shows what the engine does anyway: the operator's number of executions per artifact (`context.defaults` from `GET /api/settings/storage`),
  256 KiB and 1024 KiB for the longest stored output of a step and of an execution. Typing the default back stores `null` ("not set"), not the number, so a later change of the default
  (the operator's number, today's limits) still applies; "Reset to default" appears while another number is stored. The widget is `limit`.
- **A limit that is off by default is a switch:** *Empty step outputs after*, *Limit for the data of all executions*, *Clean automatically* and *Warn when the database is larger than* are
  `optional-number` widgets: a switch (off by default) and, once it is on, the number with its unit, starting with a suggestion (`on_values`: 30 days, 1024 MiB, every 24 hours, 1024 MiB).
  Switching on stores the suggestion, switching off stores `null`; both are saved at once, a typed number when the typing has paused. Storage stays what it was: `null` is "not set"
  (the operator's value, today's limit, or off).
- **The cleaner has its switch:** *Clean automatically* with *every N hours* (24 on first switching on). The *Database* tab says whether it is on, the interval and when it runs next
  (`next_clean_at`: the last pass, or the start of the application, plus the interval) and links to the setting.
- **The *Database* tab:** the facts as a two-column list, the biggest tables with their sizes on the right, and *Preview*, *Clean now* and *Shrink database* in a row with a line under each
  saying what it does. The messages (nothing to clean, what a pass did) and the questions before cleaning and shrinking are as before.
- **API:** `GET /api/settings/storage` gains `next_clean_at`, `defaults` and `on_values`. Nothing else changes.
