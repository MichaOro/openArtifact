/* The rules of a lane and of the board (ADR-071): one dialog in the frame of the retention rules (executions/retention-dialog.js):
 * the list of rules (a switch, a sentence, a chevron, a bin, "Add rule") and, after a click on one, that rule: "If" the
 * conditions (rule builder), "Then" the action with its settings and, beside them, a card drawn as the rule would draw it.
 * Hovering a rule in the list shows the same card in a small window with the number of cards the rule touches now.
 * Saving sends the whole list (`PUT /api/lanes/{status}/rules` or `/api/board/rules`); a board rule that deletes asks first,
 * with the number of cards it would delete. */
import { ActionDialog } from "../components/action-dialog.js";
import { RuleEditor } from "../components/rule-editor.js";
import { RuleList } from "../components/rule-list.js";
import { InlineName } from "../components/inline-name.js";
import { icon } from "../components/icons.js";
import * as listModel from "../components/rule-list-model.js";
import * as model from "../components/rule-model.js";
import { request } from "../http.js";
import { buildSchema } from "./card-rules-schema.js";
import { marksOfRule } from "./card-marks.js";
import { sampleCard } from "./card-sample.js";
import { t, tn } from "../i18n.js";

const PREVIEW_MS = 350;
const urls = (scope) => (scope.kind === "lane" ? { rules: `/api/lanes/${scope.status}/rules`, preview: `/api/lanes/${scope.status}/rules/preview`, schema: "/api/rules/schemas/lane" } : { rules: "/api/board/rules", preview: "/api/board/rules/preview", schema: "/api/rules/schemas/board" });

