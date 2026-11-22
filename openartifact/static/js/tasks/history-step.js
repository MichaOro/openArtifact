/* One step as a list item, shared by the History tab and the flow page of an execution. Everything
 * is text (textContent, never innerHTML): output, reasons and data come from what ran. The markup is
 * the #history-step-template (templates/components/history_step_template.html). */
import { agentFacts } from "../agents/model.js";
import { detailView } from "../agents/view.js";
import { icon } from "../components/icons.js";
import { formatDuration, secondsBetween, setChip } from "./history-format.js";

const KIND_ICONS = { code: "code", http: "http", timer: "clock", trigger: "play", output: "check", if: "if", switch: "switch", agent: "agent" };
const PORTS = { pass: "On Pass", fail: "On Fail", out: "Next", yes: "Yes", no: "No", else: "Else" };

/** How long a step took ("0.4 s"), null while it has not finished. */
export function stepDuration(step) {
  const seconds = secondsBetween(step.started_at, step.finished_at);
  return seconds == null || !step.finished_at ? null : formatDuration(seconds);
}

/** "On Pass", "Exit code: 0", "0.4 s" ... as one line. */
function stepFacts(step) {
  const facts = [step.port ? `Port: ${PORTS[step.port] ?? step.port.replace(/^case_(\d)$/, "Case $1")}` : null, step.exit_code != null ? `Exit code: ${step.exit_code}` : null, stepDuration(step)];
  if (step.kind === "agent") facts.push(...agentFacts(step.data)); // model, tokens and attempts at a glance
  if (step.data?.output_truncated) facts.push("Output cut at the limit of a step");
  return facts.filter(Boolean);
}

/**
 * Fill a copy of the step template.
 * @param {HTMLTemplateElement} template
 * @param {object} step
 * @param {Set<string>} open keys of the blocks (`<step id>:output`, `<step id>:data`) the user had opened
 * @param {{loadDetail?: (step: object) => Promise<object>}} [options] loadDetail: the step read alone, with its
 *   `detail` (an agent step's prompts and attempts are not part of any list; they are fetched when the block opens)
 */
export function fillStep(template, step, open = new Set(), { loadDetail = null } = {}) {
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
  fillAgent(item.querySelector("[data-step-agent]"), step, open, loadDetail);
  return item;
}

/** The block of an agent step: what was sent and every attempt, loaded when it is opened. */
function fillAgent(details, step, open, loadDetail) {
  if (!details) return; // a page with an older template
  const present = step.kind === "agent" && Boolean(loadDetail);
  details.hidden = !present;
  if (!present) return;
  details.dataset.key = `${step.id}:agent`;
  const body = details.querySelector("[data-step-agent-body]");
  let loaded = false;
  const load = async () => {
    if (loaded) return;
    loaded = true;
    body.textContent = "Loading...";
    try {
      body.replaceChildren(detailView((await loadDetail(step)).detail));
    } catch {
      loaded = false;
      body.textContent = "The request could not be loaded. Close and open it to try again.";
    }
  };
  details.addEventListener("toggle", () => details.open && load());
  details.open = open.has(details.dataset.key);
  if (details.open) load();
}

function fillBlock(details, key, text, open, present) {
  details.hidden = !present;
  details.dataset.key = key;
  details.open = open.has(key);
  details.querySelector("pre").textContent = text;
}
