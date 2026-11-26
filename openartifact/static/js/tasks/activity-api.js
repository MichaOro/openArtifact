/* Thin client for the activity of an artifact: /api/tasks/{id}/activity (ADR-058). */

import { request } from "../http.js";

/** One page of the activity, newest first: {items, next}; `before` is the `next` of the previous page. */
export function listActivity(taskId, { limit = 50, before = null } = {}) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (before) query.set("before", before);
  return request(`/api/tasks/${encodeURIComponent(taskId)}/activity?${query}`);
}
