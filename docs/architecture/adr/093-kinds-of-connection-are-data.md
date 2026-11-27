# ADR-093: One pipeline for every connection: the kinds of connection are data

**Status:** Accepted  
**Date:** 2026-11-27  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-079](079-openartifact-mcp-tool.md) addendum 1 (the line from a tool to its agent: it now follows the line style of the connection), [ADR-040](040-agent-tools.md) (the attachment of a tool)  
**Implemented in:** `static/js/editor/edge-kinds.js` (the table), `editor/geometry.js` (`edgePath` takes a kind, `attachmentPath`), `editor/canvas.js` (drawing, the bar of a connection, the preview, the levelling), `editor/clipboard.js`, `editor/editor.js`, `editor/connect-plan.js`, `editor/node-types.js`, `execution/flow-view.js`  
**Affected chapters:** guides [UI catalog](../../guides/ui-catalog.md)

## 1. Context

The line from a tool to its agent (the dashed line to the agent's *Tools* port) looked like a connection of its own: hovering it showed a bin but no pencil, so the
owner could not choose *Curved*, *Straight* or *Elbow* as on every other connection, and he suspected a second, special implementation. An audit of the code found
the suspicion half right. There is **one** entity (a `graph_edges` row; a tool connection is an edge from the tool's port `tool` to the agent's port `tools`, with a
`style` column like any edge, restyled by the same route), **one** renderer (`Canvas.drawEdges`), **one** bar and **one** deletion. What was special was a handful of
places that each tested `edge.target_port === "tools"` and did something else for it: no arrow and a dashed class, **no pencil** (the bar hid it), no line style (the
short line was always a curve), no levelling with the stage ports, the copy that remembers the agent, the flow page's decoration. Each of them was a branch in
common code, so a new feature for connections (a line style, a label) had to be added twice or would silently skip the tool connection.

## 2. Decision

- **A kind of connection is a row of a table** (`editor/edge-kinds.js`), and the common code reads a **property** of the row, never the kind's name:
  `route` (which path builder of `geometry.js` draws it: `forward`, `hang`), `arrow` (an arrow at the end or none), `styles` (the line styles its bar offers),
  `hangs` (its source hangs on its target: it is copied with it and the new copy attaches again), `levelsPorts` (it takes part in the levelling of ports while a stage is
  moved), `flowDecoration` (how the flow page decorates it: the order number of a flow edge, the use of a tool), `cssName`. `kindOfEdge(edge)` finds the row from the
  ports of the edge, `kindOfPort(port)` for a connection being dragged.
- **The tool connection gets what every connection has:** the same bar (pencil, the three styles, the bin), the style stored on the edge, drawn in all three styles.
  The line of a tool **below** its agent is a curve, a straight line, or up, across and up with rounded corners; a tool above or beside its agent still goes round the
  cards (the rule of [ADR-079](079-openartifact-mcp-tool.md) addendum 1: it never runs through a card), sharp corners for *Straight*, rounded for the other two.
- **The ports of the attachment are written once** (`ATTACHMENT_SOURCE_PORT`, `ATTACHMENT_TARGET_PORT`, `attachmentLink`, `isAttachmentTarget`). No other file of the
  editor or the flow page names them or a kind.
- **It is enforced:** `tests/test_edge_kinds.py` fails when a file of `static/js/editor` or `static/js/execution` outside the table writes `"tools"`, `"attachment"` or
  `"flow"` or compares a port name of an edge, and `tests/js/edge-kinds.test.mjs` checks that every row declares every field and that the bar offers exactly the styles of
  the kind.

## 3. How to add a kind of connection

One row in `EDGE_KINDS`, one builder in `geometry.js` if the line needs a new route (`route`), the ports in `kindNameOfPorts`. The bar, the styles, deleting, drawing, the
flow page and the copy follow from the row; a function that has to behave differently reads a new field of the row (add the field to every row and to the test).

## 4. Consequences

- A function added to connections later (a label, a colour, a different marker, a new line style) applies to the tool connection, and to any later kind, without a second
  place to change.
- The styles of a tool connection are now stored and drawn; the earlier rule "one look for every style" (a test of ADR-079) is replaced by this decision.
- There is no undo for connections in the canvas, so none was added.
- Not changed: the engine and the API treat a tool attachment as the edge it is; the flow page decorates a walked tool connection in the chosen style (the same path).
