/* Thin client for /api/artifact-types. */
import { request } from "../http.js";

export const listTypes = () => request("/api/artifact-types");

/** @param {{name: string, fields: object[]}} type */
export const createType = (type) => request("/api/artifact-types", { method: "POST", body: JSON.stringify(type) });

/** Replaces the name and the whole list of parameters. */
export const replaceType = (id, type) => request(`/api/artifact-types/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(type) });

export const deleteType = (id) => request(`/api/artifact-types/${encodeURIComponent(id)}`, { method: "DELETE" });