export class CardRulesDialog extends ActionDialog {
  /** @param {import("../components/modal.js").Modal} modal @param {{onSaved?: (scope: object) => void}} [hooks] */
  constructor(modal, { onSaved = () => {} } = {}) {
    super(modal, t("cards_rules.could_not_save"));
    this.onSaved = onSaved;
    this.form = this.root.querySelector("form");
    this.chip = this.root.querySelector("[data-modal-chip]");
    this.intro = this.root.querySelector("[data-intro]");
    this.label = this.root.querySelector("[data-submit-label]");
    this.listView = this.root.querySelector('[data-view="list"]');
    this.detailView = this.root.querySelector('[data-view="detail"]');
    this.count = this.root.querySelector("[data-rule-count]");
    this.sample = this.root.querySelector("[data-rule-sample]");
    this.warning = this.root.querySelector("[data-delete-warning]");
    this.sweep = this.root.querySelector("[data-sweep]");
    this.popover = this.root.querySelector("[data-popover]");
    this.index = -1; // the open rule, or -1 for the list
    this.scope = null;
    this.schema = null;
    this.timer = 0;
    this.turn = 0;
    this.counts = new Map(); // a rule as JSON -> how many cards it touches (asked once)
    this.confirmed = false; // the rules that delete were confirmed with the number they delete
    this.#buildHeader();
    this.list = null;
    this.editor = null;
    this.root.querySelector("[data-done]").addEventListener("click", () => this.#showList());
    this.root.querySelector("[data-sweep-now]").addEventListener("click", () => this.#previewNow());
    document.addEventListener(
      "keydown",
      (event) => {
        if (event.key !== "Escape" || this.index < 0 || !this.modal.isOpen) return;
        if (event.target.closest?.(".inline-name--editing")) return;
        event.preventDefault();
        event.stopPropagation();
        this.#showList();
      },
      true,
    );
    this.form.addEventListener("submit", async (event) => {
      event.preventDefault();
      this.asking = false;
      // saving closes the dialog, but asking "delete N cards?" leaves it open: the next click on Save is the answer
      if ((await this.run(() => this.#save(), { close: false })) && !this.asking) this.modal.close();
    });
    this.cancelButton.addEventListener("click", () => this.modal.close());
    this.modal.dialog.addEventListener("close", () => this.#hidePopover());
  }

  /**
   * @param {{kind: "lane", status: string, title: string, hue: string} | {kind: "board"}} scope
   * @param {{status: string, title: string}[]} lanes the board's lanes (the choices of the board's field "Lane")
   */
  async open(scope, lanes) {
    this.scope = scope;
    this.confirmed = false;
    this.counts.clear();
    const lane = scope.kind === "lane";
    this.lead.textContent = lane ? t("dialog.lane_settings") : t("cards_rules.board_settings");
    this.chip.hidden = !lane;
    if (lane) {
      this.chip.textContent = scope.title;
      this.chip.dataset.laneHue = scope.hue;
    }
    this.intro.textContent = lane ? t("cards_rules.intro_lane") : t("cards_rules.intro_board");
    this.sweep.hidden = lane;
    this.setError("");
    this.warning.hidden = true;
    this.index = -1;
    this.#showList(false);
    this.modal.open();
    try {
      const [server, stored] = await Promise.all([request(urls(scope).schema), request(urls(scope).rules)]);
      this.schema = buildSchema(server, { lanes });
      this.#mount();
      this.list.load(stored.rules);
      this.#changed();
      if (!lane) this.#loadLog();
    } catch {
      this.setError(t("cards_rules.could_not_load"));
    }
  }

  #mount() {
    this.list = new RuleList(this.root.querySelector("[data-rules]"), this.schema, { onChange: () => this.#changed(), onOpen: (index) => this.#openRule(index) });
    this.editor = new RuleEditor(this.root.querySelector("[data-rule-editor]"), this.schema, {
      onChange: (change) => {
        this.list.patch(this.index, change);
        this.#drawSample();
        this.#countRule();
      },
    });
    const rows = this.root.querySelector("[data-rules]");
    rows.addEventListener("mouseover", (event) => this.#hover(event.target.closest(".rl-row")));
    rows.addEventListener("focusin", (event) => this.#hover(event.target.closest(".rl-row")));
    rows.addEventListener("mouseleave", () => this.#hidePopover());
    rows.addEventListener("focusout", () => this.#hidePopover());
  }

  #showList(focus = true) {
    const was = this.index;
    this.index = -1;
    this.detailView.hidden = true;
    this.listView.hidden = false;
    this.#showTitle();
    if (focus && was >= 0) this.list?.focusRow(was);
  }

  #openRule(index) {
    this.#hidePopover();
    const rule = this.list.rules[index];
    this.index = index;
    this.listView.hidden = true;
    this.detailView.hidden = false;
    this.nameText.emptyText = listModel.labelOf({ name: "" }, index);
    this.nameText.setText(rule.name);
    this.#showTitle();
    this.editor.load(rule);
    this.#drawSample();
    this.#countRule();
    this.nameText.element.focus();
  }

  /** The header: "Lane settings" in the list; in an open rule "Lane settings – <name>" with the way back next to the close button. */
  #buildHeader() {
    const header = this.root.querySelector(".modal__header");
    this.title = header.querySelector(".modal__title");
    this.lead = Object.assign(document.createElement("span"), { className: "rl-title__lead", textContent: this.title.textContent });
    const sep = Object.assign(document.createElement("span"), { className: "rl-title__sep", textContent: " – " });
    sep.setAttribute("aria-hidden", "true");
    const name = Object.assign(document.createElement("span"), { className: "rl-title__name" });
    this.nameText = new InlineName(name, {
      label: t("components.rule_list.rule_name"),
      maxLength: 80,
      allowEmpty: true,
      onCommit: (value) => {
        this.list.patch(this.index, { name: value });
        this.nameText.setText(value);
      },
    });
    this.titleParts = [sep, name];
    this.title.classList.add("rl-title");
    this.title.replaceChildren(this.lead);
    this.back = Object.assign(document.createElement("button"), { type: "button", className: "button button--ghost button--sm rl-back", hidden: true });
    this.back.setAttribute("aria-label", t("components.rule_list.back_to_rules"));
    this.back.append(icon("chevron-left"), Object.assign(document.createElement("span"), { textContent: t("components.rule_list.rules") }));
    header.insertBefore(this.back, header.querySelector("[data-modal-close]"));
    this.back.addEventListener("click", () => this.#showList());
  }

  #showTitle() {
    const open = this.index >= 0;
    this.title.replaceChildren(this.lead, ...(open ? this.titleParts : []));
    this.back.hidden = !open;
  }

  // ── the preview of a rule: a card drawn as the rule draws it, and how many cards the rule touches now ──

  #drawSample() {
    const rule = this.list.rules[this.index];
    this.sample.replaceChildren(sampleCard(marksOfRule(rule)));
  }

  async #countOf(rule) {
    const key = JSON.stringify({ when: rule.when, action: rule.action, params: rule.params ?? null });
    if (!this.counts.has(key)) {
      const found = await request(urls(this.scope).preview, { method: "POST", body: JSON.stringify({ rule: { when: rule.when, action: rule.action, params: rule.params ?? {}, enabled: true } }) });
      this.counts.set(key, found);
    }
    return this.counts.get(key);
  }

  async #countRule() {
    const rule = this.list.rules[this.index];
    const turn = (this.turn += 1);
    window.clearTimeout(this.timer);
    this.count.textContent = "";
    if (!model.isComplete(rule.when, this.schema)) return;
    this.timer = window.setTimeout(async () => {
      try {
        const found = await this.#countOf(rule);
        if (turn !== this.turn || this.index < 0) return;
        this.count.textContent = tn("cards_rules.rule_touches", found.count);
      } catch {
        /* the number is a convenience */
      }
    }, PREVIEW_MS);
  }

  #hover(row) {
    if (!row || row.dataset.state === "removed") return this.#hidePopover();
    const rule = this.list.rules[Number(row.dataset.row)];
    if (!rule || this.popoverRow === row) return;
    this.popoverRow = row;
    const turn = (this.hoverTurn = (this.hoverTurn ?? 0) + 1);
    this.popover.querySelector("[data-popover-card]").replaceChildren(sampleCard(marksOfRule(rule)));
    const caption = this.popover.querySelector("[data-popover-caption]");
    caption.textContent = t("cards_rules.preview_caption");
    this.popover.hidden = false;
    const box = row.getBoundingClientRect();
    Object.assign(this.popover.style, { top: `${Math.round(box.bottom + 4)}px`, left: `${Math.round(box.left)}px` });
    if (!model.isComplete(rule.when, this.schema)) return;
    this.#countOf(rule)
      .then((found) => {
        if (turn === this.hoverTurn && !this.popover.hidden) caption.textContent = `${t("cards_rules.preview_caption")} · ${tn("cards_rules.rule_touches", found.count)}`;
      })
      .catch(() => {});
  }

  #hidePopover() {
    this.popoverRow = null;
    this.hoverTurn = (this.hoverTurn ?? 0) + 1;
    this.popover.hidden = true;
  }

  // ── the board's pass and its log ──

  async #previewNow() {
    const text = this.root.querySelector("[data-sweep-text]");
    try {
      const pass = await request("/api/board/rules/sweep?dry_run=true", { method: "POST" });
      text.textContent = t("cards_rules.sweep_result", { archive: pass.archive, delete: pass.delete, spared: pass.spared });
    } catch {
      text.textContent = t("cards_rules.could_not_load");
    }
  }

  async #loadLog() {
    const list = this.root.querySelector("[data-log-list]");
    try {
      const rows = await request("/api/board/rules/deletions");
      list.replaceChildren(
        ...(rows.length
          ? rows.map((row) => Object.assign(document.createElement("li"), { textContent: t("cards_rules.log_row", { number: row.number ?? "–", title: row.title, lane: row.lane, rule: row.rule, at: new Date(row.at).toLocaleString() }) }))
          : [Object.assign(document.createElement("li"), { textContent: t("cards_rules.log_empty") })]),
      );
    } catch {
      list.replaceChildren();
    }
  }

  // ── saving ──

  /** A rule changed: the Save button needs every condition finished. */
  #changed() {
    const rules = listModel.kept(this.list.rules);
    const complete = rules.every((r) => model.isComplete(r.when, this.schema));
    // a rule that deletes must name what it deletes: the server refuses one that holds for every card
    const open = rules.some((r) => r.action === "delete" && r.enabled && !r.when.items.length);
    this.submitButton.disabled = !complete || open;
    this.confirmed = false;
    this.warning.hidden = true;
    this.label.textContent = t("common.save");
    this.setError(!complete ? t("cards_rules.complete_every_condition") : open ? t("cards_rules.delete_needs_condition") : "");
  }

  async #save() {
    const rules = listModel.kept(this.list.rules);
    const deleting = rules.filter((r) => r.enabled && r.action === "delete");
    if (deleting.length && !this.confirmed) {
      let total = 0;
      for (const rule of deleting) total += (await this.#countOf(rule)).count;
      this.confirmed = true;
      this.warning.textContent = tn("cards_rules.confirm_delete", total);
      this.warning.hidden = false;
      this.label.textContent = t("cards_rules.save_and_delete");
      this.asking = true;
      return;
    }
    await request(urls(this.scope).rules, { method: "PUT", body: JSON.stringify({ rules }) });
    this.onSaved(this.scope);
  }
}
