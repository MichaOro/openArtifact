# ADR-089: A dry run needs no card, an action runs by itself, and the execution page knows where it was opened from

**Status:** Accepted  
**Date:** 2026-11-27  
**Supersedes:** the sections "A card is still needed to run" and the action's *Runs in* of [ADR-086](086-dry-run.md) addendum 2  
**Superseded by:** —  
**Amends:** [ADR-086](086-dry-run.md) (the dry run), [ADR-087](087-mock-data-for-the-dry-run.md) (the mocks of the draft apply to an action run by itself)  
**Implemented in:** `engine/snapshot.py` (`wrap_action`, `build_action_snapshot`), `engine/runner.py` (`definition_id`), `engine/flow.py` (`run_standalone`), `tasks/technical.py`, `tasks/service.py` (`start_dry_run`), `api/runs.py` and `api/v1.py` (`/graphs/{ref}/dry-run`), `api/board_tools.py` (`dry_run_graph`), migration `0068`, `static/js/editor/dry-run-panel.js`, `static/js/execution/back-link.js`  
**Affected chapters:** guides [execution nodes](../../guides/execution-nodes.md), [API reference](../../guides/api-reference.md), [UI catalog](../../guides/ui-catalog.md)

## 1. Context

The Dry run tab asked for a test card and, in an action, for the pipeline that places it. The owner's case: an action that only has an Execute Command node (`git status`)
needs no card and no pipeline. And a dry run started in an action with *Draft* ran the action's draft, then **went on into the pipeline**, which used the *published* action:
the run did not end at the action's Output. And the execution page's *Back to the board* led to the board whether the user came from an action, a pipeline, the list of executions or
a card.

## 2. Decision

