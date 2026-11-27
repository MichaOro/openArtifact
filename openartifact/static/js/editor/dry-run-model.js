/* The pure part of the Dry run tab of the Trigger window (ADR-086): what the form is made of, what the start sends, what the chosen
 * card is remembered as, and how the server's answers read in plain words. No DOM and no requests: tests/js/dry-run-model.test.mjs.
 * The rules themselves (which input is missing, which value fits, what the draft refers to that is not there) are the server's; this only
 * puts what the user typed into the shape the server takes and the server's words on the screen. */
import { t } from "../i18n.js";
import { withOrigin } from "../execution/back-link.js";

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

/** The body of the check and of the start (`/api/graphs/{id}/dry-run`, ADR-089): the graph is in the address, so the body is the version, the
 * inputs it is given and, when one was added with "+ Add", the card it runs on; without a card the run belongs to the graph's hidden card. */
export function runBody({ fields, entered, version, taskId = null }) {
  const body = { version };
  if (taskId) body.task_id = taskId;
  const inputs = inputsToSend(fields, entered);
  if (inputs !== undefined) body.inputs = inputs;
  return body;
}

/** The addresses of a graph's dry run: the start, the check before it and the hidden card its card-less runs belong to. */
export const dryRunUrls = (graphId) => ({
  start: `/api/graphs/${encodeURIComponent(graphId)}/dry-run`,
  check: `/api/graphs/${encodeURIComponent(graphId)}/dry-run/check`,
  card: `/api/graphs/${encodeURIComponent(graphId)}/dry-run-card`,
});

/** The card whose executions the tab lists and whose run the Stop stops: the chosen one, else the hidden card of the graph, else none yet. */
export const listedCard = (chosenId, hiddenId) => chosenId || hiddenId || null;

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

/** The page of the execution in the history, which shows the run with its mark: where a click on the row of a dry run leads. */
export const historyUrl = (taskNumber, executionId, from = null) => withOrigin(`/artifacts/${taskNumber}/executions/${encodeURIComponent(executionId)}`, from);

/** The list of the global execution history narrowed to dry runs: where "All dry runs" leads. */
export const allDryRunsUrl = "/executions?dry_run=only";

/** How many dry runs the tab lists (the newest); the rest is in the history. */
export const LISTED_RUNS = 5;

/** The dry runs of this graph on the card, newest first: a dry run of this graph (a pipeline's own, or an action's by itself, ADR-089). */
export function listedRuns(executions, pipelineId) {
  return [...(executions ?? [])]
    .filter((e) => e.dry_run && (!pipelineId || e.pipeline_id === pipelineId))
    .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime())
    .slice(0, LISTED_RUNS);
}

/** The dry run that is running now (the one the Start button turns into a Stop for), or null. */
export const runningRun = (runs) => (runs ?? []).find((e) => e.status === "running") ?? null;

/** What the form may be given besides what it always has (Inputs, Version, Start). One entry per item: add one here and the
 * "+ Add" menu offers it; the panel draws it with its own builder under the same key. `labelKey` is the menu entry and the field's name. */
export const OPTIONAL_ITEMS = [{ key: "card", labelKey: "editor.dry_run.card_label", icon: "plus" }];

/** The items not on the form yet, in the order of the list. */
export const availableItems = (shown) => OPTIONAL_ITEMS.filter((item) => !shown.has(item.key));
