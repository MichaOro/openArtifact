/* Thin client for the /api/tasks endpoints. */

export class ApiError extends Error {
  /**
   * @param {string} message user-presentable message
   * @param {number} status HTTP status, 0 for network failures
   * @param {Record<string, string>} fieldErrors messages by field name
   */
  constructor(message, status, fieldErrors = {}) {
    super(message);
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

async function request(url, options = {}) {
  let response;
  try {
    response = await fetch(url, {
      ...options,
      headers: { Accept: "application/json", "Content-Type": "application/json" },
    });
  } catch {
    throw new ApiError("Could not reach the server. Please check your connection and try again.", 0);
  }

  if (response.ok) return response.json();

  let detail = null;
  try {
    detail = (await response.json()).detail;
  } catch {
    /* non-JSON error body */
  }

  if (response.status === 422 && Array.isArray(detail)) {
    const fieldErrors = {};
    for (const item of detail) {
      const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : null;
      if (typeof field === "string" && !(field in fieldErrors)) fieldErrors[field] = item.msg;
    }
    throw new ApiError("Please check your input.", 422, fieldErrors);
  }
  throw new ApiError("Something went wrong on the server. Please try again.", response.status);
}

export const listTasks = () => request("/api/tasks");

/** @param {{title: string, body: string, status: string}} task */
export const createTask = (task) =>
  request("/api/tasks", { method: "POST", body: JSON.stringify(task) });
