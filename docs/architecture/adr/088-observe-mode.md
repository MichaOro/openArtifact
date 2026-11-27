# ADR-088: Observe mode: a pipeline whose every run is a dry run, set with a publication

**Status:** Accepted  
**Date:** 2026-11-27  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-086](086-dry-run.md) (a run can be a dry run nobody asked for by hand), [ADR-070](070-versions-of-actions-and-pipelines.md) (a version also holds the observe mode), [ADR-082](082-references-by-id-and-the-publish-check.md) (the check names a change of the mode)  
**Implemented in:** `api/observe.py`, `graph/observe_service.py`, `graph/observe_schemas.py` and `api/mcp.py` (the doors), `graph/observe.py` (the setting), `graph/observe_state.py` (the state, the admission, release and renewal), `graph/content.py` and `graph/versions.py` (the setting is part of a version), `graph/repository.py` (`set_observe`, `restore`), `graph/publishing.py` (`on_publication`), `graph/preflight.py` (`observe_on`, `observe_off`, `observe_changed`), `engine/runner.py` (`_start`, the not-observable end, the call check), `engine/context.py` (`depends_on_skipped`), `engine/history.py`, `engine/schemas.py` (`observed`), `models/` and migration `0067_observe_mode.py`  
**Affected chapters:** guides [execution nodes](../../guides/execution-nodes.md), [execution history](../../guides/execution-history.md), [API reference](../../guides/api-reference.md)

## 1. Context

A dry run (ADR-086) is one test run started by hand. A new pipeline also needs a longer trial: let it run on the real cards and the real starts (a card, the API,
an agent, another pipeline) for a while, read what it would have done in the history, and switch it to real operation only when it is trusted. The owner asked for
that as a mode of the pipeline, decided only by a publication, with an end that stops the pipeline until someone decides.

## 2. Decision

- **Two states, no "off" mode:** a pipeline is *observed* or it is not. The mode belongs to a **pipeline** only; its actions run inside it and follow it. (An action alone is
  tried with a dry run.)
- **The setting is part of the publication.** It is `{enabled, days, runs}` (`days` 1 to 365 and `runs` 1 to 100000, both optional; neither means: until it is switched
  off), kept in the config of the pipeline's Trigger under the hidden key `_observe` (like the mock of ADR-087 and the placement number of ADR-082: no setting of the
  node) and carried as `observe` on the graph (`graph_of`). It is part of every published version and of its fingerprint, so a draft that differs from the published
  version in its mode is a *changed draft*, *Discard draft* brings the published mode back, and *Publish again* (a rollback) brings an earlier mode back. **Only the
  published version is read**: a draft with the mode on, and a pipeline that was never published, run for real. The publish check (ADR-082) names a change as a warning the
  owner confirms (`observe_on`, `observe_off`, `observe_changed`): *Observe mode will be switched on with this publication ...*.
- **An observed run** is a run that starts at a pipeline whose published version has the mode on, from **any** start (the card, the API, the MCP tool, a rule or an agent):
  it is a dry run (ADR-086: what writes is skipped, a timer does not wait, the artifact is left as it is) with the flag **`observed`** (`executions`, `pipeline_runs`,
  migration 0067; every row before is not observed), shown as the flag *Observed* in the run and the execution (`observed: true` beside `dry_run: true`; the history's own
  chip and filter follow). The counters of real runs leave it out as they leave out a dry run. The mode is frozen into the snapshot of the run (`observed: true`).
  **Mocks do not apply** (ADR-087): an observed run reads the published version, which carries none. The emergency stop (ADR-076) still refuses every start.
- **A manual dry run is not observed and not counted.** It is refused by the emergency stop but not by an ended observation: it changes nothing.
- **Nested pipelines follow the outer run.** Whether a run is observed is decided once, at the start of the outermost pipeline; a called pipeline runs as that run does
  and neither reads nor counts its own mode. One thing is read at the call: a called pipeline whose observation **has ended** fails the call with the reason (the run fails
  by the pipeline node's On Fail like any failed call), so an ended observation is not walked around by calling the pipeline from another.
- **The end of an observation.** After the days or the runs of the setting (counted from the publication that set the mode, or from *observe again*) every **start is refused**
  with `409` and the code `observation_ended`: *Observation of the pipeline 'X' has ended: 5 of 5 runs were observed. Decide: observe it again or release it to run for
  real.* The pipeline stays like that, like an emergency stop for this one pipeline, until a decision. The run that reaches the limit still runs; the next start is refused.
- **The two decisions are immediate and recorded, and need no publication** (the owner may be away from the editor, and a publication round trip would keep a
  pipeline blocked): **release** (the pipeline runs for real from now on, whatever the published mode says, until a publication changes the mode) and **observe again**
  (counters from zero, from now, with the limit that is given, or the setting's). They write `graphs.observe_state` (JSON, outside every version), where the counters, the day
  the observation began, the release, a renewed limit and the last twenty decisions (`on`, `off`, `release`, `again`, who and when) live. A publication that **changes** the
  setting starts a new observation (the state is made again); a publication that keeps the same mode leaves it as it is, so editing a node does not restart the clock.
- **What cannot be observed.** A write that is skipped has no result (ADR-086). In an observed run a node that needs that result (it reads `.output`, `.exit_code` or a
  data field of the skipped node) does **not fail** and does not take On Fail: its step is recorded as passed with `data.not_observable: true` and *Not observable from here:
  node "X" was skipped ...*, and **the run ends there as done** with the note *Observed up to 'Y': from there on the run needs what a skipped step would have produced, so it
  cannot be observed any further*. (The chain of a pipeline is one path at a time, so this ends the observation of that run; what was seen before is in its steps.) A manual
  dry run keeps its error with the hint to use mock data.

- **API and MCP are a remote-maintenance interface.** `GET/PUT /api/pipelines/{ref}/observe` (and the same under `/api/v1`) read the setting and the state and set
  the **draft** (`ref`: id, slug or name); `POST .../release` and `POST .../again` are the two immediate decisions. `PUT` with `publish: true` also publishes, **only when the
  draft differs from the published version in nothing else** (otherwise `409 draft_has_other_changes` and nothing is changed): the call is the caller's consent to this one
  change, never to others. MCP has `get_observe_mode`, `set_observe_mode` (the same `publish`), `release_observe_block` and `observe_again`; none deletes. The record of a
  decision names the door (`user`, `api`, `mcp`). A start from outside is answered with `dry_run: true, observed: true`, and refused with `409 observation_ended` after the end.

## 3. Consequences

- Turning the mode on or off is a controlled step: the draft says what it will do, the publish check names it, a publication makes it true.
- An observed pipeline can look quiet when its steps depend on writes: the *not observable* end says where and why.
- An ended observation blocks the pipeline until someone releases it or observes again: that is the point, and it needs the owner, from the editor or remotely
  (see below).
- Migration 0067 only adds columns (`observed` twice, `observe_state`); it drops the guard views first and removes the leftover copy of an earlier failed start, as 0066.

## 4. Not in this decision

A mode per stage or per action, an observe mode that writes into a sandbox, and automatic release at the end (the end blocks, a person decides).
