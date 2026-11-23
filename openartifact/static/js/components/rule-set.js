/* A list of rules, each "if <conditions> then <action>": a rule builder per rule and a choice of what to do. Which fields
 * and actions exist is the schema's (rule-model.js), so retention of executions and, later, rules of lanes use the same
 * component. The set only holds the rules; what they mean is up to the page.
 *
 *   const set = new RuleSet(element, schema, { onChange: (rules) => ... });  set.load(rules);  set.read();
 */
import { icon } from "./icons.js";
import { RuleBuilder } from "./rule-builder.js";
import * as model from "./rule-model.js";
import { t } from "../i18n.js";

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

export class RuleSet {
  /**
   * @param {HTMLElement} root
   * @param {{fields: object[], actions: {key: string, label: string}[]}} schema
   * @param {{onChange?: (rules: object[]) => void, maxRules?: number}} [options]
   */
  constructor(root, schema, { onChange = () => {}, maxRules = 20 } = {}) {
    this.root = root;
    this.schema = schema;
    this.onChange = onChange;
    this.maxRules = maxRules;
    this.rules = [];
    root.classList.add("rs");
  }

  load(rules) {
    this.rules = (rules ?? []).map((r) => ({ when: r.when, action: r.action }));
    this.#draw();
  }

  read() {
    return this.rules;
  }

  #change(rules) {
    this.rules = rules;
    this.#draw();
    this.onChange(this.rules);
  }

  #draw() {
    const cards = this.rules.map((rule, i) => this.#card(rule, i));
    const add = make("button", "button button--ghost button--sm rs-add");
    add.type = "button";
    add.append(icon("plus"), document.createTextNode(t("components.rule_set.add_rule")));
    add.disabled = this.rules.length >= this.maxRules;
    add.addEventListener("click", () => this.#change([...this.rules, model.emptyRule(this.schema)]));
    const empty = this.rules.length ? [] : [make("p", "rb-empty", t("components.rule_set.no_rules_yet"))];
    this.root.replaceChildren(...cards, ...empty, add);
  }

  #card(rule, index) {
    const card = make("section", "rs-rule");
    card.setAttribute("aria-label", `Rule ${index + 1}`);
    const head = make("div", "rs-rule__head");
    const bin = make("button", "icon-button icon-button--sm is-danger");
    bin.type = "button";
    bin.title = t("components.rule_set.remove_rule", { number: index + 1 });
    bin.setAttribute("aria-label", t("components.rule_set.remove_rule", { number: index + 1 }));
    bin.append(icon("trash"));
    bin.addEventListener("click", () => this.#change(this.rules.filter((_, i) => i !== index)));
    head.append(make("h3", "rs-rule__title", `Rule ${index + 1}`), bin);

    const when = make("div", "rs-rule__when");
    const builder = new RuleBuilder(when, this.schema, {
      onChange: (tree) => {
        this.rules = this.rules.map((r, i) => (i === index ? { ...r, when: tree } : r));
        this.onChange(this.rules);
      },
    });
    builder.load(rule.when);

    const then = make("div", "rs-rule__then");
    const label = make("label", "rs-rule__label", t("components.rule_set.then"));
    const choice = make("select", "field__control rb-select");
    choice.id = `rs-action-${index}-${Math.random().toString(36).slice(2, 7)}`;
    label.htmlFor = choice.id;
    for (const action of this.schema.actions) choice.append(new Option(action.label, action.key));
    choice.value = rule.action;
    choice.addEventListener("change", () => {
      this.rules = this.rules.map((r, i) => (i === index ? { ...r, action: choice.value } : r));
      this.onChange(this.rules);
    });
    then.append(label, choice);

    card.append(head, make("p", "rs-rule__label", "If"), when, then);
    return card;
  }
}
