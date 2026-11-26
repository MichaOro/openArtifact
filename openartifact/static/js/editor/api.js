/* Client for the /api/pipelines and /api/actions endpoints; `kind` ("pipeline" | "action") picks the resource. */
import { request } from "../http.js";

const root = (kind) => (kind === "action" ? "/api/actions" : "/api/pipelines");
const base = (kind, id) => `${root(kind)}/${encodeURIComponent(id)}`;
const send = (method, url, body) => request(url, { method, body: body === undefined ? undefined : JSON.stringify(body) });

/** `purpose` ("pipeline" | "guard", actions only, ADR-067) narrows the list to the actions for pipelines or for guards. */
export const listGraphs = (kind, purpose = null) => request(purpose ? `${root(kind)}?purpose=${encodeURIComponent(purpose)}` : root(kind));
/** `extra`: the description and tags the new definition starts with. */
export const createGraph = (kind, name, purpose = null, extra = {}) => send("POST", root(kind), { name, ...(purpose ? { purpose } : {}), ...extra });
export const usesOf = (kind, id) => request(`${base(kind, id)}/uses`);
export const stagesOf = (id) => request(`${base("pipeline", id)}/stages`);
export const renameGraph = (kind, id, name) => send("PATCH", base(kind, id), { name });
/** Change the name and/or, for an action, its purpose (a purpose in use on the other side is refused with the places named). */
export const updateGraph = (kind, id, fields) => send("PATCH", base(kind, id), fields);
export const deleteGraph = (kind, id) => send("DELETE", base(kind, id));

// versions (ADR-070): the list, one version with its frozen graph, publish the draft, publish an earlier version again
export const versionsOf = (kind, id) => request(`${base(kind, id)}/versions`);
export const versionOf = (kind, id, number) => request(`${base(kind, id)}/versions/${number}`);
/** `acknowledge`: publish although the check found something (the caller has seen the findings, ADR-082); without it the server refuses. */
export const publishGraph = (kind, id, acknowledge = false) => send("POST", `${base(kind, id)}/publish`, acknowledge ? { acknowledge: true } : undefined);
/** What publishing the draft would run into (ADR-082): `{findings: [{level, code, node_id, node_name, message}], errors, warnings}`. */
export const checkGraph = (kind, id) => request(`${base(kind, id)}/check`);
/** Throw the changes of the draft away: it is the published version again (answers the graph as it is now). */
export const discardGraphDraft = (kind, id) => send("POST", `${base(kind, id)}/draft/discard`);
export const republishGraph = (kind, id, number) => send("POST", `${base(kind, id)}/versions/${number}/republish`);

export const loadGraph = (kind, id) => request(base(kind, id));
/** The inputs and outputs of the version of a graph that RUNS (published, else the draft of a never published one; ADR-083 add. 2). */
export const loadContract = (kind, id) => request(`${base(kind, id)}/contract`);
export const addNode = (kind, id, node) => send("POST", `${base(kind, id)}/nodes`, node);
export const updateNode = (kind, id, nodeId, fields) => send("PATCH", `${base(kind, id)}/nodes/${encodeURIComponent(nodeId)}`, fields);
export const deleteNode = (kind, id, nodeId) => send("DELETE", `${base(kind, id)}/nodes/${encodeURIComponent(nodeId)}`);
export const connect = (kind, id, edge) => send("POST", `${base(kind, id)}/edges`, edge);
export const restyleEdge = (kind, id, edgeId, style) => send("PATCH", `${base(kind, id)}/edges/${encodeURIComponent(edgeId)}`, { style });
export const disconnect = (kind, id, edgeId) => send("DELETE", `${base(kind, id)}/edges/${encodeURIComponent(edgeId)}`);
