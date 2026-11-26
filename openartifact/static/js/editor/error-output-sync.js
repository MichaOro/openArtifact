/* The error output of an action is one state of its definition and its uses (ADR-061 addendum). The server keeps them in
 * step and answers a change with `notices` (what it did beyond the node) and `reload` (other nodes of this graph changed
 * too); `graph.changed` announces the OTHER graphs it touched. This module turns the notices into short messages and
 * lets an open editor follow the changes of another tab. */
import { connectEvents } from "../tasks/events.js";
import { plural } from "../i18n.js";

/** "Flow › Stage 1 › Action": where something happened, as the server named it. */
export function placeText(place) {
  return [place.graph, place.stage, place.node].filter(Boolean).join(" › ");
}

/** The messages for the notices of one answer, in the language of the page. */
export function noticeMessages(notices = []) {
  const out = [];
  for (const notice of notices) {
    if (notice.kind === "definition_on") out.push(plural("editor.sync.definition_on", notice.uses, { definition: notice.definition }));
    else if (notice.kind === "definition_stays_on") out.push(plural("editor.sync.definition_stays_on", notice.uses, { definition: notice.definition }));
    else if (notice.kind === "disconnected") out.push(plural("editor.sync.disconnected", notice.count, { places: (notice.places ?? []).map(placeText).join("; ") }));
  }
  return out;
}

/** One line for the alert bar ("" when the answer has no notice). */
export function noticeText(notices) {
  return noticeMessages(notices).join(" ");
}

/** Whether an answer to a change asks the editor to load the graph again: other nodes of it changed, or connections went. */
export function needsReload(answer) {
  return Boolean(answer?.reload || answer?.notices?.some((n) => n.kind === "disconnected"));
}

/**
 * Reload when another editor (or the API) changed this graph through a definition or a use elsewhere.
 * @param {string} graphId the graph this editor shows
 * @param {() => void} reload
 * @returns {() => void} stop following
 */
export function followGraphChanges(graphId, reload) {
  return connectEvents({
    onEvent: (type, data) => {
      if (type === "graph.changed" && Array.isArray(data.graph_ids) && data.graph_ids.includes(graphId)) reload();
    },
    onOpen: () => {},
    onClosed: () => {},
  });
}

/**
 * Follow a publication or a discarded draft of another graph (`graph.contract_changed`, ADR-083 add. 2): what a pipeline editor shows as the
 * inputs and outputs of an action is the contract of the version that runs, and that changes then.
 * @param {(graphId: string) => void} onChange called with the id of the graph whose contract may have changed
 * @returns {() => void} stop following
 */
export function followContracts(onChange) {
  return connectEvents({
    onEvent: (type, data) => {
      if (type === "graph.contract_changed" && typeof data.graph_id === "string") onChange(data.graph_id);
    },
    onOpen: () => {},
    onClosed: () => {},
  });
}
