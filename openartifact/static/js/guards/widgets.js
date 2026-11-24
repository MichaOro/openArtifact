/* The widgets the guard editor registers for its form manifest (ui/forms/guard.yaml, ADR-062): what the built-in widgets
 * of components/form-widgets.js cannot be. `rule-tree` is the rule builder over the guard schema, `escalation-steps`
 * the rows "from firing k, every N rounds or seconds", `action-picker` the guard's own action (choose one, make a new
 * one, edit it in the action editor). The window hands them what they need as the form's `context`:
 * {ruleSchema, actions, newAction(), editAction()}. */
import { icon } from "../components/icons.js";
import { registerWidget } from "../components/form-widgets.js";
import { RuleBuilder } from "../components/rule-builder.js";
import { t } from "../i18n.js";

const MAX_STEPS = 10;

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

function number(value, min, label) {
  const input = Object.assign(make("input", "field__control gd-number"), { type: "number", min, step: 1, value: String(value) });
  input.setAttribute("aria-label", label);
  return input;
}

function select(options, value, label) {
  const el = make("select", "field__control");
  for (const [key, text] of options) el.append(new Option(text, key));
  el.value = value;
  el.setAttribute("aria-label", label);
  return el;
}

registerWidget("rule-tree", (ctx) => {
  const host = make("div");
  const builder = new RuleBuilder(host, ctx.context.ruleSchema, { onChange: (tree) => ctx.set(tree) });
  builder.load(ctx.value);
  return { el: host, control: null };
});

registerWidget("escalation-steps", (ctx) => {
  const steps = ctx.value ?? [];
  const root = make("div", "gd-steps-wrap");
  const commit = () => ctx.set(structuredClone(steps));
  const draw = () => {
    const table = make("div", "gd-steps");
    steps.forEach((step, i) => {
      const row = make("div", "gd-step");
      row.setAttribute("role", "group");
      row.setAttribute("aria-label", t("guards.step_n", { n: i + 1 }));
      const from = number(step.from_firing, 1, t("guards.from_firing"));
      from.addEventListener("input", () => {
        step.from_firing = Math.max(1, Math.round(Number(from.value) || 1));
        commit();
      });
      const unit = step.every_runs != null ? "runs" : "seconds";
      const amount = number(step.every_runs ?? step.every_seconds ?? 1, 1, t("guards.every_amount"));
      const kind = select([["runs", t("guards.rounds")], ["seconds", t("components.rule_builder.units.seconds")]], unit, t("guards.every_unit"));
      const update = () => {
        const n = Math.max(1, Math.round(Number(amount.value) || 1));
        delete step.every_runs;
        delete step.every_seconds;
        step[kind.value === "runs" ? "every_runs" : "every_seconds"] = n;
        commit();
      };
      amount.addEventListener("input", update);
      kind.addEventListener("change", update);
      const bin = make("button", "icon-button icon-button--sm is-danger");
      bin.type = "button";
      bin.setAttribute("aria-label", t("guards.remove_step"));
      bin.title = t("guards.remove_step");
      bin.append(icon("trash"));
      bin.addEventListener("click", () => {
        steps.splice(i, 1);
        commit();
        draw();
      });
      row.append(make("span", "gd-step__text", t("guards.from_firing")), from, make("span", "gd-step__text", t("guards.every")), amount, kind, bin);
      table.append(row);
    });
    const add = make("button", "button button--ghost button--sm");
    add.type = "button";
    add.append(icon("plus"), document.createTextNode(t("guards.add_step")));
    add.disabled = steps.length >= MAX_STEPS;
    add.addEventListener("click", () => {
      const last = steps.at(-1);
      steps.push({ from_firing: last ? last.from_firing + 1 : 1, every_runs: 5 });
      commit();
      draw();
    });
    root.replaceChildren(table, add);
  };
  draw();
  return { el: root, control: null };
});

registerWidget("action-picker", (ctx) => {
  const root = make("div", "gd-logic");
  if (ctx.get("consequence") !== "run_action") {
    const use = make("button", "button button--ghost button--sm");
    use.type = "button";
    use.dataset.useAction = "";
    use.append(icon("action"), document.createTextNode(t("guards.use_action")));
    use.addEventListener("click", () => {
      ctx.set("run_action", "consequence");
      ctx.form.focus("action_id");
    });
    root.append(make("p", "field__help", t("guards.logic_off")), use);
    return { el: root, control: null };
  }
  const chooser = select([["", t("guards.action_none")], ...ctx.context.actions.map((a) => [a.id, a.name])], ctx.value ?? "", ctx.field.label);
  chooser.id = ctx.id;
  chooser.dataset.guardAction = "";
  chooser.dataset.fieldKey = ctx.field.key;
  chooser.removeAttribute("aria-label");
  chooser.addEventListener("change", () => ctx.set(chooser.value || null));
  const bar = make("div", "ge-actionbar gd-actionbar");
  const newButton = make("button", "button button--ghost button--sm");
  newButton.type = "button";
  newButton.dataset.newAction = "";
  newButton.append(icon("plus"), document.createTextNode(t("common.new")));
  newButton.addEventListener("click", () => ctx.context.newAction());
  const edit = make("button", "button button--ghost button--sm");
  edit.type = "button";
  edit.dataset.editAction = "";
  edit.append(icon("pencil"), document.createTextNode(t("common.edit")));
  edit.title = t("guards.edit_saves_first");
  edit.addEventListener("click", () => ctx.context.editAction());
  bar.append(newButton, edit);
  root.append(chooser, make("p", "field__help", ctx.value ? t("guards.edit_saves_first") : t("guards.action_made_on_save")), bar);
  return { el: root, control: chooser };
});
