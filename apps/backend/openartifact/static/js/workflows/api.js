/* Client for the /api/workflows endpoints. */
import { request } from "../http.js";

const base = (id) => `/api/workflows/${encodeURIComponent(id)}`;
const send = (method, url, body) => request(url, { method, body: body === undefined ? undefined : JSON.stringify(body) });

export const listWorkflows = () => request("/api/workflows");
export const createWorkflow = (name) => send("POST", "/api/workflows", { name });
export const renameWorkflow = (id, name) => send("PATCH", base(id), { name });
export const deleteWorkflow = (id) => send("DELETE", base(id));

export const loadWorkflow = (id) => request(base(id));
export const addNode = (id, node) => send("POST", `${base(id)}/nodes`, node);
export const updateNode = (id, nodeId, fields) => send("PATCH", `${base(id)}/nodes/${encodeURIComponent(nodeId)}`, fields);
export const deleteNode = (id, nodeId) => send("DELETE", `${base(id)}/nodes/${encodeURIComponent(nodeId)}`);
export const connect = (id, edge) => send("POST", `${base(id)}/edges`, edge);
export const disconnect = (id, edgeId) => send("DELETE", `${base(id)}/edges/${encodeURIComponent(edgeId)}`);
