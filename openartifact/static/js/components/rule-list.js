/* A list of rules, one row each, with the switch that turns a rule on or off: the front door of a rule set. A row says
 * the rule's name (or "Rule N") and in one line what it does; a click opens the rule (the page shows the editor, see
 * rule-editor.js), the switch turns it on or off, and a rule can be taken out: it stays in the list marked "Will be
 * removed when you save", with Undo, until the page saves. The data and its changes are rule-list-model.js; what the
 * rules mean is up to the page.
 *
 *   const list = new RuleList(element, schema, { onChange: (rules) => ..., onOpen: (index) => ... });
 *   list.load(storedRules);  list.rules  // [{when, action, name, enabled, removed?}]
 *   list.patch(index, { name })  // from the page, when the open rule changed;  list.add(rule)  // opens it
 */
import { icon } from "./icons.js";
import { createSwitch, Switch } from "./switch.js";
import * as model from "./rule-list-model.js";
import { emptyRule } from "./rule-model.js";
import { t } from "../i18n.js";

let counter = 0;

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

export class RuleList {
  /**
   * @param {HTMLElement} root
   * @param {object} schema the rule schema (fields, actions), for the one-line summaries and a new rule
   * @param {{onChange?: (rules: object[]) => void, onOpen?: (index: number) => void, maxRules?: number}} [options]
   */
  constructor(root, schema, { onChange = () => {}, onOpen = () => {}, maxRules = 20 } = {}) {
    this.root = root;
    this.schema = schema;
    this.onChange = onChange;
    this.onOpen = onOpen;
    this.maxRules = maxRules;
    this.rules = [];
    root.classList.add("rl");
  }

  load(rules) {
    this.rules = model.normalize(rules);
    this.#draw();
  }

  /** A change from outside (the open rule's name, switch or conditions): the row follows. */
  patch(index, change) {
    this.rules = model.patch(this.rules, index, change);
    this.#draw();
    this.onChange(this.rules);
  }

  /** Add a rule (on, no conditions yet) and open it. */
  add(rule = emptyRule(this.schema)) {
    const before = this.rules.length;
    this.rules = model.append(this.rules, rule, this.maxRules);
    if (this.rules.length === before) return;
    this.#draw();
    this.onChange(this.rules);
    this.onOpen(this.rules.length - 1);
  }

  /** Put the focus on the button that opens a rule (after coming back from it). */
  focusRow(index) {
    this.root.querySelector(`[data-row="${index}"] .rl-row__open, [data-row="${index}"] [data-undo]`)?.focus();
  }

  #change(rules) {
    this.rules = rules;
    this.#draw();
    this.onChange(this.rules);
  }

  #draw() {
    const rows = this.rules.map((rule, index) => this.#row(rule, index));
    const add = make("button", "button button--ghost button--sm rl-add");
    add.type = "button";
    add.append(icon("plus"), document.createTextNode(t("components.rule_set.add_rule")));
    add.disabled = this.rules.length >= this.maxRules;
    add.addEventListener("click", () => this.add());
    const list = make("ul", "rl-rows");
    list.setAttribute("aria-label", t("components.rule_list.rules"));
    list.append(...rows);
    const empty = this.rules.length ? [] : [make("p", "rb-empty", t("components.rule_set.no_rules_yet"))];
    this.root.replaceChildren(...(rows.length ? [list] : []), ...empty, add);
  }

  #row(rule, index) {
    const item = make("li", "rl-row");
    item.dataset.row = String(index);
    const label = model.labelOf(rule, index);
    const nameId = `rl-name-${(counter += 1)}`;

    if (rule.removed) {
      item.dataset.state = "removed";
      const text = make("div", "rl-row__text");
      text.append(make("span", "rl-row__name", label), make("span", "rl-row__summary", t("components.rule_list.will_be_removed")));
      const undo = make("button", "button button--ghost button--sm", t("components.rule_list.undo"));
      undo.type = "button";
      undo.dataset.undo = "";
      undo.addEventListener("click", () => this.#change(model.restore(this.rules, index)));
      item.append(text, undo);
      return item;
    }

    const summary = model.summaryOf(rule, this.schema);
    item.dataset.state = !rule.enabled ? "off" : summary.state === "ok" ? "on" : summary.state;

    const toggle = createSwitch(nameId);
    const sw = new Switch(toggle, { onChange: (on) => this.#change(model.setEnabled(this.rules, index, on)) });
    sw.on = rule.enabled;

    const open = make("button", "rl-row__open");
    open.type = "button";
    open.dataset.ui = "custom";
    open.dataset.uiReason = "a whole row that opens its rule";
    open.setAttribute("aria-label", t("components.rule_list.open_rule", { name: label }));
    const text = make("span", "rl-row__text");
    const name = make("span", "rl-row__name", label);
    name.id = nameId;
    const line = make("span", "rl-row__summary", summary.text);
    line.title = summary.text;
    text.append(name, line);
    open.append(text, icon("chevron-right"));
    open.addEventListener("click", () => this.onOpen(index));

    const bin = make("button", "icon-button icon-button--sm is-danger");
    bin.type = "button";
    bin.title = t("components.rule_set.remove_rule", { number: index + 1 });
    bin.setAttribute("aria-label", t("components.rule_set.remove_rule", { number: index + 1 }));
    bin.append(icon("trash"));
    bin.addEventListener("click", () => this.#change(model.removeStaged(this.rules, index)));

    item.append(toggle, open, bin);
    return item;
  }
}
