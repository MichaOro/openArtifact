/* The Observe section at the top of the Dry run tab of a pipeline's Trigger window (ADR-088): one switch that makes every run of the pipeline a
 * dry run, and the two optional limits. It edits the DRAFT (the mode goes live with a publication), and says so under the switch together
 * with what is live now when that differs. Switching it on happens only here; the eye in the status bar of the canvas can switch it off. */
import { createSwitch, Switch } from "../components/switch.js";
import { t } from "../i18n.js";
import { LIMITS, liveNote, parseLimit, settingOf } from "./observe-model.js";

const make = (tag, className = "", text = null) => {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
};

let counter = 0;

export class ObservePanel {
  /** @param {import("./observe-store.js").ObserveStore} store @param {{changed?: () => void}} [hooks] `changed`: the draft was changed here */
  constructor(store, { changed = () => {} } = {}) {
    this.store = store;
    this.changed = changed;
    const uid = `observe-${(counter += 1)}`;
    this.element = make("section", "ge-observe");
    this.element.dataset.observePanel = "";
    const head = make("div", "ge-observe__head");
    const label = make("span", "ge-observe__title", t("editor.observe.title"));
    label.id = `${uid}-label`;
    this.switchButton = createSwitch(label.id);
    this.switchButton.dataset.observeSwitch = "";
    this.switch = new Switch(this.switchButton, { onChange: (on) => this.#save(on) });
    head.append(this.switchButton, label);
    this.lead = make("p", "ge-observe__lead", t("editor.observe.lead"));
    this.limits = make("div", "ge-observe__limits");
    this.limits.hidden = true;
    this.fields = {};
    for (const which of ["days", "runs"]) {
      const box = make("div", "field ge-observe__limit");
      const text = make("label", "field__label", t(`editor.observe.${which}`));
      const input = make("input", "field__control");
      input.type = "text";
      input.inputMode = "numeric";
      input.id = `${uid}-${which}`;
      input.dataset.observeLimit = which;
      input.placeholder = t("editor.observe.no_limit");
      text.htmlFor = input.id;
      input.addEventListener("change", () => this.#save(this.switch.on));
      box.append(text, input);
      this.limits.append(box);
      this.fields[which] = input;
    }
    this.limitNote = make("p", "ge-observe__note", t("editor.observe.limit_note"));
    this.limits.append(this.limitNote);
    this.status = make("p", "ge-observe__note");
    this.status.setAttribute("role", "status");
    this.status.dataset.observeStatus = "";
    this.error = make("p", "ge-observe__error");
    this.error.setAttribute("role", "alert");
    this.error.hidden = true;
    this.element.append(head, this.lead, this.limits, this.status, this.error);
    store.subscribe((read) => this.render(read));
    store.refresh();
  }

  /** Draw what the draft says: the switch, the limits (not while one is being typed), and the line about when it applies. */
  render(read) {
    const draft = read?.draft ?? null;
    this.switch.on = Boolean(draft?.enabled);
    this.limits.hidden = !draft?.enabled;
    for (const which of ["days", "runs"]) {
      if (document.activeElement !== this.fields[which]) this.fields[which].value = draft?.[which] ?? "";
    }
    const live = liveNote(read);
    const parts = [t("editor.observe.applies")];
    if (live) parts.push(t(`editor.observe.live_${live}`));
    this.status.textContent = parts.join(" ");
  }

  #problem(text) {
    this.error.textContent = text;
    this.error.hidden = !text;
  }

  async #save(on) {
    const days = parseLimit(this.fields.days.value, "days");
    const runs = parseLimit(this.fields.runs.value, "runs");
    const wrong = [["days", days], ["runs", runs]].find(([, parsed]) => parsed.error);
    if (on && wrong) {
      const [which, parsed] = wrong;
      this.#problem(t(`editor.observe.problem_${parsed.error}`, { min: LIMITS[which][0], max: LIMITS[which][1] }));
      return;
    }
    this.#problem("");
    try {
      await this.store.setDraft(settingOf({ enabled: on, days: on ? days.value : null, runs: on ? runs.value : null }));
      this.changed();
    } catch (error) {
      this.#problem(error.detail ?? error.message);
      this.render(this.store.read);
    }
  }
}
