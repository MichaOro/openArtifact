/* Client for the /api/pipelines and /api/actions endpoints; `kind` ("pipeline" | "action") picks the resource. */
import { request } from "../http.js";

const root = (kind) => (kind === "action" ? "/api/actions" : "/api/pipelines");
const base = (kind, id) => `${root(kind)}/${encodeURIComponent(id)}`;
const send = (method, url, body) => request(url, { method, body: body === undefined ? undefined : JSON.stringify(body) });

export const listGraphs = (kind) => request(root(kind));
export const createGraph = (kind, name) => send("POST", root(kind), { name });
export const renameGraph = (kind, id, name) => send("PATCH", base(kind, id), { name });
export const deleteGraph = (kind, id) => send("DELETE", base(kind, id));

export const loadGraph = (kind, id) => request(base(kind, id));
export const addNode = (kind, id, node) => send("POST", `${base(kind, id)}/nodes`, node);
export const updateNode = (kind, id, nodeId, fields) => send("PATCH", `${base(kind, id)}/nodes/${encodeURIComponent(nodeId)}`, fields);
export const deleteNode = (kind, id, nodeId) => send("DELETE", `${base(kind, id)}/nodes/${encodeURIComponent(nodeId)}`);
export const connect = (kind, id, edge) => send("POST", `${base(kind, id)}/edges`, edge);
export const restyleEdge = (kind, id, edgeId, style) => send("PATCH", `${base(kind, id)}/edges/${encodeURIComponent(edgeId)}`, { style });
export const disconnect = (kind, id, edgeId) => send("DELETE", `${base(kind, id)}/edges/${encodeURIComponent(edgeId)}`);
