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
    const params = make("div", "rs-rule__params");
    choice.addEventListener("change", () => {
      const action = this.schema.actions.find((a) => a.key === choice.value);
      // an action with settings starts with its defaults; one without has none
      const change = { action: choice.value, params: action?.defaults ? { ...action.defaults } : undefined };
      this.onChange(action?.startsOff ? { ...change, enabled: false } : change);
      this.#drawParams(params, choice.value, change.params ?? {});
    });
    this.#drawParams(params, rule.action, rule.params ?? {});
    then.append(label, choice, params);

    this.root.replaceChildren(make("p", "rs-rule__label", t("components.rule_set.if")), when, then);
  }

  /** The settings of the chosen action (`action.params`: text, tone or mode), each a control that says `{params}`. */
  #drawParams(box, key, values) {
    const definitions = this.schema.actions.find((a) => a.key === key)?.params ?? [];
    let current = { ...values };
    const say = (name, value) => {
      current = { ...current, [name]: value };
      this.onChange({ params: current });
    };
    box.replaceChildren(
      ...definitions.map((def) => {
        const id = `rs-param-${Math.random().toString(36).slice(2, 7)}`;
        const wrap = make("div", "rs-rule__param");
        const label = make("label", "rs-rule__label", def.label);
        label.htmlFor = id;
        let control;
        if (def.kind === "text") {
          control = Object.assign(make("input", "field__control rb-text"), { type: "text", maxLength: def.max ?? 24, value: current[def.key] ?? "", autocomplete: "off" });
          control.addEventListener("input", () => say(def.key, control.value));
        } else {
          control = make("select", "field__control rb-select");
          for (const option of def.options) control.append(new Option(option.label, option.value));
          control.value = current[def.key] ?? def.options[0].value;
          control.addEventListener("change", () => say(def.key, control.value));
        }
        control.id = id;
        wrap.append(label, control);
        return wrap;
      }),
    );
  }
}
