/* The few things a node kind's manifest may name instead of describing (ADR-054): captions and rules that need more than a
 * template. A manifest chooses among these by name (`ui.caption.fn`, a port's `visible_when.fn` and `label_from`, `ui.size_fn`,
 * `ui.group_used_fn`); the names a manifest may use are `CLIENT_FUNCTIONS` in graph/manifest.py, and a test keeps both lists equal. */
import { overridesOf } from "../agents/model.js";
import { short } from "./caption.js";

/** The names of the agents by id, for the caption of an agent node (filled by `rememberAgents`). */
export const agentNames = new Map();

/** Operators that look at the value only (mirror of UNARY_OPERATORS, graph/node_types.py). */
const UNARY = ["is empty", "is not empty", "is true", "is false"];
const OPERATOR_SIGNS = { "not equals": "≠", "greater than": ">", "less than": "<", "greater or equal": "≥", "less or equal": "≤" };

/** Whether a Switch case is in use: a value, or an operator that needs none (mirror of switch_case_used). */
export function switchCaseUsed(config, port) {
  const operator = config?.[`case_operator_${port.slice(5)}`] ?? "equals";
  return UNARY.includes(operator) || (config?.[port] ?? "").trim() !== "";
}

const usedCases = (node) => [1, 2, 3, 4, 5, 6].filter((n) => switchCaseUsed(node.config, `case_${n}`));

export const FUNCTIONS = {
  caption: {
    /** The first condition and how many more there are. */
    if_summary(node) {
      const config = node.config ?? {};
      const used = [1, 2, 3, 4, 5].filter((n) => (config[`left_${n}`] ?? "").trim() !== "");
      if (!used.length) return "no condition yet";
      const n = used[0];
      const operator = config[`operator_${n}`] ?? "equals";
      const unary = UNARY.includes(operator);
      const first = short(`${config[`left_${n}`]} ${operator}${unary ? "" : ` ${config[`right_${n}`] ?? ""}`}`.trim());
      return used.length > 1 ? `${first} +${used.length - 1} more` : first;
    },
    /** The value and the number of cases. */
    switch_summary(node) {
      const value = (node.config?.value ?? "").trim();
      const cases = usedCases(node).length;
      return `${value ? short(value) : "no value yet"} · ${cases} ${cases === 1 ? "case" : "cases"}`;
    },
    /** The agent's name and how many settings the node overrides. */
    agent_summary(node, view) {
      const id = node.config?.agent_id;
      if (!id) return "no agent yet";
      const own = overridesOf(node.config, view.settings).length;
      // an execution's frozen node carries its agent; the editor knows the names of the list
      return `${node.agent?.name ?? agentNames.get(id) ?? "agent"}${own ? ` · ${own} override${own === 1 ? "" : "s"}` : ""}`;
    },
  },
  /** The ports of unused cases are not there; Else always is. */
  visible: {
    switch_case_used: (node, port) => !port.startsWith("case_") || switchCaseUsed(node.config, port),
  },
  /** A case is shown by its condition as the user wrote it: the value, or the operator before it when it is not
   * "equals" ("> 10", "contains urgent", "is empty"); null: the port's own label. */
  label: {
    switch_case_label(node, port) {
      const value = node.config?.[port]?.trim() ?? "";
      const operator = node.config?.[`case_operator_${port.slice(5)}`] ?? "equals";
      const text = operator === "equals" ? value : `${OPERATOR_SIGNS[operator] ?? operator} ${UNARY.includes(operator) ? "" : value}`.trim();
      return text ? short(text) : null;
    },
  },
  /** The card grows with its visible outputs. */
  size: {
    switch_size(node, view) {
      const visible = view.outputs.filter((p) => view.isVisible(node, p.name)).length;
      return { width: 250, height: Math.max(84, 26 * visible + 20) };
    },
  },
  /** A case group of the dialog is open when the case is in use; null: the kind does not know. */
  group_used: {
    switch_group_used(node, group) {
      const n = group.match(/^Case (\d)$/)?.[1];
      return n ? switchCaseUsed(node.config, `case_${n}`) : null;
    },
  },
};
