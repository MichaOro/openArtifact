/* The filters of the global execution list as a value that lives in the URL's query string, so a reload,
 * a shared link and the browser's Back button restore them.
 *
 * URL names are the API's: status, started_by (comma separated), pipeline, q, since, until. `range`
 * (1h, 24h, 7d) is a relative since that is worked out when the list is fetched, so a reloaded link means
 * "the last 24 hours" again. `page_size` (tests) passes through untouched. */

export const STATUSES = ["running", "done", "failed", "stopped"];
export const ORIGINS = ["user", "api", "mcp", "system"];
export const RANGES = { "1h": 3600, "24h": 86400, "7d": 7 * 86400 };

const csv = (value, allowed) => [...new Set((value ?? "").split(",").map((v) => v.trim().toLowerCase()))].filter((v) => allowed.includes(v));
const ordered = (values, allowed) => allowed.filter((v) => values.includes(v));

export class Filters {
  constructor({ status = [], startedBy = [], pipeline = "", q = "", range = "", since = "", until = "", pageSize = "" } = {}) {
    this.status = ordered(status, STATUSES);
    this.startedBy = ordered(startedBy, ORIGINS);
    this.pipeline = pipeline.trim();
    this.q = q.trim();
    this.range = range in RANGES ? range : "";
    this.since = since;
    this.until = until;
    this.pageSize = pageSize;
  }

  static fromSearch(search) {
    const p = new URLSearchParams(search);
    return new Filters({
      status: csv(p.get("status"), STATUSES),
      startedBy: csv(p.get("started_by"), ORIGINS),
      pipeline: p.get("pipeline") ?? "",
      q: p.get("q") ?? "",
      range: p.get("range") ?? "",
      since: p.get("since") ?? "",
      until: p.get("until") ?? "",
      pageSize: p.get("page_size") ?? "",
    });
  }

  with(changes) {
    return new Filters({ ...this, ...changes });
  }

  /** Any narrowing at all (page_size is not one). */
  get active() {
    return this.activeCount > 0;
  }

  /** How many kinds of filter are set; shown on the disclosure of the phone layout. */
  get activeCount() {
    return [this.status.length, this.startedBy.length, this.pipeline, this.q, this.range || this.since || this.until].filter(Boolean).length;
  }

  /** since/until given by hand (a link or the API's names) rather than by a preset. */
  get custom() {
    return !this.range && Boolean(this.since || this.until);
  }

  /** The query string of the page's URL ("" when nothing is set). */
  toSearch() {
    const p = new URLSearchParams();
    if (this.status.length) p.set("status", this.status.join(","));
    if (this.startedBy.length) p.set("started_by", this.startedBy.join(","));
    if (this.pipeline) p.set("pipeline", this.pipeline);
    if (this.q) p.set("q", this.q);
    if (this.range) p.set("range", this.range);
    else {
      if (this.since) p.set("since", this.since);
      if (this.until) p.set("until", this.until);
    }
    if (this.pageSize) p.set("page_size", this.pageSize);
    const text = p.toString();
    return text ? `?${text}` : "";
  }

  /** The query of the API call for the first page, or for the one after `cursor`. */
  toQuery({ limit, cursor = null, now = Date.now() } = {}) {
    const p = new URLSearchParams();
    if (this.status.length) p.set("status", this.status.join(","));
    if (this.startedBy.length) p.set("started_by", this.startedBy.join(","));
    if (this.pipeline) p.set("pipeline", this.pipeline);
    if (this.q) p.set("q", this.q);
    const since = this.range ? new Date(now - RANGES[this.range] * 1000).toISOString() : this.since;
    if (since) p.set("since", since);
    if (!this.range && this.until) p.set("until", this.until);
    if (limit) p.set("limit", String(limit));
    if (cursor) p.set("cursor", cursor);
    return p;
  }

  /** Could this execution (as an event carries it) be in the list? false only when a filter surely excludes it;
   * the text search needs the artifact's title, which an event does not have, so it never excludes. */
  mayInclude(execution, now = Date.now()) {
    if (this.status.length && !this.status.includes(execution.status)) return false;
    if (this.startedBy.length && !this.startedBy.includes(execution.started_by)) return false;
    if (this.pipeline) {
      const name = (execution.pipeline_name ?? "").toLowerCase();
      if (execution.pipeline_id !== this.pipeline && !name.includes(this.pipeline.toLowerCase())) return false;
    }
    const started = new Date(execution.started_at).getTime();
    const since = this.range ? now - RANGES[this.range] * 1000 : this.since ? new Date(this.since).getTime() : null;
    if (since !== null && !Number.isNaN(since) && started < since) return false;
    if (!this.range && this.until && started > new Date(this.until).getTime()) return false;
    return true;
  }
}
