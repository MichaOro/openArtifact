/* The Comments tab of the artifact dialog (templates/components/comments_panel.html): the comments of the shown artifact,
 * oldest first, with a box to write at the bottom. Plain text only (shown with its line breaks, never as markup).
 *
 * The tab follows the artifact the dialog shows (show / hide) and is kept current by the page's event stream:
 * comment.created / updated / deleted reach it through handleEvent(). Editing happens in place; delete asks first. */
import { ActionMenu } from "../components/action-menu.js";
import { AlertBar } from "../components/alert-bar.js";
import { avatar } from "../components/avatar.js";
import { icon } from "../components/icons.js";
import { addComment, deleteComment, listComments, updateComment } from "./comments-api.js";
import { canSend, countText, inOrder, isEdited, kindOf, runLink, withComment } from "./comment-format.js";
import { collapseComments, isHiddenComment, COLLAPSED } from "./activity-model.js";
import { formatTime } from "./history-format.js";
import { plural, t } from "../i18n.js";

/** How long the highlight of a jumped-to comment stays when motion is reduced (it is a static one then), in ms. */
const HOLD_MS = 1500;
/** The longest the pulsing highlight can last (three pulses of half a second) before it is taken off anyway, in ms. */
const PULSE_MAX_MS = 2500;

export class CommentsTab {
  /**
   * @param {object} options
   * @param {HTMLElement} options.root the panel (templates/components/comments_panel.html)
   * @param {HTMLElement} options.badge the count on the tab
   * @param {import("../components/confirm-dialog.js").ConfirmDialog} options.confirm
   * @param {() => void} [options.onChange] the comments shown changed (the History tab reads their text live)
   */
  constructor({ root, badge, confirm, onChange = () => {} }) {
    this.onChange = onChange;
    this.root = root;
    this.badge = badge;
    this.confirm = confirm;
    this.menu = new ActionMenu();
    this.taskId = null;
    this.number = null;
    this.comments = [];
    this.editingId = null;
    this.token = 0;
    this.sending = false;
    this.expanded = false; // the older comments are shown (GitHub-style "Show N older comments")

    this.alert = new AlertBar(root.querySelector("[data-comments-alert]"));
    this.alert.onRetry(() => this.load());
    this.live = root.querySelector("[data-comments-live]");
    this.summary = root.querySelector("[data-comments-summary]");
    this.list = root.querySelector("[data-comments-list]");
    this.empty = root.querySelector("[data-comments-empty]");
    this.form = root.querySelector("[data-comments-form]");
    this.input = root.querySelector("[data-comments-input]");
    this.send = root.closest("[data-task-view]").querySelector("[data-comments-send]"); // in the dialog footer, next to Close
    this.error = root.querySelector("[data-comments-error]");
    this.scroller = root.querySelector("[data-comments-scroll]");
    this.older = root.querySelector("[data-comments-older]");
    this.older.addEventListener("click", () => this.#toggleExpanded());
    this.template = document.getElementById("comment-template");

    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.#submit();
    });
    this.input.addEventListener("input", () => this.#syncSend());
    this.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        this.#submit();
      }
    });
    this.list.addEventListener("click", (event) => {
      const more = event.target.closest("[data-comment-more]");
      if (more) this.#openMenu(more, this.comments.find((c) => c.id === more.closest(".comment").dataset.id));
    });
  }

  /** Whether a text is typed and not sent (the dialog warns before it is closed over it). */
  get dirty() {
    return this.taskId !== null && (this.input.value.trim() !== "" || this.editingId !== null);
  }

  /** The dialog shows this artifact: start from its comments (a reopened one keeps what it had until the fresh data arrives). */
  show(task) {
    const same = task.id === this.taskId;
    this.taskId = task.id;
    this.number = task.number;
    if (!same) {
      this.comments = [];
      this.expanded = false;
      this.editingId = null;
      this.input.value = "";
      this.#setError("");
      this.alert.hide();
      this.#render();
    }
    this.#syncSend();
    this.load({ scroll: true });
  }

  /** The tab was opened: the newest comment is the one in view (a hidden panel has no height to scroll). */
  scrollToEnd() {
    window.requestAnimationFrame(() => (this.scroller.scrollTop = this.scroller.scrollHeight));
  }

  /** The dialog closed: stop listening. */
  hide() {
    this.taskId = null;
    this.token++;
    this.menu.close({ restoreFocus: false });
  }

  async load({ scroll = false } = {}) {
    const taskId = this.taskId;
    if (!taskId) return;
    const token = ++this.token;
    try {
      const comments = await listComments(taskId);
      if (token !== this.token) return;
      this.comments = inOrder(comments);
      this.alert.hide();
      this.#render({ scroll });
    } catch (error) {
      if (token === this.token) this.alert.show(error.message || t("tasks.comments_tab.comments_could_not_be_loaded"), { retry: true });
    }
  }

  /** comment.created / updated / deleted of the event stream. */
  handleEvent(type, data) {
    if (!this.taskId || data.task_id !== this.taskId) return;
    if (type === "comment.deleted") {
      this.comments = this.comments.filter((c) => c.id !== data.id);
      if (this.editingId === data.id) this.editingId = null;
      this.#render();
      this.announce(t("tasks.comments_tab.comment_was_deleted"));
      return;
    }
    const atEnd = this.#atEnd();
    const changed = this.comments.some((c) => c.id === data.id);
    this.comments = withComment(this.comments, data);
    if (this.editingId === data.id) return this.#render({ keep: true }); // what is typed stays
    this.#render({ scroll: atEnd && !changed });
    if (!changed) this.announce(t("tasks.comments_tab.new_comment_from_author", { author: data.author }));
  }

  announce(message) {
    this.live.textContent = "";
    window.requestAnimationFrame(() => (this.live.textContent = message));
  }

  // ── showing ─────────────────────────────────────────────────────────

  #atEnd() {
    const box = this.scroller;
    return box.scrollHeight - box.scrollTop - box.clientHeight < 48;
  }

  #render({ scroll = false, keep = false } = {}) {
    this.badge.hidden = this.taskId === null || this.comments.length === 0;
    this.badge.textContent = this.badge.hidden ? "" : String(this.comments.length);
    this.badge.title = countText(this.comments.length);
    this.summary.textContent = countText(this.comments.length);
    this.empty.hidden = this.comments.length > 0;
    // the newest comments are shown; a comment being edited is never hidden under the fold
    const { shown, hidden } = collapseComments(this.comments, this.expanded, COLLAPSED, this.editingId);
    this.older.hidden = hidden === 0 && !(this.expanded && this.comments.length > COLLAPSED);
    this.older.textContent = hidden > 0 ? plural("tasks.comments_tab.show_older", hidden) : t("tasks.activity.show_fewer");
    this.older.setAttribute("aria-expanded", String(hidden === 0));
    const open = this.root.querySelector("[data-comment-edit-input]");
    const typed = open?.value;
    const rows = shown.map((comment) => this.#row(comment));
    this.list.replaceChildren(...rows);
    if (keep && typed !== undefined) {
      const again = this.root.querySelector("[data-comment-edit-input]");
      if (again) again.value = typed;
    }
    if (scroll) window.requestAnimationFrame(() => (this.scroller.scrollTop = this.scroller.scrollHeight));
    this.onChange();
  }

  /** The comment of this id, or undefined (the History tab shows its first words next to its entry). */
  commentOf(id) {
    return this.comments.find((comment) => comment.id === id);
  }

  /** Show the older comments, or fold them again; the comments in view stay where they are. */
  #toggleExpanded() {
    const box = this.scroller;
    const before = box.scrollHeight - box.scrollTop;
    this.expanded = !this.expanded;
    this.#render();
    if (this.expanded) box.scrollTop = box.scrollHeight - before;
    else box.scrollTop = box.scrollHeight;
    this.older.focus();
  }

  /**
   * Show a comment of the artifact: the tab expands over it when it is under the fold, scrolls it into view, moves the
   * focus to it and pulses its border three times (once, held, when motion is reduced).
   * @param {string} id
   */
  async reveal(id) {
    if (!this.commentOf(id)) await this.load();
    const comment = this.commentOf(id);
    if (!comment) return this.announce(t("tasks.comments_tab.comment_no_longer_exists"));
    if (isHiddenComment(this.comments, id)) this.expanded = true;
    this.#render({ keep: true });
    await new Promise((resolve) => window.requestAnimationFrame(() => window.requestAnimationFrame(resolve)));
    const row = this.list.querySelector(`[data-id="${CSS.escape(id)}"]`);
    if (!row) return;
    row.scrollIntoView({ block: "center" });
    row.tabIndex = -1;
    row.focus({ preventScroll: true });
    this.#pulse(row);
    this.announce(t("tasks.comments_tab.comment_from_author", { author: comment.author }));
  }

  #pulse(row) {
    row.removeAttribute("data-pulse");
    void row.offsetWidth; // restart the animation when it is jumped to again
    row.dataset.pulse = "";
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const off = () => row.removeAttribute("data-pulse");
    if (!reduced) row.addEventListener("animationend", off, { once: true });
    window.setTimeout(off, reduced ? HOLD_MS : PULSE_MAX_MS);
  }

  #row(comment) {
    const row = this.template.content.firstElementChild.cloneNode(true);
    row.dataset.id = comment.id;
    row.dataset.kind = comment.author_kind;
    const kind = kindOf(comment);
    // The kind is the avatar's icon and its accessible name; the name stands beside it, the kind is not written out.
    row.querySelector("[data-comment-avatar]").replaceWith(avatar({ kind: comment.author_kind, label: kind.label, icon: kind.icon }));
    row.querySelector("[data-comment-author]").textContent = comment.author;
    const time = row.querySelector("[data-comment-time]");
    time.textContent = formatTime(comment.created_at);
    time.dateTime = comment.created_at;
    time.title = comment.created_at;
    row.querySelector("[data-comment-edited]").hidden = !isEdited(comment);
    const href = runLink(comment, this.number);
    const link = row.querySelector("[data-comment-run]");
    link.hidden = href === null;
    if (href) link.href = href;
    const more = row.querySelector("[data-comment-more]");
    more.replaceChildren(icon("more"));
    more.setAttribute("aria-label", t("tasks.comments_tab.actions_comment_author", { author: comment.author }));
    const body = row.querySelector("[data-comment-body]");
    if (this.editingId === comment.id) {
      body.replaceChildren(this.#editor(comment));
    } else {
      body.textContent = comment.body; // plain text: line breaks by CSS (white-space: pre-wrap), never markup
    }
    return row;
  }

  #editor(comment) {
    const form = document.createElement("form");
    form.className = "comment__edit";
    const area = document.createElement("textarea");
    area.className = "field__control";
    area.rows = 4;
    area.value = comment.body;
    area.dataset.commentEditInput = "";
    area.setAttribute("aria-label", t("tasks.comments_tab.edit_comment"));
    const error = document.createElement("p");
    error.className = "form-error";
    error.setAttribute("role", "alert");
    error.hidden = true;
    const actions = document.createElement("div");
    actions.className = "comment__edit-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "button button--ghost button--sm";
    cancel.textContent = t("common.cancel");
    const save = document.createElement("button");
    save.type = "submit";
    save.className = "button button--primary button--sm";
    save.textContent = t("common.save");
    actions.append(cancel, save);
    form.append(area, error, actions);
    const stop = () => {
      this.editingId = null;
      this.#render();
    };
    cancel.addEventListener("click", stop);
    area.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation(); // the dialog must not close over it
        stop();
      } else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        form.requestSubmit();
      }
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!canSend(area.value)) {
        error.textContent = t("tasks.comments_tab.comment_cannot_be_empty");
        error.hidden = false;
        return;
      }
      save.disabled = true;
      try {
        const changed = await updateComment(this.taskId, comment.id, area.value);
        this.comments = withComment(this.comments, changed);
        this.editingId = null;
        this.#render();
      } catch (failure) {
        if (failure.status === 404) {
          this.comments = this.comments.filter((c) => c.id !== comment.id);
          this.editingId = null;
          this.#render();
          return;
        }
        error.textContent = failure.fieldErrors?.body ?? failure.message;
        error.hidden = false;
        save.disabled = false;
      }
    });
    window.requestAnimationFrame(() => area.focus());
    return form;
  }

  // ── actions ─────────────────────────────────────────────────────────

  #openMenu(trigger, comment) {
    if (!comment) return;
    this.menu.toggle(
      trigger,
      [
        {
          label: t("common.edit"),
          icon: "pencil",
          onSelect: () => {
            this.editingId = comment.id;
            this.#render();
          },
        },
        { label: t("common.delete"), icon: "trash", danger: true, onSelect: () => this.#confirmDelete(comment) },
      ],
      t("tasks.comments_tab.comment_actions"),
    );
  }

  #confirmDelete(comment) {
    this.confirm.open({
      message: t("executions.page.delete_subject_cannot_be_undone"),
      subject: t("tasks.comments_tab.comment_author", { author: comment.author }),
      onConfirm: async () => {
        try {
          await deleteComment(this.taskId, comment.id);
        } catch (error) {
          if (error.status !== 404) throw error; // gone already is what was wanted
        }
        this.comments = this.comments.filter((c) => c.id !== comment.id);
        this.#render();
        this.announce(t("tasks.comments_tab.comment_deleted"));
      },
      onClose: () => this.input.focus(),
    });
  }

  #syncSend() {
    this.send.setAttribute("aria-disabled", String(!canSend(this.input.value) || this.sending));
  }

  #setError(message) {
    this.error.textContent = message;
    this.error.hidden = !message;
  }

  async #submit() {
    if (this.sending || !canSend(this.input.value)) return;
    this.sending = true;
    this.#syncSend();
    this.#setError("");
    try {
      const made = await addComment(this.taskId, this.input.value);
      this.comments = withComment(this.comments, made); // the event may be here already: same id, same row
      this.input.value = "";
      this.#render({ scroll: true });
      this.input.focus();
    } catch (error) {
      this.#setError(error.fieldErrors?.body ?? error.message);
    } finally {
      this.sending = false;
      this.#syncSend();
    }
  }
}
