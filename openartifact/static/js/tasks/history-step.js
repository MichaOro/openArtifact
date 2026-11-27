/* One step as a list item, shared by the History tab and the flow page of an execution. Everything
 * is text (textContent, never innerHTML): output, reasons and data come from what ran. The markup is
 * the #history-step-template (templates/components/history_step_template.html). */
import { agentFacts } from "../agents/model.js";
import { detailView } from "../agents/view.js";
import { attachCopy } from "../components/copy-button.js";
import { icon } from "../components/icons.js";
import { skipMarker } from "../components/skip-marker.js";
import { mockOfStep } from "../editor/mock-model.js";
import { formatBytes } from "../editor/sources-model.js";
import { request } from "../http.js";
import { formatDuration, secondsBetween, setChip } from "./history-format.js";
import { t } from "../i18n.js";

const PORTS = { pass: t("tasks.history_step.pass"), fail: t("tasks.history_step.fail"), out: t("tasks.history_step.next"), yes: t("tasks.field_rail.yes"), no: "No", else: t("tasks.history_step.else") };

/** How long a step took ("0.4 s"), null while it has not finished. */
export function stepDuration(step) {
  const seconds = secondsBetween(step.started_at, step.finished_at);
  return seconds == null || !step.finished_at ? null : formatDuration(seconds);
}

/** "On Pass", "Exit code: 0", "0.4 s" ... as one line. */
function stepFacts(step) {
  const facts = [step.port ? `Port: ${PORTS[step.port] ?? step.port.replace(/^case_(\d)$/, "Case $1")}` : null, step.exit_code != null ? `Exit code: ${step.exit_code}` : null, stepDuration(step)];
  if (step.kind === "agent") facts.push(...agentFacts(step.data), ...handoverFacts(step.data), ...answerFacts(step.data)); // model, tokens and attempts at a glance, the documents handed over
  if (step.kind === "context") facts.push(...contextFacts(step.data)); // how full the package is
  if (step.data?.output_truncated) facts.push(t("tasks.history_step.output_cut_at_limit_step"));
  if (step.attempts > 1) facts.push(t("tasks.history_step.tries_fact", { n: step.attempts })); // Retry on fail (ADR-073)
  return facts.filter(Boolean);
}

/** "Handed over: Review" for an agent step whose Hand Over Tools accepted a document (ADR-080); the documents are in the data below. */
export function handoverFacts(data) {
  const names = data?.handovers ? Object.keys(data.handovers) : [];
  return names.length ? [t("tasks.history_step.handed_over", { names: names.join(", ") })] : [];
}

/** "Answer reported" or "Answer reported, corrected once" for an agent step with an answer format (ADR-085); the fields are in the data below. */
export function answerFacts(data) {
  if (!data || !data.answer_calls) return [];
  return [data.repaired ? t("tasks.history_step.answer_repaired") : t("tasks.history_step.answer_reported")];
}

/** "Package 5.1 KiB of 8 KiB (about 1,300 tokens)" for a Build Context step (ADR-078); nothing for data that is not its. */
export function contextFacts(data) {
  if (!data || !Array.isArray(data.included)) return [];
  return [t("tasks.history_step.context_size", { size: formatBytes(data.size_bytes), limit: formatBytes(data.limit_bytes), tokens: data.approx_tokens ?? 0 })];
}

/** The lines of what a Build Context step put in the package and what it left out, as text (the order of the sources). */
export function contextLines(data) {
  if (!data || !Array.isArray(data.included)) return null;
  const included = data.included.map((part) => {
    const of = part.available > part.items ? t("tasks.history_step.context_of", { items: part.items, available: part.available }) : t("tasks.history_step.context_all", { items: part.items });
    const cut = part.cut ? ` · ${t("tasks.history_step.context_cut", { n: part.cut })}` : "";
    return `${t(`editor.sources.source.${part.source}.label`)}: ${of} (${formatBytes(part.bytes)})${cut}`;
  });
  const omitted = (data.omitted ?? []).map((part) => `${t(`editor.sources.source.${part.source}.label`)}: ${part.reason}`);
  return { included, omitted };
}

/** What a Build Context step shows without being opened: what went into the package and what was left out, and why. */
function fillContext(box, step) {
  if (!box) return; // a page with an older template
  const lines = step.kind === "context" ? contextLines(step.data) : null;
  box.hidden = !lines;
  if (!lines) return;
  box.querySelector("[data-step-context-title]").textContent = t("tasks.history_step.context_in");
  const list = (selector, items) => box.querySelector(selector).replaceChildren(...items.map((text) => Object.assign(document.createElement("li"), { textContent: text })));
  list("[data-step-context-included]", lines.included);
  box.querySelector("[data-step-context-omitted-title]").textContent = lines.omitted.length ? t("tasks.history_step.context_left_out") : "";
  list("[data-step-context-omitted]", lines.omitted);
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
  item.querySelector("[data-step-kind-icon]").replaceChildren(icon(step.icon ?? "action"));
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
  // a step an observed run could not see (ADR-088) is passed: its line says so quietly, it is no reason of a failure
  const quiet = Boolean(step.data?.not_observable);
  reason.textContent = step.reason ? (quiet ? step.reason : t("tasks.history_step.reason_reason", { reason: step.reason })) : "";
  reason.hidden = !step.reason;
  if (quiet) reason.dataset.notObservable = "";
  else delete reason.dataset.notObservable;

  // the flow page leaves the output out and loads it when the block is opened (output_length says there is one)
  fillBlock(item.querySelector("[data-step-output]"), `${step.id}:output`, step.output, open, step.output || step.output_length > 0);
  item.querySelector("[data-step-truncated]").hidden = !step.output_truncated;
  const data = step.data == null ? "" : JSON.stringify(step.data, null, 2);
  fillBlock(item.querySelector("[data-step-data]"), `${step.id}:data`, data, open, Boolean(data));
  fillMock(item, step, loadDetail);
  fillSkip(item, step);
  fillContext(item.querySelector("[data-step-context]"), step);
  fillAgent(item.querySelector("[data-step-agent]"), step, open, loadDetail);
  fillTries(item.querySelector("[data-step-tries]"), step, open, loadDetail);
  return item;
}

