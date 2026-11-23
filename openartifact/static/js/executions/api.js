/* The calls of the global execution list. Reading is GET /api/executions; deleting stays with the
 * artifact (DELETE /api/tasks/{id}/executions/{execution_id}, see tasks/history-api.js). */
import { request } from "../http.js";

/** One page of executions (newest first) for the query (a URLSearchParams); resolves to {items, next_cursor, total, summary}. */
/** Delete several executions (any artifacts) at once; resolves to {deleted, skipped_running}. */
export const deleteExecutions = (ids) => request("/api/executions/delete", { method: "POST", body: JSON.stringify({ ids }) });

export const listAllExecutions = (query) => request(`/api/executions?${query}`);
