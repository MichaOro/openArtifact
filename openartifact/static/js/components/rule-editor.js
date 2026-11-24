/* One rule, "if <conditions> then <action>": a rule builder for the conditions and a choice of what to do. Which fields
 * and actions exist is the schema's (rule-model.js), so retention of executions, guards and, later, lanes use the same
 * component. The editor holds no list and no state of its own: it draws the rule it is given and says what the user
 * changed (`{when}` or `{action}`); the list around it (rule-list.js) and the page decide what that means.
 *
 *   const editor = new RuleEditor(element, schema, { onChange: (change) => ... });  editor.load(rule);
 */
import { RuleBuilder } from "./rule-builder.js";
import { t } from "../i18n.js";

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

export class RuleEditor {
  /**
   * @param {HTMLElement} root
   * @param {{fields: object[], actions: {key: string, label: string}[]}} schema
   * @param {{onChange?: (change: {when?: object, action?: string}) => void}} [options]
   */
  constructor(root, schema, { onChange = () => {} } = {}) {
    this.root = root;
    this.schema = schema;
    this.onChange = onChange;
    root.classList.add("rs-rule");
  }

  /** @param {{when: object, action: string}} rule */
  load(rule) {
    const when = make("div", "rs-rule__when");
    const builder = new RuleBuilder(when, this.schema, { onChange: (tree) => this.onChange({ when: tree }) });
    builder.load(rule.when);

    const then = make("div", "rs-rule__then");
    const label = make("label", "rs-rule__label", t("components.rule_set.then"));
    const choice = make("select", "field__control rb-select");
    choice.id = `rs-action-${Math.random().toString(36).slice(2, 7)}`;
    label.htmlFor = choice.id;
    for (const action of this.schema.actions) choice.append(new Option(action.label, action.key));
    choice.value = rule.action;
    choice.addEventListener("change", () => this.onChange({ action: choice.value }));
    then.append(label, choice);

    this.root.replaceChildren(make("p", "rs-rule__label", "If"), when, then);
  }
}
