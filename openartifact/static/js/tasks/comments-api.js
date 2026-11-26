/* Thin client for the comments of an artifact: /api/tasks/{id}/comments. */
import { request } from "../http.js";

const base = (taskId) => `/api/tasks/${encodeURIComponent(taskId)}/comments`;

/** The comments, oldest first. */
export const listComments = (taskId) => request(base(taskId));

/** Adds a comment (plain text); resolves to it. The server decides who the author is. */
export const addComment = (taskId, body) => request(base(taskId), { method: "POST", body: JSON.stringify({ body }) });

/** Replaces the text of a comment; resolves to it. */
export const updateComment = (taskId, id, body) =>
  request(`${base(taskId)}/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ body }) });

export const deleteComment = (taskId, id) => request(`${base(taskId)}/${encodeURIComponent(id)}`, { method: "DELETE" });
