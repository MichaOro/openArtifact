/* Shared JSON client for the REST API. */

export class ApiError extends Error {
  /**
   * @param {string} message user-presentable message
   * @param {number} status HTTP status, 0 for network failures
   * @param {Record<string, string>} fieldErrors messages by field name
   * @param {string|null} detail the server's own explanation, when it sent a text (a refused rule, a conflict)
   */
  constructor(message, status, fieldErrors = {}, detail = null) {
    super(message);
    this.status = status;
    this.fieldErrors = fieldErrors;
    this.detail = detail;
  }
}

let signingIn = false;

/** The sign-in has expired (or was ended in another tab): go and sign in again, then come back here. */
function signIn() {
  if (!signingIn && window.location.pathname !== "/login") {
    signingIn = true;
    window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
  }
  return new ApiError("Your sign-in has expired. Please sign in again.", 401);
}

export async function request(url, options = {}) {
  let response;
  try {
    response = await fetch(url, {
      ...options,
      headers: { Accept: "application/json", "Content-Type": "application/json", ...options.headers },
    });
  } catch {
    throw new ApiError("Could not reach the server. Please check your connection and try again.", 0);
  }

  if (response.status === 204) return null;
  if (response.ok) return response.json();
  if (response.status === 401) throw signIn();

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
  const text = typeof detail === "string" && detail ? detail : null;
  if (response.status >= 500) throw new ApiError("Something went wrong on the server. Please try again.", response.status, {}, text);
  throw new ApiError(text ?? "The request was not accepted.", response.status, {}, text);
}
