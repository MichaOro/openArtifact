/* One step as a list item, shared by the History tab and the flow page of an execution. Everything
 * is text (textContent, never innerHTML): output, reasons and data come from what ran. The markup is
 * the #history-step-template (templates/components/history_step_template.html). */
import { icon } from "../components/icons.js";
import { formatDuration, secondsBetween, setChip } from "./history-format.js";

const KIND_ICONS = { code: "code", http: "http", timer: "clock", trigger: "play", output: "check", if: "if", switch: "switch" };
const PORTS = { pass: "On Pass", fail: "On Fail", out: "Next", yes: "Yes", no: "No", else: "Else" };

/** How long a step took ("0.4 s"), null while it has not finished. */
export function stepDuration(step) {
  const seconds = secondsBetween(step.started_at, step.finished_at);
  return seconds == null || !step.finished_at ? null : formatDuration(seconds);
}

/** "On Pass", "Exit code: 0", "0.4 s" ... as one line. */
function stepFacts(step) {
  return [step.port ? `Port: ${PORTS[step.port] ?? step.port.replace(/^case_(\d)$/, "Case $1")}` : null, step.exit_code != null ? `Exit code: ${step.exit_code}` : null, stepDuration(step)].filter(Boolean);
}

/**
 * Fill a copy of the step template.
 * @param {HTMLTemplateElement} template
 * @param {object} step
 * @param {Set<string>} open keys of the blocks (`<step id>:output`, `<step id>:data`) the user had opened
 */
export function fillStep(template, step, open = new Set()) {
  const item = template.content.firstElementChild.cloneNode(true);
  item.dataset.stepId = step.id;
  item.dataset.outcome = step.outcome;
  item.dataset.kind = step.kind;
  item.style.setProperty("--depth", String(step.depth ?? 0));
  item.querySelector("[data-step-seq]").textContent = String(step.seq);
  item.querySelector("[data-step-kind-icon]").replaceChildren(icon(KIND_ICONS[step.kind] ?? "action"));
  item.querySelector("[data-step-name]").textContent = step.node_name ?? step.kind;
  item.querySelector("[data-step-kind]").textContent = step.kind;
  setChip(item.querySelector("[data-step-outcome]"), step.outcome);

  const where = [step.stage_name, step.action_name].filter(Boolean).join(" › ");
  const whereEl = item.querySelector("[data-step-where]");
  whereEl.textContent = where;
  whereEl.hidden = !where;

  const facts = stepFacts(step);
  const factsEl = item.querySelector("[data-step-facts]");
  factsEl.textContent = facts.join(" · ");
  factsEl.hidden = facts.length === 0;

  const reason = item.querySelector("[data-step-reason]");
  reason.textContent = step.reason ? `Reason: ${step.reason}` : "";
  reason.hidden = !step.reason;

  // the flow page leaves the output out and loads it when the block is opened (output_length says there is one)
  fillBlock(item.querySelector("[data-step-output]"), `${step.id}:output`, step.output, open, step.output || step.output_length > 0);
  item.querySelector("[data-step-truncated]").hidden = !step.output_truncated;
  const data = step.data == null ? "" : JSON.stringify(step.data, null, 2);
  fillBlock(item.querySelector("[data-step-data]"), `${step.id}:data`, data, open, Boolean(data));
  return item;
}

function fillBlock(details, key, text, open, present) {
  details.hidden = !present;
  details.dataset.key = key;
  details.open = open.has(key);
  details.querySelector("pre").textContent = text;
}