/** The skip marker beside the outcome of a step a dry run (or an observed run) skipped: the icon with what it would have done as its tooltip. The
 * wording of the step stays as it was; a mocked step never has it (ADR-086 addendum 3). */
function fillSkip(item, step) {
  const slot = item.querySelector("[data-step-skip]");
  if (!slot) return; // a page with an older template
  const marker = skipMarker(step);
  slot.replaceChildren(...(marker ? [marker] : []));
  slot.hidden = !marker;
}

/** The kinds that take no mock (the server refuses them as well). */
const NO_MOCK = new Set(["trigger", "output", "complete", "stage", "action", "pipeline", "if", "switch", "timer"]);

/** The *Mock* flag of a step that handed over a mock, and *Keep as mock* on a step with a real result: it sets that result as the mock of the node in the
 * current DRAFT of the action (ADR-087). A step a dry run skipped or mocked has no real result, so it offers nothing. */
function fillMock(item, step, loadDetail) {
  const flag = item.querySelector("[data-step-mock]");
  if (flag) flag.hidden = !step.data?.mock;
  const box = item.querySelector("[data-step-keep]");
  if (!box) return; // a page with an older template
  const real = !NO_MOCK.has(step.kind) && !step.data?.mock && !step.data?.dry_run && Boolean(step.definition_id) && Boolean(step.node_id);
  box.hidden = !real;
  if (!real) return;
  const note = box.querySelector("[data-step-keep-note]");
  box.querySelector("[data-step-keep-mock]").addEventListener("click", async () => {
    note.textContent = "";
    try {
      const full = loadDetail ? await loadDetail(step) : step; // the list may leave the output out
      await request(`/api/actions/${encodeURIComponent(step.definition_id)}/nodes/${encodeURIComponent(step.node_id)}`, { method: "PATCH", body: JSON.stringify({ mock: mockOfStep({ ...step, ...full }) }) });
      note.textContent = t("tasks.history_step.mock_kept");
    } catch (error) {
      note.textContent = t("tasks.history_step.mock_not_kept", { reason: error.detail ?? error.message });
    }
  });
}

/** A node that was tried again (*Retry on fail*, ADR-073) lists its tries when the block is opened: the failed ones with their
 * reason and time (the step's `detail.tries`, which a list does not carry), then how the last one ended. */
function fillTries(details, step, open, loadDetail) {
  if (!details) return; // a page with an older template
  const present = step.attempts > 1 && Boolean(loadDetail);
  details.hidden = !present;
  if (!present) return;
  details.dataset.key = `${step.id}:tries`;
  details.querySelector("[data-step-tries-summary]").textContent = t("tasks.history_step.tries_summary", { n: step.attempts });
  const body = details.querySelector("[data-step-tries-body]");
  let loaded = false;
  const load = async () => {
    if (loaded) return;
    loaded = true;
    body.replaceChildren(Object.assign(document.createElement("li"), { textContent: t("execution.flow_panel.loading") }));
    try {
      const failedTries = (await loadDetail(step)).detail?.tries ?? [];
      const rows = failedTries.map((one) => t("tasks.history_step.try_failed", { n: one.try, total: step.attempts, reason: one.reason, time: formatDuration(one.duration_ms / 1000) }));
      rows.push(step.outcome === "pass" ? t("tasks.history_step.try_passed", { n: step.attempts, total: step.attempts }) : t("tasks.history_step.try_failed_last", { n: step.attempts, total: step.attempts, reason: step.reason ?? "" }));
      body.replaceChildren(...rows.map((text) => Object.assign(document.createElement("li"), { textContent: text })));
    } catch {
      loaded = false;
      body.textContent = t("tasks.history_step.request_could_not_be_loaded");
    }
  };
  details.addEventListener("toggle", () => details.open && load());
  details.open = open.has(details.dataset.key);
  if (details.open) load();
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
    body.textContent = t("execution.flow_panel.loading");
    try {
      body.replaceChildren(detailView((await loadDetail(step)).detail));
    } catch {
      loaded = false;
      body.textContent = t("tasks.history_step.request_could_not_be_loaded");
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
  const pre = details.querySelector("pre");
  pre.textContent = text;
  attachCopy(pre); // the whole output or data, however far the block has scrolled
}
