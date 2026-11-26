/* Settings > Personal (ADR-062): the form is the manifest `ui/forms/personal.yaml`, drawn by components/form-view.js. A switch
 * is saved when it is changed (persist policy of the catalog), one request at a time; a number is saved when the typing has
 * paused (NUMBER_PAUSE_MS), so a value typed digit by digit is sent once, and the form is not drawn again over a field the
 * user is typing in. Another tab's change arrives as `settings.changed` and is shown unless a save of this one is still on its way. */
import { AlertBar } from "../components/alert-bar.js";
import { FormView } from "../components/form-view.js";
import { request } from "../http.js";
import { t } from "../i18n.js";
import { connectEvents } from "../tasks/events.js";

const URL = "/api/settings/personal";
const root = document.querySelector("[data-personal-settings]");
const status = root.querySelector("[data-status]");
const errorLine = root.querySelector("[data-form-error]");
const banner = new AlertBar();
const NUMBER_PAUSE_MS = 700;
let form = null;
let saving = 0;
const timers = new Map();

function showError(message) {
  errorLine.textContent = message;
  errorLine.hidden = !message;
}

/** The values the form shows: what the server holds. */
function show(settings) {
  if (!form) return;
  form.values = { ...settings };
  form.render();
}

async function load() {
  try {
    const [settings, manifest] = await Promise.all([request(URL), form ? null : request("/api/forms/personal")]);
    if (!form) {
      form = new FormView(root.querySelector("[data-form]"), { manifest, values: { ...settings }, onChange: (values, key) => schedule(key, values[key]) });
    } else {
      show(settings);
    }
    banner.hide();
  } catch {
    banner.show(t("settings.personal_page.personal_could_not_be"), { retry: true });
  }
}

/** A switch is saved at once; a number once the typing has paused. */
function schedule(key, value) {
  clearTimeout(timers.get(key));
  if (typeof value === "boolean") return persist(key, value);
  status.textContent = "";
  timers.set(key, setTimeout(() => persist(key, value, true), NUMBER_PAUSE_MS));
}

async function persist(key, value, typing = false) {
  saving += 1;
  status.textContent = t("editor.setting_controls.saving");
  showError("");
  try {
    const saved = await request(URL, { method: "PUT", body: JSON.stringify({ [key]: value }) });
    if (typing && saved[key] === value) form.values = { ...saved }; // what the user typed is what the server holds: no redraw
    else show(saved);
    status.textContent = t("settings.personal_page.saved");
  } catch (problem) {
    status.textContent = "";
    showError(Object.values(problem.fieldErrors ?? {})[0] ?? problem.detail ?? problem.message);
    await load(); // the form shows what the server holds again
  } finally {
    saving -= 1;
  }
}

banner.onRetry(load);
load();

connectEvents({
  onClosed: () => {},
  onOpen: () => form && load(), // a reconnect: events may have been missed (the first load is already on its way)
  onEvent: (type, data) => {
    if (type === "settings.changed" && data.personal && !saving) show(data.personal);
  },
});
