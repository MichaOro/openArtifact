/* Settings > Personal: rendered from form manifest via FormView. Switches persist on change (catalog rule 5). */
import { AlertBar } from "../components/alert-bar.js";
import { request } from "../http.js";
import { connectEvents } from "../tasks/events.js";
import { FormView } from "../components/form-view.js";
import { t } from "../i18n.js";

const host = document.querySelector("[data-personal-settings]");
const status = host.querySelector("[data-status]");
const banner = new AlertBar();
let formView = null;
let saved = null;

function show(settings) {
  saved = settings;
  if (formView) {
    formView.values = { ...settings };
    formView.render();
  }
}

async function load() {
  try {
    const settings = await request("/api/settings/personal");
    show(settings);
    banner.hide();
    // Initialize FormView after first load
    if (!formView) {
      const manifest = await request("/api/forms/personal");
      formView = new FormView(host.querySelector("[data-form]"), {
        manifest,
        values: settings,
        onChange: (values, key) => {
          // Switch persists on change (catalog rule 5)
          if (key in saved && saved[key] !== values[key]) {
            persist(key, values[key]);
          }
        },
      });
    }
  } catch {
    banner.show(t("settings.personal_page.personal_could_not_be"), { retry: true });
  }
}

async function persist(key, value) {
  status.textContent = t("editor.setting_controls.saving");
  try {
    await request("/api/settings/personal", {
      method: "PUT",
      body: JSON.stringify({ [key]: value }),
    });
    show(await request("/api/settings/personal"));
    status.textContent = t("settings.personal_page.saved");
  } catch (problem) {
    status.textContent = "";
    const msg = Object.values(problem.fieldErrors ?? {})[0] ?? problem.detail ?? problem.message;
    host.querySelector("[data-form-error]")?.textContent = msg;
    host.querySelector("[data-form-error]")?.hidden = false;
  }
}

banner.onRetry(load);
load();

connectEvents({
  onClosed: () => {},
  onOpen: () => {},
  onEvent: (type, data) => {
    // another tab changed them: show the new values unless this form has changes of its own
    if (type === "settings.changed" && data.personal) {
      const hasLocalChanges = formView && Object.keys(formView.values).some(k => formView.values[k] !== saved[k]);
      if (!hasLocalChanges) show(data.personal);
    }
  },
});