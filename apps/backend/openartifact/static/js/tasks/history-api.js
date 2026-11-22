/* Thin client for the execution history of an artifact: /api/tasks/{id}/executions and the policy. */

import { request } from "../http.js";

const base = (taskId) => `/api/tasks/${encodeURIComponent(taskId)}`;

/** The newest executions (newest first), their total and the retention policy. */
export const listExecutions = (taskId, limit = 100) => request(`${base(taskId)}/executions?limit=${limit}`);

/** One execution with its steps. */
export const getExecution = (taskId, executionId) => request(`${base(taskId)}/executions/${encodeURIComponent(executionId)}`);

/** One step alone, with its whole output and its detail (an agent step's prompts and attempts). */
export const getStep = (taskId, executionId, stepId) =>
  request(`${base(taskId)}/executions/${encodeURIComponent(executionId)}/steps/${encodeURIComponent(stepId)}`);

/** 409 while the execution is running. */
export const deleteExecution = (taskId, executionId) =>
  request(`${base(taskId)}/executions/${encodeURIComponent(executionId)}`, { method: "DELETE" });

/** Deletes every execution that is not running; resolves to {deleted}. */
export const clearExecutions = (taskId) => request(`${base(taskId)}/executions`, { method: "DELETE" });

/** The body replaces the policy: null = no limit. Resolves to {policy, deleted}. */
export const saveHistoryPolicy = (taskId, { keep_last, keep_hours }) =>
  request(`${base(taskId)}/history-policy`, { method: "PUT", body: JSON.stringify({ keep_last, keep_hours }) });
