/* The Mock tab of a node's window (ADR-087): the result the node hands over in a dry run instead of running. A switch (*Mock active*) and a form: outcome,
 * output, data (JSON) and reason. *Use the result of the last run* takes what the node left in its newest real run. Every change is saved at once, in the draft
 * only (a published version and a real run never hold a mock); a mistake in the data text is told in a plain line and nothing is sent until it is right. */
import { Switch, createSwitch } from "../components/switch.js";
import { icon } from "../components/icons.js";
import { field } from "./field.js";
import { formOf, mockOfResult, payloadOf } from "./mock-model.js";
import { t } from "../i18n.js";

let count = 0;

function make(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}

/**
 * @param {object} node the node (its `mock` is what is stored)
 * @param {{saveMock: (node: object, mock: object|null) => Promise<string|null>, lastResult: (node: object) => Promise<object>}} editor
 *   saveMock resolves to null or to why the server refused it
 */
export function mockPanel(node, editor) {
  const id = `ge-mock-${(count += 1)}`;
  const form = formOf(node);
  const wrap = make("div", "ge-mock");
  wrap.dataset.mockPanel = "";
  wrap.append(make("p", "ge-inspector__note", t("editor.mock.intro")));

  const error = make("p", "ge-mock__error");
  error.setAttribute("role", "alert");
  error.hidden = true;
  const showError = (text) => {
    error.textContent = text ?? "";
    error.hidden = !text;
  };

  const switchRow = make("div", "ge-mock__switch");
  const switchLabel = make("span", "field__label", t("editor.mock.active"));
  switchLabel.id = `${id}-active`;
  const button = createSwitch(switchLabel.id);
  button.dataset.focusKey = "mock-active";
  switchRow.append(switchLabel, button);

  const outcome = make("select", "field__control");
  outcome.dataset.focusKey = "mock-outcome";
  outcome.append(new Option(t("editor.mock.outcome_pass"), "pass"), new Option(t("editor.mock.outcome_fail"), "fail"));
  const output = make("textarea", "field__control ge-mock__text");
  output.rows = 4;
  output.dataset.focusKey = "mock-output";
  const data = make("textarea", "field__control ge-mock__text ge-mock__text--code");
  data.rows = 6;
  data.spellcheck = false;
  data.dataset.focusKey = "mock-data";
  const reason = make("input", "field__control");
  reason.type = "text";
  reason.dataset.focusKey = "mock-reason";

  const fill = (state) => {
    outcome.value = state.outcome;
    output.value = state.output;
    data.value = state.data;
    reason.value = state.reason;
    toggle.on = state.enabled;
  };
  const toggle = new Switch(button, { onChange: () => save() });

  const read = () => ({ enabled: toggle.on, outcome: outcome.value, output: output.value, data: data.value, reason: reason.value });

  const save = async () => {
    const body = payloadOf(read());
    if (body.error) return showError(body.error === "invalid" ? t("editor.mock.data_invalid") : t("editor.mock.data_not_object")); // nothing is sent while the data is not valid
    const refused = await editor.saveMock(node, body.mock);
    showError(refused);
    remove.disabled = !node.mock;
  };
  for (const control of [outcome, output, data, reason]) control.addEventListener("change", save);

  const useLast = make("button", "button button--ghost button--sm");
  useLast.type = "button";
  useLast.dataset.focusKey = "mock-use-last";
  useLast.append(icon("refresh"), document.createTextNode(t("editor.mock.use_last")));
  useLast.addEventListener("click", async () => {
    showError(null);
    try {
      const found = await editor.lastResult(node);
      if (!found.found) return showError(t("editor.mock.no_last_result"));
      const mock = { ...mockOfResult(found), enabled: toggle.on || node.mock?.enabled === true };
      const refused = await editor.saveMock(node, mock);
      if (refused) return showError(refused);
      fill(formOf({ mock }));
      remove.disabled = false;
    } catch {
      showError(t("editor.mock.last_result_failed"));
    }
  });

  const remove = make("button", "button button--ghost button--sm is-danger");
  remove.type = "button";
  remove.dataset.focusKey = "mock-remove";
  remove.append(icon("trash"), document.createTextNode(t("editor.mock.remove")));
  remove.disabled = !node.mock;
  remove.addEventListener("click", async () => {
    const refused = await editor.saveMock(node, null);
    showError(refused);
    if (!refused) fill(formOf({}));
    remove.disabled = !node.mock;
  });

  const bar = make("div", "ge-mock__bar");
  bar.append(useLast, remove);
  fill(form);
  wrap.append(
    switchRow,
    field(t("editor.mock.outcome"), outcome),
    field(t("editor.mock.output"), output),
    field(t("editor.mock.data"), data, { help: t("editor.mock.data_help") }),
    field(t("editor.mock.reason"), reason),
    error,
    bar,
  );
  return wrap;
}
