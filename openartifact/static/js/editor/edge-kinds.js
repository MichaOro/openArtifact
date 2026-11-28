/* The kinds of connection, as data (ADR-093). Every connection on the canvas is one `GraphEdge` drawn, selected, restyled, deleted and pasted by the
 * same code; a KIND differs only by what this table says: how its line is routed (`route`: a builder of geometry.js), whether it ends in an arrow, which
 * line styles it offers, whether its source hangs on its target (it is copied with it and does not take part in the levelling of ports), how the flow page
 * decorates it. A function that needs to know the kind asks `kindOfEdge` for this row and reads a PROPERTY; it never compares with a kind's name. Another
 * kind of connection (a later specialisation) is one more row here and one more route in geometry.js. No file outside this one writes the port names of the
 * tool attachment: `tests/test_edge_kinds.py` fails when one does. */

/** The port a tool leaves from (the top of the tool) and the port it arrives at (the bottom of its agent). */
export const ATTACHMENT_SOURCE_PORT = "tool";
export const ATTACHMENT_TARGET_PORT = "tools";

export const LINE_STYLES = ["curved", "straight", "elbow"];

export const EDGE_KINDS = {
  /** Output to input along the flow: an arrow at the end, the colour of the port it leaves from. */
  flow: {
    route: "forward",
    arrow: true,
    styles: LINE_STYLES,
    hangs: false,
    levelsPorts: true,
    flowDecoration: "order",
    cssName: (edge) => edge.source_port,
  },
  /** A tool hangs below its agent: dashed, no arrow, the same styles; it belongs to the agent (copied with it, not levelled with the stage ports). */
  attachment: {
    route: "hang",
    arrow: false,
    styles: LINE_STYLES,
    hangs: true,
    levelsPorts: false,
    flowDecoration: "tool",
    cssName: () => "attachment",
  },
};

/** The name of the kind of connection a pair of ports makes. */
export function kindNameOfPorts(sourcePort, targetPort) {
  return sourcePort === ATTACHMENT_SOURCE_PORT || targetPort === ATTACHMENT_TARGET_PORT ? "attachment" : "flow";
}

/** The kind (a row of the table) of an edge. */
export function kindOfEdge(edge) {
  return EDGE_KINDS[kindNameOfPorts(edge.source_port, edge.target_port)];
}

/** The kind of a connection being dragged from `port` (either end of it). */
export function kindOfPort(port) {
  return EDGE_KINDS[kindNameOfPorts(port, port)];
}

/** The ends of a tool's attachment to an agent: the fields of a new edge. */
export function attachmentLink(toolId, agentId) {
  return { source_id: toolId, source_port: ATTACHMENT_SOURCE_PORT, target_id: agentId, target_port: ATTACHMENT_TARGET_PORT };
}

/** Is `port` the port a tool attaches to? (the connection rules ask this, not the name) */
export function isAttachmentTarget(port) {
  return port === ATTACHMENT_TARGET_PORT;
}
