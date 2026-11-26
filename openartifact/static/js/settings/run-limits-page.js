/* Settings > Run limits: two numbers, saved together. The server checks the bounds and has the last word. */
import { AlertBar } from "../components/alert-bar.js";
import { request } from "../http.js";
import { connectEvents } from "../tasks/events.js";
import { t } from "../i18n.js";

const form = document.querySelector("[data-run-limits]");
const submit = form.querySelector("[data-submit]");
const status = form.querySelector("[data-status]");
const error = form.querySelector("[data-form-error]");
const banner = new AlertBar();
const FIELDS = ["max_steps", "time_limit_minutes"];
let saved = null;

function show(limits) {
  saved = limits;
  for (const name of FIELDS) form.elements.namedItem(name).value = String(limits[name]);
  form.querySelector("[data-concurrent]").textContent = String(limits.max_concurrent_runs);
  sync();
}

function values() {
  return Object.fromEntries(FIELDS.map((name) => [name, Number(form.elements.namedItem(name).value)]));
}

/** Save is possible when something changed. */
function sync() {
  const now = values();
  submit.disabled = !saved || FIELDS.every((name) => now[name] === saved[name]);
}

function fail(message) {
  error.textContent = message ?? "";
  error.hidden = !message;
}

async function load() {
  try {
    show(await request("/api/settings/run-limits"));
    banner.hide();
  } catch {
    banner.show(t("settings.run_limits_page.run_limits_could_not_be"), { retry: true });
  }
}

form.addEventListener("input", () => {
  status.textContent = "";
  fail(null);
  sync();
});
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (submit.disabled) return;
  const body = values();
  if (FIELDS.some((name) => !Number.isInteger(body[name]))) {
    fail(t("settings.run_limits_page.enter_whole_numbers"));
    return;
  }
  submit.disabled = true;
  status.textContent = t("editor.setting_controls.saving");
  try {
    show(await request("/api/settings/run-limits", { method: "PUT", body: JSON.stringify(body) }));
    status.textContent = t("settings.run_limits_page.saved_executions_start_from_now");
  } catch (problem) {
    status.textContent = "";
    fail(Object.values(problem.fieldErrors ?? {})[0] ?? problem.detail ?? problem.message);
    sync();
  }
});
banner.onRetry(load);
load();

connectEvents({
  onClosed: () => {},
  onOpen: () => {},
  onEvent: (type, data) => {
    // another tab changed them: show the new values unless this form has changes of its own
    if (type === "settings.changed" && data.run_limits && submit.disabled) show(data.run_limits);
  },
});
