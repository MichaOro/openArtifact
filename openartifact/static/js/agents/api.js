/* Thin client for /api/agents and /api/providers (and the secret names a provider may refer to). */
import { request } from "../http.js";

const agent = (id) => `/api/agents/${encodeURIComponent(id)}`;
const provider = (id) => `/api/providers/${encodeURIComponent(id)}`;
const send = (method, url, body) => request(url, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

export const listAgents = () => request("/api/agents");
export const getAgent = (id) => request(agent(id));
export const createAgent = (data) => send("POST", "/api/agents", data);
export const updateAgent = (id, data) => send("PATCH", agent(id), data);
export const deleteAgent = (id) => send("DELETE", agent(id));
export const saveDraft = (id, config) => send("PUT", `${agent(id)}/draft`, config);
export const discardDraft = (id) => send("POST", `${agent(id)}/draft/discard`);
export const publishAgent = (id) => send("POST", `${agent(id)}/publish`);
export const republishVersion = (id, number) => send("POST", `${agent(id)}/versions/${number}/republish`);
export const agentUses = (id) => request(`${agent(id)}/uses`);
/** The prompts as they would be sent; no request goes to a model. */
export const previewAgent = (id, body) => send("POST", `${agent(id)}/preview`, body);

export const listProviders = () => request("/api/providers");
export const testProvider = (data) => send("POST", "/api/providers/test", data);
export const createProvider = (data) => send("POST", "/api/providers", data);
export const updateProvider = (id, data) => send("PATCH", provider(id), data);
export const deleteProvider = (id) => send("DELETE", provider(id));
export const checkProvider = (id) => send("POST", `${provider(id)}/test`);
export const refreshModels = (id) => send("POST", `${provider(id)}/models/refresh`);
export const addModel = (id, data) => send("POST", `${provider(id)}/models`, data);
export const updateModel = (id, modelId, data) => send("PATCH", `${provider(id)}/models/${encodeURIComponent(modelId)}`, data);
export const deleteModel = (id, modelId) => send("DELETE", `${provider(id)}/models/${encodeURIComponent(modelId)}`);

export const listSecrets = () => request("/api/secrets");
/** Stores or replaces a secret; the value is never read back. */
export const putSecret = (name, value) => send("PUT", `/api/secrets/${encodeURIComponent(name)}`, { value });