- **A dry run needs no card. The smallest design: a hidden technical card per graph.** An execution belongs to a card in the engine (`executions.task_id`, its number counts per
  card, one run per card, the history page and the address `/artifacts/<number>/executions/<id>` are the card's). Two ways were weighed: a nullable `task_id` through the executions,
  the runs, the guard views, the events and every list (large, and every consumer has to learn a card-less execution), or **a card that exists but is in no list**. The second is
  chosen: `tasks.technical` (migration `0068`, a plain `ADD COLUMN`: `tasks` is not rebuilt, because executions, comments and runs point at it with `ON DELETE CASCADE`). The
  card of a graph is made when its first card-less dry run starts (`tasks/technical.py`, titled *Dry runs of <name>*, in the first lane, `pipeline_id` naming the graph), and
  used again. Its executions behave like any card's: history, flow, counters (dry runs are never counted), address.
- **It is in no list, count or rule of the board.** `visible()` (`Task.technical.is_(False)`) is added where cards are listed or counted: the board and archive lists (`TaskRepository.list_all`,
  hence the API, the integration API and the MCP tools), the number of cards, the lane counts and the guards' `lane.*` facts, the card rules and their preview, the guard view
  `v_guard_artifacts`, and the count of artifacts a graph is used by. A lane holds hidden cards without being "not empty": deleting a lane moves them to another lane. A hidden
  card is reached by its id or number only (the execution page, the history API). `tests/test_dry_run_standalone.py` fails when one shows up in a listing.
  A hidden card takes a number from the same counter as any card (numbers are never reused), so a card's number can skip when a graph is first dry-run without a card.
- **A card chosen with *+ Add* is used as before** (the run is on it, `${card...}` reads it). Without one, a reference to a card field gives its normal missing-value error.
- **An action's dry run runs the action by itself.** The engine walks pipelines; a dry run of an action walks a *wrapper* made in the snapshot (`wrap_action`): a Trigger, one stage
  holding one placement of the action, a Complete. It is never stored as a graph, its ids are derived from the action's id, and the run's `pipeline_id` is the action's own id. The
  snapshot holds the action in the version asked for (`draft` or `published`) and, for the draft, its mocks (ADR-087). So the run is the action's Trigger, its nodes and its
  **Output**, and nothing around it; no pipeline is entered and no published placement is used. The inputs come from the form (they are the values the one placement is given).
  The flow of such an execution (`flow.py`, `run_standalone`) is the action's own graph as the root, one visit, not the wrapper. A pipeline's dry run is its own graph as before; a
  pipeline that *calls* actions keeps the rule of ADR-086 addendum 2 (draft: the drafts; published: the published versions).
- **The Dry run tab:** no *Runs in*, no *Place this action...*, no lock for a missing card. It starts and checks through `POST /api/graphs/{id}/dry-run` and `.../dry-run/check`, with
  the card added with *+ Add* as `task_id` (optional), and lists the rows of that card, or of the graph's hidden card (`GET /api/graphs/{id}/dry-run-card`).
- **API and MCP:** `POST /api/graphs/{ref}/dry-run` (`ref`: id, slug or name of a pipeline or an action; body `task_id?`, `stage_id?`, `action_id?`, `inputs?`, `version?`;
  default `draft`), `POST /api/graphs/{ref}/dry-run/check`, `GET /api/graphs/{ref}/dry-run-card`; the same under `/api/v1` (start only, default `published`); MCP `dry_run_graph`
  (`artifact?`). `POST /api/tasks/{id}/run` takes `definition_id` (a dry run only: an action by itself). A real start with `definition_id` is 422.
- **The Back button knows its origin.** A link to an execution carries `?from=` with a short word of a fixed list (`back-link.js`): `board`, `executions`, `card:<number>`,
  `action:<slug>`, `pipeline:<slug>`. The page turns it into the label and target (*Back to the action <name>*, *Back to the pipeline <name>*, *Back to executions*, *Back to the card*,
  else *Back to the board*); the name is the one that ran. Nothing else is taken from the address (no URL, no path: an open redirect is not possible), and the word stays in the
  address while the user steps into a visit. The code that links says where it is: the dry run row of an editor (`from=action:...` / `pipeline:...`), the list of executions, a
  card's History tab and the links in its comments. Going back to an editor opens the editor page; the Trigger window is not reopened.

## 3. Consequences

- A dry run of an action works wherever the action is, placed or not, with or without a card; the old *Runs in* choice is gone from the tab (the placements route stays in the API).
- Hidden cards stay in the database with their executions (the retention rules and the number of executions kept per card still apply to them). A deleted graph leaves its hidden
  card behind (the foreign key clears its `pipeline_id`) with the old executions; nothing shows it.
- The title of the execution page for such a run reads *Execution #1 of #12 Dry runs of <name>*: the hidden card's number and title.

## 4. Not in this decision

An action's dry run inside a pipeline's view (that is the pipeline's dry run), a card made on the board for tests, and removing hidden cards of deleted graphs.


## Addendum 1: the inputs of the Trigger reach the prompt of an agent node

The owner declared the input `mield` on an action's Trigger, typed a value in the Dry run form and wrote `${input.mield}` in the node's User prompt. The run stopped
before the model with "`${input.mield}` is not a declared input": a prompt reads the inputs of its **agent** only (ADR-064), and this agent declared `repo`. The value
had arrived (the run context holds it while the action runs); the prompt could not see it, and the node window warned the same way.

- **The rule:** in a prompt of an agent node, `${input.NAME}` is first an input of the agent (its mapping in the node). A name the agent does not declare is read from the
  inputs of the run, that is the inputs the Trigger of the graph the node sits in declares (for an action: the ones the Dry run form or the placement fills; for a pipeline:
  its own). The agent's own input wins on a clash, so no agent changes its meaning. A name that nobody declares still stops the node before the model.
- **The check:** the node's hints and the agent preview name the Trigger's inputs too (`prompt_problems(..., graph_inputs)`): no false warning for a valid reference, and the
  warning for a wrong name says what the agent and the Trigger declare. The warning "Input X is mapped but no prompt uses it" is unchanged (it is true).
- **What stays:** nothing else of the run is readable in a prompt (`${node...}`, `${var...}`, `${secret:...}` are still refused): an agent still does not depend on the nodes of a
  pipeline, only on the declared inputs of its graph.
- **Implemented in:** `agents/render.py` (`fill`, `prompt_problems`), `agents/service.py` (`_graph_input_names`). Test: `tests/test_trigger_input_in_agent_prompt.py`.

## Addendum 2: the flow of a running dry run shows the node that works

The flow of an action's dry run (the action by itself, no pipeline around it) is replayed from the steps of the action alone. A node that works has no step of its own yet, so the
replay has to say the run is in the node the edge of the last finished step leads to, as the replay of a run through a pipeline does (`_definition` in `engine/flow.py`). It did
not, so while an agent or an HTTP node worked the flow drew it faded, no bubbles ran along the edge and the path list ended at the Trigger. `run_standalone` now adds that edge and node while
the run is `running`. A pipeline dry run and an observed run replay like any pipeline run and were not affected.
