/* The pure part of the Dry run tab of the Trigger window (ADR-086): what the form is made of, what the start sends, what the chosen
 * card is remembered as, and how the server's answers read in plain words. No DOM and no requests: tests/js/dry-run-model.test.mjs.
 * The rules themselves (which input is missing, which value fits, what the draft refers to that is not there) are the server's; this only
 * puts what the user typed into the shape the server takes and the server's words on the screen. */
import { t } from "../i18n.js";

/** The localStorage key under which the card last chosen for a graph is kept (a browser's own memory, nothing on the server). */
export const cardKey = (graphId) => `oa-dry-run-card-${graphId}`;

/** The choices of the card list: the cards of the board that are not archived, each by number and title, with its lane beside it. */
export function cardOptions(tasks, lanes) {
  const titles = new Map((lanes ?? []).map((lane) => [lane.status, lane.title]));
  return (tasks ?? [])
    .filter((task) => !task.archived_at)
    .sort((a, b) => a.number - b.number)
    .map((task) => ({
      value: task.id,
      label: `#${task.number} ${task.title}`,
      description: titles.get(task.status) ?? task.status,
      keywords: String(task.number),
    }));
}

/** The remembered card when it is still among the options, else null. */
export function rememberedCard(options, savedId) {
  return options.find((option) => option.value === savedId)?.value ?? null;
}

/** What the form is made of: one entry per declared input, in the declared order. */
export function formFields(inputs) {
  return (Array.isArray(inputs) ? inputs : []).map((spec) => ({
    name: spec.name,
    type: spec.type ?? "text",
    required: Boolean(spec.required),
    default: spec.default == null ? "" : String(spec.default),
    description: spec.description ?? "",
    choices: Array.isArray(spec.choices) ? spec.choices : [],
  }));
}

/** The kind of control a type is entered in: a switch among *default / true / false* for a boolean, a pick for a choice, lines for a list. */
export function controlOf(field) {
  return { text: "text", number: "number", boolean: "boolean", choice: "choice", list: "lines" }[field.type] ?? "text";
}

/** The text that sits faintly in an empty field: the default when there is one. */
export function placeholderOf(field) {
  if (field.default) return field.default;
  return field.required ? t("editor.dry_run.required_placeholder") : "";
}

/** The values to send: only what was filled in (an empty field uses the declared default, on the server); `undefined` when the contract declares no inputs. */
export function inputsToSend(fields, entered) {
  if (!fields.length) return undefined;
  const out = {};
  for (const field of fields) {
    const raw = entered[field.name];
    if (raw === undefined || raw === null) continue;
    const text = String(raw);
    if (text.trim() !== "") out[field.name] = field.type === "list" ? text.replace(/\r\n/g, "\n") : text;
  }
  return out;
}

/** The body of the check and of the start: where the run starts (the pipeline, and for an action the place it is put), what it is given and which version. */
export function runBody({ target, fields, entered, version }) {
  const body = { pipeline_id: target.pipeline_id, version };
  if (target.stage_id) body.stage_id = target.stage_id;
  if (target.action_id) body.action_id = target.action_id;
  const inputs = inputsToSend(fields, entered);
  if (inputs !== undefined) body.inputs = inputs;
  return body;
}

/** The text of the check before the start: nothing found, or what would refuse the run, one line each. */
export function problemLines(problems) {
  return (problems ?? []).map((text) => String(text).trim()).filter(Boolean);
}

/** The server's refusal of a start in plain words: the stop switch, a run in progress, a check that failed. */
export function startErrorText(error) {
  if (error?.code === "stopped") return t("editor.dry_run.error_stopped");
  if (error?.status === 409) return t("editor.dry_run.error_busy");
  if (error?.status === 422) return error.detail && typeof error.detail === "string" ? error.detail : error.message;
  return error?.message || t("editor.dry_run.error_unknown");
}

/** The word for a run's status. */
export function statusLabel(status) {
  return { running: t("common.running"), done: t("common.done"), failed: t("common.failed"), stopped: t("common.stopped") }[status] ?? status;
}

/** One line of the result: the step's name, how it ended, and for a skipped writing step what it would have done. */
export function stepRow(step) {
  const skipped = Boolean(step.data?.dry_run);
  const would = skipped && step.data.would_have ? t("editor.dry_run.would_have", { what: step.data.would_have }) : "";
  const text = would || (step.outcome === "fail" ? (step.reason ?? "") : "");
  return { id: step.id, name: step.node_name, outcome: step.outcome, skipped, text };
}

/** The steps of the result in order. The Trigger that starts an action and an Output that passes say nothing new: they are left out, an Output that fails stays. */
export function stepRows(results) {
  return [...(results ?? [])]
    .filter((step) => step.kind !== "trigger" && !(step.kind === "output" && step.outcome !== "fail"))
    .sort((a, b) => a.seq - b.seq)
    .map(stepRow);
}

/** The page of the execution in the history, which shows the run with its mark. */
export const historyUrl = (taskNumber, executionId) => `/artifacts/${taskNumber}/executions/${encodeURIComponent(executionId)}`;

/** The way to run an action definition: the places a pipeline puts it; none means it cannot run alone. */
export function chooseTarget(placements, savedActionId) {
  if (!placements.length) return null;
  return placements.find((p) => p.action_id === savedActionId) ?? placements[0];
}

/** The label of a place an action is put in. */
export const placementLabel = (placement) => `${placement.pipeline_name} · ${placement.stage_name}`;
