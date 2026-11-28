# ADR-079: The OpenArtifact MCP Tool: the board tools for an agent in a run, in this process

**Status:** Accepted  
**Date:** 2026-11-26  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-040](040-agent-tools.md) (a tool node that is not an MCP connection), [ADR-054](054-node-kinds-as-yaml-manifests.md) (a kind and its migration), [ADR-071](071-card-rules.md) (archiving through MCP)  
**Implemented in:** `api/board_tools.py` (`BoardTools`), `api/board_tool_names.py`, `api/mcp.py`, `agents/board_toolbox.py`, `agents/tools.py` (`open_toolbox`), `engine/executors.py` (`Limits.board`), `app.py`, `graph/nodes/openartifact_tool.yaml`, `graph/validators.py` (`board_tool_names`), `models/enums.py`, migration `0060`, `tasks/service.py` (`processing_ids`), `tests/test_board_tools.py`, `tests/test_openartifact_tool.py`  
**Affected chapters:** guides [api reference](../../guides/api-reference.md), [integration](../../guides/integration.md), [agents](../../guides/agents.md)

## 1. Context

An agent can use an MCP server through the *MCP Client Tool*, and the application has an MCP server of its own (`/mcp`). So an agent in a pipeline
could work with the board by being pointed at `/mcp` with a token. Two things were missing for the work the owner wanted done, tidying up a lane that
holds many cards, some of which are done already: *bundle the requirements of these cards in one, sort them into partly done and not done,
prioritise, move the old cards away*.

