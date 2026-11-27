
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
