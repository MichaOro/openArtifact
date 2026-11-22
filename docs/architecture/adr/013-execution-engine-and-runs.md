# ADR-013: Execution engine and pipeline runs

**Status:** Accepted  
**Date:** 2026-11-21  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** —  
**Amended by:** [ADR-015](015-vocabulary-and-storage-names.md) (vocabulary), [ADR-018](018-typed-runs-one-error-one-persistence-rule.md) (run model, atomic start)

## 1. Title

An execution engine that runs an artifact through a pipeline, and the run model behind it.

## 2. Context

A pipeline (ADR-012) is a definition. The next step is to run an artifact through it: from the
trigger, stage by stage and action by action, along *On Pass* / *On Error*, with a human able to
start, stop and restart at any stage.

### 2.1 Decisions

1. **One run per artifact** (`pipeline_runs`, `task_id` unique) holds the state: `pipeline_id` is the pipeline the run started in (renamed from `workflow_id`, ADR-015); `status`
   (`running`, `stopped`, `done`, `failed`), the current stage and action, a `note`, who started it
   (`started_by`: `user` or `system`) and a **snapshot** of the pipeline and the action definitions
   it uses. Editing a pipeline does not change a run in flight.
2. **Stage status per run** (`run_stages`: `pending`, `running`, `passed`, `failed`, `skipped`).
   Starting at a later stage marks the earlier ones `passed` if the artifact had passed them, else
   `skipped`; both count as done. Starting at an earlier stage again is allowed. This is the "jump".
3. **Order.** Every output has one edge, so trigger → stage → stage → complete is a chain
   (`engine/chain.py`); stages off that path are not part of the pipeline.
4. **Execution** (`engine/runner.py`): a background `asyncio` task per running artifact. The step is
   saved and published as `run.updated` (SSE) before and after it. An action runs its definition
   from its trigger; a timer sleeps; the output's `pass` / `fail` connector decides *On Pass* or
   *On Error*. An action without a definition is an empty shell and passes at once. A missing
   connection (On Pass of an action, On Error of a failed one, a definition without a way to its
   output) fails the run with a note; a pipeline that does not end after 1000 steps fails.
5. **Start and stop** are one code path for user and system (`RunEngine.start(..., started_by)`).
   While a run is `running` the server answers 409 to changes of lane, order and parent and to
   deleting the artifact; the UI shows these as read-only. Title and body stay editable. Stop
   cancels the task and keeps the stage and action, so the artifact can be started again there.
6. **Restart of the container**: a run that was `running` is set to `stopped` with the note
   "interrupted"; it does not continue by itself.
7. **UI**: the artifact dialog's rail has Pipeline, Stage and Action (defaults: the only pipeline,
   its first stage and that stage's first action); one button, *Start processing* or *Stop
   processing*, sits at the left of the reading view's footer, level with Close and Edit; the card shows the stage and state. `GET /api/runs`,
   `POST /api/tasks/{id}/run`, `POST /api/tasks/{id}/run/stop`, `GET /api/pipelines/{id}/stages`.

### 2.2 Pipeline nodes (sub-pipelines)

A node of kind `pipeline` (migration 0018) sits in the chain like a stage, with an input and an
output, added through the "+" menu of the pipeline editor. Its `definition_id` names the pipeline it
calls. Running it runs that pipeline up to its *Complete*, then the calling pipeline goes on; every
pipeline keeps its Complete as its defined end. The call is part of the same run: the snapshot holds
the called pipelines (nested up to five deep) and their action definitions. The node is one entry in
the artifact's stage list (named after the called pipeline, started as a whole, no action to choose);
inside the called pipeline the run shows the stage and action that are current. If the called pipeline
cannot go on, or none is chosen, the run fails at the node. The artifact follows the flow: its Pipeline, Stage and Action fields show where the run is, so they switch into the called pipeline and back, and a finished run rests where it ended (the last stage and action that ran, even inside a called pipeline). To start again, `resume_stage_id` / `resume_action_id` name the entry of the artifact's own pipeline (the calling node if the run is inside a called one); a finished run starts again at the first stage. A pipeline cannot call itself, not even
through others (refused when linking, 422); the step limit also counts across nested pipelines.

## 3. Consequences

- Fully visible, restartable state; a second browser follows through SSE.
- The run is a single row per artifact, so there is no history of earlier runs yet.
- Only a timer is business logic so far; the other nodes of an action definition come later.
- Human-in-the-loop (a `waiting` status) and automatic starts by the system are prepared (one start
  path, `started_by`) but not built.

## 4. Planned (not built)

- **Executions.** Today an artifact has one run row; starting again overwrites it. Planned: a run per
  start, shown on the artifact as a tab ("Executions") next to the reading view, with the stages and
  actions each run went through, including the nested pipelines of pipeline nodes.
- **Settings and loop protection.** A *Settings* area. The only protection against endless loops
  is a fixed limit of 1000 steps per run (an *On Error* routed back to its own action loops for
  ever until then). A global protection (limits, behaviour on reaching them, a warning when a
  definition can loop) is to be designed there.
- **Human-in-the-loop** (a `waiting` status) and **automatic starts** of sub-artifacts by the system.

## 5. Update (2026-11-22): atomic start and limits

The decisions above stand; [ADR-018](018-typed-runs-one-error-one-persistence-rule.md) adds how a start is made safe.

- **Atomic start.** `RunEngine` claims an artifact before its first `await` (an in-process set), then changes the
  artifact with a conditional `UPDATE`, and inserts the run row with `INSERT ... ON CONFLICT DO NOTHING` on
  `pipeline_runs.task_id`. A lost race answers `409`; stopping while a start is in progress answers `409` too.
- **Run cap.** At most `OPENARTIFACT_MAX_CONCURRENT_RUNS` (default 8) runs are active; another start answers `429`.
- **Steps** are counted across the pipeline and action loops together (1000, nesting up to 5), so a loop inside an action
  cannot escape the limit.
- **Events.** Starting an artifact in a pipeline publishes `task.updated` (the fresh artifact) in addition to
  `run.updated` when its pipeline, stage or action changed. Event streams are capped by
  `OPENARTIFACT_MAX_SSE_SUBSCRIBERS` (default 50, `503`).
- **Typed run.** `RunRead` / `RunStageRead` (`engine/schemas.py`) describe a run everywhere it is returned
  (`/api/runs`, `POST .../run`, `/api/v1/artifacts/{ref}/run`, the `run.updated` event); `updated_at` is ISO-8601 UTC
  with a `Z` suffix.
- **Not built:** no wall-clock deadline per run or per node (only the step limit and the timer's bound of one day),
  see arc42 chapter 11.
