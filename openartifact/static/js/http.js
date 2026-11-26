/* Shared JSON client for the REST API. */

import { t } from "./i18n.js";
export class ApiError extends Error {
  /**
   * @param {string} message user-presentable message
   * @param {number} status HTTP status, 0 for network failures
   * @param {Record<string, string>} fieldErrors messages by field name
   * @param {string|null} detail the server's own explanation, when it sent a text (a refused rule, a conflict)
   * @param {string|null} code the stable word the server gave a refusal (`stopped`), for what a program must tell apart
   */
  constructor(message, status, fieldErrors = {}, detail = null, code = null) {
    super(message);
    this.status = status;
    this.fieldErrors = fieldErrors;
    this.detail = detail;
    this.code = code;
  }
}

let signingIn = false;

/** The sign-in has expired (or was ended in another tab): go and sign in again, then come back here. */
function signIn() {
  if (!signingIn && window.location.pathname !== "/login") {
    signingIn = true;
    window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
  }
  return new ApiError(t("http.your_sign_has_expired_please"), 401);
}

export async function request(url, options = {}) {
  let response;
  try {
    response = await fetch(url, {
      ...options,
      headers: { Accept: "application/json", "Content-Type": "application/json", ...options.headers },
    });
  } catch {
    throw new ApiError(t("http.could_not_reach_server_please"), 0);
  }

  if (response.status === 204) return null;
  if (response.ok) return response.json();
  if (response.status === 401) throw signIn();

  let detail = null;
  let code = null;
  try {
    const body = await response.json();
    detail = body.detail;
    code = typeof body.code === "string" ? body.code : null;
  } catch {
    /* non-JSON error body */
  }

  if (response.status === 422 && Array.isArray(detail)) {
    const fieldErrors = {};
    for (const item of detail) {
      const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : null;
      if (typeof field === "string" && !(field in fieldErrors)) fieldErrors[field] = item.msg;
    }
    throw new ApiError(t("http.please_check_your_input"), 422, fieldErrors);
  }
  const text = typeof detail === "string" && detail ? detail : null;
  if (response.status >= 500) throw new ApiError(t("http.something_went_wrong_server_please"), response.status, {}, text);
  throw new ApiError(text ?? t("http.request_was_not_accepted"), response.status, {}, text, code);
}
