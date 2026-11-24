/* The rows of the timeline that are not live executions: what changed on the artifact, a comment (a button that jumps
 * to it), and the slim line a delete action on executions or on a comment leaves. They share one <ul> with the
 * execution rows (HistoryList) and sit among them by time. Built from <template id="activity-row-template"> with
 * textContent only. */
import { fillTime, placeByTime } from "./history-row.js";
import { setMarker } from "./history-marker.js";
import { actorName, markerOf, previewOf, sentenceOf, timeOf, traceOf } from "./activity-model.js";
import { formatTime } from "./history-format.js";
import { t } from "../i18n.js";

export class ActivityRows {
  /**
   * @param {HTMLElement} root the <ul> of the timeline
   * @param {object} options
   * @param {(id: string) => object | undefined} options.commentOf the comment of an artifact by id (its text is read here, live)
   * @param {(commentId: string) => void} options.onJump a comment entry was activated
   */
  constructor(root, { commentOf, onJump }) {
    this.root = root;
    this.template = document.getElementById("activity-row-template");
    this.commentOf = commentOf;
    /** @type {Map<string, HTMLElement>} */
    this.rows = new Map();
    root.addEventListener("click", (event) => {
      const jump = event.target.closest("[data-event-jump]");
      if (jump) onJump(jump.closest(".history-event").dataset.commentId);
    });
  }

  get(key) {
    return this.rows.get(key);
  }

  /** Show exactly these items ({type: "change"|"trace"|"comment", key, at, entry}); rows of other items go. */
  render(items) {
    const keep = new Set(items.map((item) => item.key));
    for (const [key, row] of this.rows) {
      if (!keep.has(key)) {
        row.remove();
        this.rows.delete(key);
      }
    }
    for (const item of items) {
      let row = this.rows.get(item.key);
      if (!row) {
        row = this.template.content.firstElementChild.cloneNode(true);
        this.rows.set(item.key, row);
      }
      this.#fill(row, item);
      placeByTime(this.root, row, timeOf(item));
    }
  }

  #fill(row, item) {
    const { entry } = item;
    row.dataset.kind = entry.kind;
    row.dataset.group = { change: "changes", trace: "runs", comment: "comments" }[item.type];
    row.dataset.commentId = entry.data?.comment_id ?? "";
    setMarker(row, markerOf(item));
    row.querySelector("[data-event-actor]").textContent = actorName(entry);
    fillTime(row.querySelector("[data-event-time]"), entry.created_at);
    const sub = row.querySelector("[data-event-sub]");
    sub.hidden = true;
    sub.textContent = "";
    let sentence;
    let jumpable = false;
    if (item.type === "trace") {
      const trace = traceOf(entry);
      sentence = trace.sentence;
      if (trace.ran) {
        sub.textContent = t("tasks.activity.ran_at", { time: formatTime(trace.ran) });
        sub.hidden = false;
      }
      row.title = t("tasks.activity.execution_was_deleted");
    } else if (item.type === "comment") {
      if (entry.kind === "comment_deleted") {
        sentence = t("tasks.activity.deleted_comment");
      } else {
        const comment = this.commentOf(entry.data?.comment_id);
        sentence = comment ? t("tasks.activity.commented_preview", { preview: `“${previewOf(comment.body)}”` }) : t("tasks.activity.commented");
        jumpable = comment !== undefined;
      }
    } else {
      sentence = sentenceOf(entry);
    }
    row.querySelector("[data-event-sentence]").textContent = sentence;
    this.#wrap(row, jumpable);
  }

  /** A comment entry's text is a button (it jumps to the comment); every other entry's is plain text. */
  #wrap(row, jumpable) {
    const body = row.querySelector(".history-event__body");
    const text = row.querySelector(".history-event__text");
    const button = row.querySelector("[data-event-jump]");
    if (jumpable && !button) {
      const jump = document.createElement("button");
      jump.type = "button";
      jump.className = "history-event__jump";
      jump.dataset.eventJump = "";
      jump.title = t("tasks.activity.open_comment");
      text.replaceWith(jump);
      jump.append(text);
    } else if (!jumpable && button) {
      button.replaceWith(text);
    }
    if (jumpable) row.querySelector("[data-event-jump]").setAttribute("aria-label", `${text.textContent} — ${t("tasks.activity.open_comment")}`);
    if (!body.contains(text)) body.prepend(text);
  }
}
