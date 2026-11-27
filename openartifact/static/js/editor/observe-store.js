/* What the editor knows of the observe mode of its pipeline (ADR-088): the answer of `GET /api/pipelines/{ref}/observe` (the draft, the
 * published setting and the state), read again when something changes (a run, a publication, the draft), and the calls. A pipeline only:
 * an action has no mode of its own (it is tried with a dry run). */
import { request } from "../http.js";
import { connectEvents } from "../tasks/events.js";

const send = (method, url, body) => request(url, { method, body: body === undefined ? undefined : JSON.stringify(body) });

export class ObserveStore {
  /** @param {string} id the pipeline's id */
  constructor(id) {
    this.url = `/api/pipelines/${encodeURIComponent(id)}/observe`;
    this.read = null;
    this.listeners = new Set();
    this.turn = 0;
    connectEvents({
      onEvent: (type) => {
        if (type === "run.updated" || type === "graph.changed" || type === "graph.contract_changed") this.#later();
      },
      onOpen: () => this.refresh(),
      onClosed: () => {},
    });
  }

  /** Call `fn(read)` now (when known) and whenever the answer changes. */
  subscribe(fn) {
    this.listeners.add(fn);
    if (this.read) fn(this.read);
  }

  #later() {
    window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => this.refresh(), 400);
  }

  async refresh() {
    const turn = (this.turn += 1);
    try {
      const read = await request(this.url);
      if (turn === this.turn) this.#set(read);
    } catch {
      /* a hint, not the editor's state: the bar keeps what it showed */
    }
    return this.read;
  }

  #set(read) {
    this.read = read;
    for (const fn of [...this.listeners]) fn(read);
  }

  /** Set the draft (the mode goes live with a publication). */
  async setDraft(setting) {
    this.#set(await send("PUT", this.url, setting));
    return this.read;
  }

  async release() {
    this.#set(await send("POST", `${this.url}/release`));
    return this.read;
  }

  async again(limits = {}) {
    this.#set(await send("POST", `${this.url}/again`, limits));
    return this.read;
  }
}
