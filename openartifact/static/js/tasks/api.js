/* Thin client for the /api/tasks endpoints, the runs of the tasks and the stages of a pipeline. */

import { request } from "../http.js";

export const listTasks = () => request("/api/tasks");

/** @param {{title: string, body: string, status: string}} task */
export const createTask = (task) =>
  request("/api/tasks", { method: "POST", body: JSON.stringify(task) });

/**
 * Partial update of a task: any of title, body, status, parent_id (null = no parent), type_id (null = none),
 * parameters (merged; null clears one) and reset_parameters (drop the stored values when the type changes).
 * @param {string} id
 * @param {{title?: string, body?: string|null, status?: string, parent_id?: string|null}} fields
 */
export const updateTask = (id, fields) =>
  request(`/api/tasks/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(fields) });

/**
 * Move a task to another lane and/or to a position inside a lane.
 * @param {string} id
 * @param {{status?: string, beforeId?: string|null}} placement
 *   beforeId: put it before this task; null = end of the lane; omitted = keep (same lane) or top
 *   (other lane).
 */
export const placeTask = (id, { status, beforeId } = {}) => {
  const fields = {};
  if (status !== undefined) fields.status = status;
  if (beforeId !== undefined) fields.before_id = beforeId;
  return updateTask(id, fields);
};

/** @param {string} id */
export const deleteTask = (id) =>
  request(`/api/tasks/${encodeURIComponent(id)}`, { method: "DELETE" });

const post = (url, body) => request(url, { method: "POST", body: body && JSON.stringify(body) });

export const listRuns = () => request("/api/runs");

/** @param {string} taskId @param {{pipeline_id: string, stage_id: string, action_id: string|null}} start where to start */
export const startRun = (taskId, start) => post(`/api/tasks/${encodeURIComponent(taskId)}/run`, start);

export const stopRun = (taskId) => post(`/api/tasks/${encodeURIComponent(taskId)}/run/stop`);

/** The stages of a pipeline with their actions (the pipelines themselves: listGraphs("pipeline")). */
export const listStages = (pipelineId) => request(`/api/pipelines/${encodeURIComponent(pipelineId)}/stages`);
