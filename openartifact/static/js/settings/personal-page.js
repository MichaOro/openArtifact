/* Settings > Personal (ADR-062): the form is the manifest `ui/forms/personal.yaml`, drawn by components/form-view.js. A switch
 * is saved when it is changed (persist policy of the catalog), one request at a time; a number is saved when the typing has
 * paused (NUMBER_PAUSE_MS), so a value typed digit by digit is sent once, and the form is not drawn again over a field the
 * user is typing in. Another tab's change arrives as `settings.changed` and is shown unless a save of this one is still on its way. */
import { AlertBar } from "../components/alert-bar.js";
import { FormView } from "../components/form-view.js";
import { request } from "../http.js";
import { t } from "../i18n.js";
import { connectEvents } from "../tasks/events.js";
import { Tabs } from "../components/tabs.js";
import { StoragePanel } from "./storage-panel.js";

const URL = "/api/settings/personal";
const root = document.querySelector("[data-personal-settings]");
const status = root.querySelector("[data-status]");
const errorLine = root.querySelector("[data-form-error]");
const banner = new AlertBar();
const NUMBER_PAUSE_MS = 700;
const storage = new StoragePanel(document.querySelector("[data-storage-panel]"));
const TABS = ["general", "storage"];
/** `#database` was a tab of its own once: a link to it opens the storage tab, where the database now is. */
const fromHash = () => {
  const name = location.hash.slice(1) === "database" ? "storage" : location.hash.slice(1);
  return TABS.includes(name) ? name : "general";
};
/** The tab is in the address: a reload and a link open the same one. */
const tabs = new Tabs(document.querySelector("[data-st-tabs]"), (name) => history.replaceState(null, "", `#${name}`));
tabs.select(fromHash(), { notify: false });
window.addEventListener("hashchange", () => tabs.select(fromHash(), { notify: false }));
/** One form per tab of the page: the manifest names the tab of each section; the values are shared. */
let forms = [];
let context = {};
let saved = {};
let saving = 0;
const timers = new Map();

function showError(message) {
  errorLine.textContent = message;
  errorLine.hidden = !message;
}

/** The values the forms show: what the server holds. */
function show(settings) {
  saved = { ...settings };
  for (const each of forms) {
    each.values = { ...settings };
    each.render();
  }
}

function build(manifest, settings) {
  saved = { ...settings };
  forms = [];
  for (const name of ["general", "storage"]) {
    const sections = manifest.sections.filter((section) => (section.tab ?? "general") === name);
    const host = root.querySelector(`[data-form="${name}"]`);
    forms.push(new FormView(host, { manifest: { ...manifest, sections }, values: { ...settings }, context, onChange: (values, key) => schedule(key, values[key]) }));
  }
}

async function load() {
  try {
    const [settings, manifest, status] = await Promise.all([request(URL), forms.length ? null : request("/api/forms/personal"), request("/api/settings/storage")]);
    context = { defaults: status.defaults ?? {}, on_values: status.on_values ?? {} };
    if (!forms.length) build(manifest, settings);
    else {
      for (const each of forms) each.context = context;
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
  // a limit that is switched on or off or reset gains or loses its number: saved at once, and the widget has drawn itself already
  if ((value === null) !== (saved[key] === null || saved[key] === undefined)) return persist(key, value, true);
  status.textContent = "";
  timers.set(key, setTimeout(() => persist(key, value, true), NUMBER_PAUSE_MS));
}

let queue = Promise.resolve();
/** One request at a time, in the order the user made the changes. */
function persist(key, value, typing = false) {
  saving += 1;
  queue = queue.then(() => send(key, value, typing));
  return queue;
}

async function send(key, value, typing) {
  status.textContent = t("editor.setting_controls.saving");
  showError("");
  try {
    const result = await request(URL, { method: "PUT", body: JSON.stringify({ [key]: value }) });
    if (typing && result[key] === value) saved = { ...result }; // what the user typed is what the server holds: no redraw
    else show(result);
    status.textContent = t("settings.personal_page.saved");
    if (key.startsWith("storage_")) storage.refresh(); // the warning and the cleaner's interval follow the setting
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
  onOpen: () => forms.length && load(), // a reconnect: events may have been missed (the first load is already on its way)
  onEvent: (type, data) => {
    if (type === "settings.changed" && data.personal && !saving) show(data.personal);
    if (type === "storage.cleaned") storage.refresh(); // a pass of the background cleaner
  },
});