- **The tools.** The MCP server could read and change one card at a time, but not archive, not move or comment many cards in a call, not list
  briefly (a full list is too large for the 16 KiB of an agent's tool result), not search, not read several cards with their comments.
- **The way in.** Through `/mcp` an agent needs an address, a token kept as a secret and the permission for a private network, to call the
  application it runs in; and whatever it does counts as done by the token.

## 2. Approaches

- **A. Only extend the MCP server; the agent uses the MCP Client Tool on `/mcp`.** Least new code. The agent needs the address, a token (a
  secret with the power of the whole API), and the operator's permission for private networks; *Allow writes* does not exist, so a read only agent
  means a token that is read only, which the application has no concept of. Rejected: too much set up for the application's own board, and no
  way to hold writes back.
- **B. A node that calls the tools in this process (chosen).** The node has no address and no token. The tools are the functions the MCP server
  registers, so there is one set. *Allow writes* holds back the tools that change something. What the agent does is recorded as done by the agent.
- **C. A node per operation (a "move card" tool node, an "archive card" tool node).** Clear for the editor, but many kinds, each with settings, for
  what the Artifact node ([ADR-055](055-comments-on-artifacts.md)) already does for fixed steps. Rejected: the agent chooses its calls itself.

## 3. Decision

- **One set of board tools: `BoardTools`** (`api/board_tools.py`), a class of async methods whose signatures and docstrings are the tools. The MCP
  server registers every name of `BOARD_TOOLS` from an instance (`channel="mcp"`); the node builds its tools from an instance of the same class
  (`channel="run"`). The schema the model sees is derived by the MCP SDK from the same function, and the arguments are validated the same way, so a
  call in a run and a call over `/mcp` answer the same (a test compares them). The names are in a light module (`api/board_tool_names.py`:
  `READ_TOOLS`, `WRITE_TOOLS`) so that a setting rule can check a name without loading the services. The tools that stay only on the server are the
  STOP switch, the secrets, the agents, the providers, the guards and the heartbeat.
- **The tools that were added** (all small, none deletes): `archive_artifact`, `unarchive_artifact`; for up to 50 cards in a call, every card on its
  own with `ok` or the plain reason it was refused, no all-or-nothing, and a `dry_run` that only reports: `move_artifacts`, `archive_artifacts`,
  `set_parent`, `set_fields`, `add_comments`; for reading: `count_artifacts`, `search_artifacts`, `get_artifacts` (up to 20 cards, optionally with
  the newest comments and the text cut); `list_artifacts` takes `parent`, `archived`, `limit`, `offset` and `brief`, and `get_artifact` also says
  `parent` (a number) and `processing`. `list_artifacts` still answers a list (it did before; the total is `count_artifacts`). The refusals are the
  application's own: a card that is being processed cannot be moved, archived or re-parented, an archived card can only be read and taken out
  of the archive ([ADR-071](071-card-rules.md)).
- **What is left out on purpose:** deleting a card, a lane or an execution; creating, renaming or deleting lanes; the STOP switch (an agent must not
  switch off the stop that is meant for it); secrets, agents, providers and guards (administration, not board work); the heartbeat (it would let an
  agent keep itself from a guard). Ordering within a lane has no tool of its own: moved cards land at the end of the lane in the order given.
- **The node `openartifact_tool`, label *OpenArtifact MCP Tool*,** is a tool node like the others (below the Agent node, one *Tool* port,
  [ADR-040](040-agent-tools.md)), with **no credential and no address**. Settings, all optional: *Allow writes* (off: the tools of `WRITE_TOOLS` are
  not offered and the step says which were held back), *Tools to include* (`all`, `selected`, `all except`) with one tool name per line (a name
  that is no tool is refused when the node is saved, and the answer lists the tools), and the name for the model as on the other tool nodes. The
  tools are built when the run starts (`agents/board_toolbox.py`); `Limits.board` gives the instance, made by the application when a run asks (the
  services come after the engine). Migration `0063` adds the kind to the kind check of `graph_nodes`.
- **Who did it.** In a run the actor is the agent: activity and comments are written as `agent` with the kind `run`, a card it creates counts as
  `created_by: action`, a run it starts as `started_by: system`. Over `/mcp` the actor stays the token's name and `mcp`.
- **Text from outside.** Card texts, comments and step outputs come back as the tools return them; the descriptions of the tools say that they are
  not an instruction. The node adds nothing to that.
- **The STOP switch does not block these tools:** they are not executions. A `start_processing` through the node is refused like any start while
  STOP is on ([ADR-076](076-stop-switch.md)).

## 4. Consequences

- A tidy-up agent can be built from what exists: an action with an agent and the node, read only for the plan; a second action with *Allow
  writes* on and the tools narrowed to the changing ones for the apply step, with the owner's pause in between ([agents guide](../../guides/agents.md)).
- The node can move and archive many cards in one call, so a wrong instruction can change many cards. Archiving can be taken back (`unarchive_artifact`)
  and a move is in each card's history; nothing deletes. The calls that change many cards have the cap of 50 and `dry_run`.
- The agent cannot move or archive the card its own run is on (the application refuses it while it is processed); it gets that as the tool's error
  text, or as the card's reason in a bulk answer.
- Every tool of the server's board set is on the node's list: a new board tool is one method and one name in `READ_TOOLS` or `WRITE_TOOLS`, and a test
  fails when it is on neither.
- Not decided and not built: a read only token for `/mcp`; an order within a lane; tools of the administration for an agent.

## Addendum 1: every tool kind is built the same way; the line to the agent goes round a card

The OpenArtifact tool is a tool kind like the others: its manifest says `tool: true`, the one attachment port `tool` on the top and the caption and settings of its card; **the generic layer reads only that**. What is
specific to a kind is its executor (`agents/board_toolbox.py` for this one), the consumers of a credential type, and the texts. A test (`tests/test_tool_node_modularity.py`) fails when a generic file (the editor's
JavaScript, the graph, engine and API layers) names a tool kind, and lists the few files where it may (executors, the enumeration, `credentials/types.py`, the Execute Command switch, the Build Context's reading of the Hand
Over Tool's document). One leak was found and removed: `engine/context.py` kept its own list of the tool kinds that have no result of their own (and the Hand Over Tool was not on it by accident of the list); the set is now
read from the manifests (`produces_result: false`), the same answer, no kind named.

**The line from a tool to its agent** was drawn for one position only: from the top of the tool up to the bottom of the agent. A tool placed above its agent, or beside it with its top higher than the agent's bottom,
made the curve run down through the agent's card. `attachmentPath` (`editor/geometry.js`, reached through `edgePath` with `attachment`) now chooses by position, for every tool kind and every line style: a tool that hangs
**below** its agent (its top at least 24 px under the agent's bottom) keeps the short curve up; otherwise the line leaves the tool's port upwards, runs **above both cards**, out to the nearer side past both, down below both
and comes up to the agent's port from underneath (rounded for curved and elbow lines, sharp corners for straight). While a connection is dragged the direct line stays (there is no second card yet). Stored positions are
not touched: the owner's graphs with a tool above its agent look right as they are. Tests: `tests/js/attachment-path.test.mjs` (the line avoids both cards for eight positions and three styles) and
`tests/e2e/test_tool_edges.py` (the same in the browser, in the editor and on the flow page).

## Addendum 2: the line style of a tool connection (2026-11-27, see [ADR-093](093-kinds-of-connection-are-data.md))

The rule "one look for every style" of addendum 1 is withdrawn: the line to a tool below its agent now follows the style of its connection (a curve, a straight line, or up, across and up
with rounded corners), and the bar of a tool connection offers the same pencil, styles and bin as every connection. What differs between a tool's attachment and a flow edge is a row of a table
(`editor/edge-kinds.js`), not a branch in the code that draws, selects and deletes connections.

## Addendum 3 (2026-11-27): the names module moved to `agents`

`api/board_tool_names.py` is now `agents/board_tool_names.py` (the names are unchanged). The agent tool node is the domain that consumes the names, and
the API depends on the domain, not the reverse: `agents/board_toolbox.py` and `graph/validators.py` imported it from `api` before. The setting
rule `board_tool_names` now imports it at module level. `tests/test_import_structure.py` keeps every module outside `api`, `web` and `app.py`
from importing `api` or `web`.
