/* The numbers and the actions of the Data storage section (ADR-084), under the form of Settings > Personal: the size of the database
 * file and of its write-ahead log, the biggest tables, the last cleaning pass, a warning when the file is over the size the user set;
 * and three actions: Preview (what a pass would delete or empty, nothing is changed), Clean now (asks first, then does exactly what
 * the preview shows) and Shrink database (asks first: it rewrites the file). Text is set with textContent only. */
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { Modal } from "../components/modal.js";
import { request } from "../http.js";
import { plural, t } from "../i18n.js";

const BASE = "/api/settings/storage";

/** A size in bytes for people: "1.9 MiB", "512 KiB", "300 B". */
export function human(bytes) {
  if (!Number.isFinite(bytes)) return "";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const text = unit === 0 || value >= 100 ? String(Math.round(value)) : value.toFixed(1).replace(/\.0$/, "");
  return `${text} ${units[unit]}`;
}

function element(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

export class StoragePanel {
  /** @param {HTMLElement} root the panel (`[data-storage-panel]`) */
  constructor(root) {
    this.root = root;
    this.warning = root.querySelector("[data-storage-warning]");
    this.facts = root.querySelector("[data-storage-facts]");
    this.tables = root.querySelector("[data-storage-tables]");
    this.result = root.querySelector("[data-storage-result]");
    this.errorLine = root.querySelector("[data-storage-error]");
    this.confirm = new ConfirmDialog(new Modal(document.getElementById("storage-confirm")));
    root.querySelector("[data-storage-preview]").addEventListener("click", () => this.preview());
    root.querySelector("[data-storage-clean]").addEventListener("click", () => this.askClean());
    root.querySelector("[data-storage-shrink]").addEventListener("click", () => this.askShrink());
    this.refresh();
  }

  #error(message) {
    this.errorLine.textContent = message;
    this.errorLine.hidden = !message;
  }

  async refresh() {
    try {
      this.draw(await request(BASE));
      this.#error("");
    } catch (problem) {
      this.#error(problem.detail ?? problem.message);
    }
  }

  draw(status) {
    const { db } = status;
    this.warning.hidden = !db.over_warning;
    this.warning.textContent = db.over_warning ? t("storage.over_warning", { size: human(db.file_bytes), limit: human(db.warn_bytes) }) : "";
    const last = status.last_clean;
    const rows = [
      [t("storage.file"), human(db.file_bytes)],
      [t("storage.wal"), human(db.wal_bytes)],
      [t("storage.free_pages"), `${db.free_pages} (${human(db.free_bytes)})`],
      [t("storage.run_data"), human(status.run_data_bytes)],
      [t("storage.cleaner"), status.interval_hours ? plural("storage.every_hours", status.interval_hours) : t("storage.cleaner_off")],
      [t("storage.last_pass"), last ? t("storage.last_pass_value", { when: new Date(last.at).toLocaleString(), entries: last.entries, size: human(last.bytes) }) : t("storage.never")],
    ];
    this.facts.replaceChildren(...rows.flatMap(([label, value]) => [element("dt", "", label), element("dd", "", value)]));
    const heading = element("h3", "st-subheading", t("storage.biggest_tables"));
    const list = element("ul", "st-list");
    for (const table of db.tables) {
      const size = table.bytes === null ? plural("storage.rows", table.rows ?? 0) : human(table.bytes);
      list.append(element("li", "", `${table.name}: ${size}`));
    }
    this.tables.replaceChildren(heading, list);
  }

  /** The categories of a plan as a list, or one line when it has nothing to do. */
  #plan(plan) {
    const box = element("div", "st-plan");
    if (plan.entries === 0) {
      box.append(element("p", "", t("storage.nothing")));
      return box;
    }
    const list = element("ul", "st-list");
    for (const category of plan.categories.filter((c) => c.entries > 0)) {
      list.append(element("li", "", `${category.label}: ${plural("storage.entries", category.entries)}, ${human(category.bytes)}`));
    }
    box.append(element("p", "st-plan__total", t("storage.would", { entries: plan.entries, size: human(plan.bytes) })), list);
    return box;
  }

  async preview() {
    this.#error("");
    try {
      const plan = await request(`${BASE}/preview`, { method: "POST", body: "{}" });
      this.result.replaceChildren(this.#plan(plan));
      this.result.hidden = false;
    } catch (problem) {
      this.#error(problem.detail ?? problem.message);
    }
  }

  async askClean() {
    this.#error("");
    let plan;
    try {
      plan = await request(`${BASE}/preview`, { method: "POST", body: "{}" });
    } catch (problem) {
      this.#error(problem.detail ?? problem.message);
      return;
    }
    const lines = plan.categories.filter((c) => c.entries > 0).map((c) => ({ level: "warning", mark: "•", label: c.label, text: `${plural("storage.entries", c.entries)}, ${human(c.bytes)}` }));
    this.confirm.open({
      title: t("storage.confirm_title"),
      message: plan.entries ? t("storage.confirm_clean", { entries: plan.entries, size: human(plan.bytes) }) : t("storage.confirm_clean_nothing"),
      note: t("storage.confirm_note"),
      items: lines,
      confirmLabel: t("storage.clean_now"),
      tone: plan.entries ? "danger" : "primary",
      onConfirm: async () => {
        const report = await request(`${BASE}/clean`, { method: "POST", body: "{}" });
        this.result.replaceChildren(this.#plan(report.plan), element("p", "", t("storage.cleaned", { before: human(report.before.file_bytes), after: human(report.after.file_bytes) })));
        this.result.hidden = false;
        await this.refresh();
      },
    });
  }

  askShrink() {
    this.#error("");
    this.confirm.open({
      title: t("storage.shrink_title"),
      message: t("storage.confirm_shrink"),
      note: t("storage.confirm_shrink_note"),
      confirmLabel: t("storage.shrink"),
      tone: "danger",
      onConfirm: async () => {
        const report = await request(`${BASE}/shrink`, { method: "POST", body: "{}" });
        this.result.replaceChildren(element("p", "", t("storage.shrunk", { before: human(report.before.file_bytes), after: human(report.after.file_bytes) })));
        this.result.hidden = false;
        await this.refresh();
      },
    });
  }
}
