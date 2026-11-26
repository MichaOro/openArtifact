/* The archive (ADR-071): the cards that were archived, read only, in the frame of the management pages (components/management-page.js).
 * Tiles on two thirds, the panel on one third with four tabs (Details, Comments, History, Context). The one thing that can be done
 * here is "Remove from archive": the card goes back on top of the lane it came from. The board's menu shows and hides this view. */
import { ClampedText } from "../components/clamped-text.js";
import { ManagementPage, cardBody, chip, make } from "../components/management-page.js";
import { t } from "../i18n.js";
import { listActivity } from "./activity-api.js";
import { actorName, sentenceOf } from "./activity-model.js";
import { SORTS, contextRows, searchText } from "./archive-model.js";
import { listArchive, unarchiveTask, getTask } from "./api.js";
import { kindOf } from "./comment-format.js";
import { listComments } from "./comments-api.js";

const when = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
const day = (iso) => new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });

export class ArchiveView {
  /**
   * @param {object} options
   * @param {HTMLElement} options.root the element the page is built in
   * @param {() => {name: string, label: string}[]} options.fields the artifact fields
   * @param {(id: string) => string|null} options.parentTitle the title of a card of the board
   * @param {(task: object) => void} options.onRestored a card left the archive (the board takes it in)
   * @param {(message: string) => void} options.onError
   */
  constructor({ root, fields, parentTitle, onRestored, onError }) {
    this.root = root;
    this.fields = fields;
    this.parentTitle = parentTitle;
    this.onRestored = onRestored;
    this.onError = onError;
    this.visible = false;
    this.page = new ManagementPage(root, {
      name: "archive",
      label: t("archive.title"),
      placeholder: t("components.management.search"),
      emptyText: t("archive.empty"),
      itemKey: (task) => task.id,
      readOnly: true,
      search: searchText,
      sorts: SORTS.map((s) => ({ key: s.key, label: s.label(), compare: s.compare })),
      card: (task) => this.#card(task),
      panel: {
        placeholder: t("archive.select"),
        icon: () => "inbox",
        title: (task) => task.title,
        chips: (task) => [chip(`#${task.number}`), ...(task.archived_from_lane ? [chip(task.archived_from_lane)] : [])],
        tabs: () => [
          { key: "details", label: t("archive.tab_details"), render: (body, task) => this.#details(body, task) },
          { key: "comments", label: t("archive.tab_comments"), render: (body, task) => this.#comments(body, task) },
          { key: "history", label: t("archive.tab_history"), render: (body, task) => this.#history(body, task) },
          { key: "context", label: t("archive.tab_context"), render: (body, task) => this.#context(body, task) },
        ],
      },
    });
  }

  /** Show or hide the view; showing reads the archive again. */
  async show(on) {
    this.visible = on;
    this.root.hidden = !on;
    if (on) await this.load();
  }

  async load() {
    try {
      this.page.setItems(await listArchive());
    } catch {
      this.onError(t("archive.load_failed"));
    }
  }

  /** The live events: the archive changed (a card came in or left), read it again while it is shown. */
  handleEvent(type) {
    if (this.visible && (type === "board.updated" || type === "task.updated" || type === "task.deleted")) this.load();
  }

  #card(task) {
    const part = (value, before = "") => {
      const span = make("span");
      span.append(document.createTextNode(before), make("b", "", value));
      return span;
    };
    // where the card came from, not where it is (it is in the archive); a lane that no longer exists says so
    const facts = [part(task.archived_from_lane ?? t("archive.lane_gone"), `${t("archive.lane")}: `)];
    return cardBody({
      title: task.title,
      text: task.preview ?? task.body,
      chips: [chip(`#${task.number}`)],
      facts,
      date: task.archived_at ? part(day(task.archived_at), `${t("archive.archived")} `) : null,
    });
  }

  #loading(body) {
    body.append(make("p", "mg-card__facts", t("archive.loading")));
  }

  #failed(body) {
    body.replaceChildren(make("p", "mg-card__facts", t("archive.load_failed")));
  }

  #details(body, task) {
    this.#loading(body);
    getTask(task.id)
      .then((full) => {
        const text = full.body_resolved ?? full.body ?? "";
        const list = make("dl", "mg-facts");
        for (const [label, value] of [[t("archive.archived"), when(full.archived_at)], [t("archive.created"), when(full.created_at)]]) {
          list.append(make("dt", "", label), make("dd", "", value));
        }
        const remove = make("button", "button button--primary button--sm", t("archive.remove"));
        remove.type = "button";
        remove.dataset.unarchive = "";
        remove.addEventListener("click", () => this.#remove(task, remove));
        const actions = make("div", "action-row");
        actions.append(remove);
        const section = make("section", "mg-section");
        section.append(make("h3", "", t("archive.text")), new ClampedText({ text, label: t("archive.text"), empty: t("archive.no_text") }).element);
        body.replaceChildren(section, list, actions);
      })
      .catch(() => this.#failed(body));
  }

  async #remove(task, button) {
    button.disabled = true;
    try {
      const restored = await unarchiveTask(task.id);
      this.page.setItems(this.page.items.filter((x) => x.id !== task.id));
      this.onRestored(restored);
    } catch {
      button.disabled = false;
      this.onError(t("archive.remove_failed"));
    }
  }

  #comments(body, task) {
    this.#loading(body);
    listComments(task.id)
      .then((comments) => {
        if (!comments.length) return body.replaceChildren(make("p", "mg-card__facts", t("archive.no_comments")));
        const list = make("ul", "mg-uses");
        for (const comment of comments) {
          const item = make("li");
          const head = make("span", "mg-uses__kind", `${kindOf(comment).label} · ${when(comment.created_at)}`);
          item.append(head, make("div", "archive-text", comment.body));
          list.append(item);
        }
        body.replaceChildren(list);
      })
      .catch(() => this.#failed(body));
  }

  #history(body, task) {
    this.#loading(body);
    listActivity(task.id, { limit: 200 })
      .then(({ items }) => {
        if (!items.length) return body.replaceChildren(make("p", "mg-card__facts", t("archive.no_history")));
        const list = make("ul", "mg-uses");
        for (const entry of items) {
          const item = make("li");
          item.append(make("span", "mg-uses__kind", when(entry.created_at)), document.createTextNode(`${actorName(entry)} ${sentenceOf(entry)}`));
          list.append(item);
        }
        body.replaceChildren(list);
      })
      .catch(() => this.#failed(body));
  }

  #context(body, task) {
    const list = make("dl", "mg-facts");
    for (const row of contextRows(task, this.fields(), task.parent_id ? this.parentTitle(task.parent_id) : null)) {
      list.append(make("dt", "", row.label), make("dd", "", row.value));
    }
    body.replaceChildren(list);
  }
}
