/* The calls of the flow page. All of them read: the page never changes anything on the server. */
import { request } from "../http.js";

const task = (ref) => `/api/tasks/${encodeURIComponent(ref)}`;

/** The flow of one execution; outputs are left out (see loadStep). */
export const loadFlow = (ref, executionId) => request(`${task(ref)}/executions/${encodeURIComponent(executionId)}/flow?outputs=false`);

/** One step with its whole output. */
export const loadStep = (ref, executionId, stepId) => request(`${task(ref)}/executions/${encodeURIComponent(executionId)}/steps/${encodeURIComponent(stepId)}`);

/** The run context of the execution (variables and the latest result of each node). */
export const loadContext = (ref, executionId) => request(`${task(ref)}/executions/${encodeURIComponent(executionId)}/context`);

/** The artifact the execution belongs to (number and title for the page header). */
export const loadTask = (ref) => request(task(ref));
