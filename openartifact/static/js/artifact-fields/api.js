/* Thin client for /api/artifact-fields (ADR-044). */
import { request } from "../http.js";

/** The fields every artifact has: {fields: [...]}, each with artifact_count. */
export const listFields = () => request("/api/artifact-fields");

/** Replaces the whole, ordered list of fields. */
export const replaceFields = (fields) => request("/api/artifact-fields", { method: "PUT", body: JSON.stringify({ fields }) });
