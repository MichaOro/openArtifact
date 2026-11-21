# ADR-013: Execution engine and pipeline runs

> **Status:** **Accepted**

## 1. Title

An execution engine that runs an artifact through a pipeline, and the run model behind it.

## 2. Context

A pipeline (ADR-012) is a definition. The next step is to run an artifact through it: from the
trigger, stage by stage and action by action, along *On Pass* / *On Error*, with a human able to
start, stop and restart at any stage.

### 2.1 Decisions

1. **One run per artifact** (`pipeline_runs`, `task_id` unique) holds the state: `status`
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
   `POST /api/tasks/{id}/run`, `POST /api/tasks/{id}/run/stop`, `GET /api/workflows/{id}/stages`.

## 3. Consequences

- Fully visible, restartable state; a second browser follows through SSE.
- The run is a single row per artifact, so there is no history of earlier runs yet.
- Only a timer is business logic so far; the other nodes of an action definition come later.
- Human-in-the-loop (a `waiting` status) and automatic starts by the system are prepared (one start
  path, `started_by`) but not built.
