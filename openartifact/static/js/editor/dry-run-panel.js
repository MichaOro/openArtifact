/* The Dry run tab of the Trigger window (ADR-086): choose a test card, give the inputs the Trigger declares, choose the version, see what
 * the server says would refuse the run, start it, and read the result: the status with the Dry run mark and one line per step, with a link
 * to the execution in the history (the flow view is not drawn again here). One panel lives as long as the editor page: the window redraws its
 * contents on every change, the panel keeps what was entered and is placed into the new tab each time (`show`).
 * The rules are the server's (`POST /api/tasks/{id}/dry-run/check`, the start itself); the model (dry-run-model.js) is the pure part. */
import { Combobox } from "../components/combobox.js";
import { currentStop, followStop, subscribeStop } from "../components/stop-state.js";
import { request } from "../http.js";
import { t } from "../i18n.js";
import { readJson, writeJson } from "../storage.js";
import { connectEvents } from "../tasks/events.js";
import {
  cardKey,
  cardOptions,
  chooseTarget,
  controlOf,
  formFields,
  historyUrl,
  placeholderOf,
  placementLabel,
  problemLines,
  rememberedCard,
  runBody,
  startErrorText,
  statusLabel,
  stepRows,
} from "./dry-run-model.js";

const make = (tag, className = "", text = null) => {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
};

let counter = 0;

export class DryRunPanel {
  /** @param {{kind: "pipeline"|"action", id: string, contract: (version: string) => Promise<object[]>}} graph what is edited */
  constructor(graph) {
    this.graph = graph;
    this.uid = `dry-${(counter += 1)}`;
    this.entered = {}; // input name -> what was typed; kept across redraws of the window
    this.version = "draft";
    this.taskId = null;
    this.target = null; // where the run starts (an action definition: the place a pipeline puts it)
    this.placements = null;
    this.running = false;
    this.run = null; // the answer of the start: the run and its execution
    this.steps = [];
    this.inputsSource = []; // the declared inputs shown now
    this.checkTurn = 0;
    this.element = make("div", "ge-dry");
    this.element.dataset.dryRun = "";
    this.#build();
    subscribeStop(() => this.#syncStart());
    followStop();
    connectEvents({
      onEvent: (type, data) => {
        if (type === "run.updated" && this.run && data.task_id === this.run.task_id) this.#onRun(data);
        if (type === "graph.changed" || type === "graph.contract_changed") this.#scheduleCheck();
      },
      onOpen: () => {},
      onClosed: () => {},
    });
  }

  /** Put the panel into a fresh window: `inputs` are what the Trigger declares in the draft, now. */
  show(inputs) {
    this.draftInputs = formFields(inputs);
    if (this.version === "draft") this.#setFields(this.draftInputs);
    if (!this.loaded) this.#load();
    return this.element;
  }

  // ── building ──────────────────────────────────────────────────

  #build() {
    const id = (name) => `${this.uid}-${name}`;
    const lead = make("p", "ge-dry__lead", this.graph.kind === "action" ? t("editor.dry_run.lead_action") : t("editor.dry_run.lead_pipeline"));
    this.placeBox = make("div", "field ge-dry__place");
    this.placeBox.hidden = true;
    this.placeSelect = make("select", "field__control");
    this.placeSelect.id = id("place");
    this.placeSelect.dataset.focusKey = "dry-place";
    this.placeSelect.addEventListener("change", () => {
      this.target = this.placements.find((p) => p.action_id === this.placeSelect.value) ?? null;
      this.#scheduleCheck();
      this.#syncStart();
    });
    const placeLabel = make("label", "field__label", t("editor.dry_run.place_label"));
    placeLabel.htmlFor = this.placeSelect.id;
    this.placeBox.append(placeLabel, this.placeSelect);
    this.placeMissing = make("p", "ge-dry__note", t("editor.dry_run.place_missing"));
    this.placeMissing.hidden = true;
    this.placeMissing.setAttribute("role", "status");

    const cardBox = make("div", "field ge-dry__card");
    const cardLabel = make("span", "field__label", t("editor.dry_run.card_label"));
    cardLabel.id = id("card-label");
    this.cardHost = make("div", "ge-dry__combo");
    cardBox.append(cardLabel, this.cardHost);
    this.cardNote = make("p", "ge-dry__note", t("editor.dry_run.card_none"));
    this.cardNote.hidden = true;
    this.combo = new Combobox(this.cardHost, {
      label: t("editor.dry_run.card_label"),
      options: [],
      placeholder: t("editor.dry_run.card_placeholder"),
      emptyText: t("editor.dry_run.card_no_match"),
      onChange: (option) => this.#pickCard(option?.value ?? null),
    });
    this.combo.input.dataset.focusKey = "dry-card";

    this.inputsBox = make("fieldset", "ge-dry__inputs");
    const legend = make("legend", "ge-dry__legend", t("editor.dry_run.inputs_title"));
    this.inputsList = make("div", "ge-dry__rows");
    this.noInputs = make("p", "ge-dry__note", t("editor.dry_run.no_inputs"));
    this.inputsBox.append(legend, this.inputsList, this.noInputs);

    const versionBox = make("fieldset", "ge-dry__version");
    versionBox.append(make("legend", "ge-dry__legend", t("editor.dry_run.version_label")));
    const choices = make("div", "ge-dry__choices");
    for (const [value, label] of [
      ["draft", t("editor.dry_run.version_draft")],
      ["published", t("editor.dry_run.version_published")],
    ]) {
      const wrap = make("label", "ge-dry__choice");
      const radio = make("input");
      radio.type = "radio";
      radio.name = id("version");
      radio.value = value;
      radio.checked = value === this.version;
      radio.dataset.focusKey = `dry-version-${value}`;
      radio.addEventListener("change", () => this.#setVersion(value));
      wrap.append(radio, make("span", "", label));
      choices.append(wrap);
    }
    versionBox.append(choices);
    this.versionRadios = [...choices.querySelectorAll("input")];

    this.checkLine = make("div", "ge-dry__check");
    this.checkLine.setAttribute("role", "status");
    this.checkLine.setAttribute("aria-live", "polite");

    const actions = make("div", "ge-dry__actions");
    this.startButton = make("button", "button button--primary", t("editor.dry_run.start"));
    this.startButton.type = "button";
    this.startButton.dataset.dryStart = "";
    this.startButton.dataset.focusKey = "dry-start";
    this.startButton.addEventListener("click", () => this.#start());
    this.startHint = make("span", "ge-dry__hint");
    this.startHint.id = id("hint");
    this.startButton.setAttribute("aria-describedby", this.startHint.id);
    actions.append(this.startButton, this.startHint);

    this.errorLine = make("p", "ge-dry__error");
    this.errorLine.setAttribute("role", "alert");
    this.errorLine.hidden = true;

    this.result = make("section", "ge-dry__result");
    this.result.setAttribute("aria-label", t("editor.dry_run.result_title"));
    this.result.setAttribute("aria-live", "polite");
    this.result.hidden = true;
    this.resultHead = make("p", "ge-dry__resulthead");
    this.stepList = make("ol", "ge-dry__steps");
    this.historyLink = make("a", "ge-dry__history", t("editor.dry_run.open_history"));
    this.result.append(this.resultHead, this.stepList, this.historyLink);

    this.element.append(lead, this.placeBox, this.placeMissing, cardBox, this.cardNote, this.inputsBox, versionBox, this.checkLine, actions, this.errorLine, this.result);
    this.#setFields([]);
    this.#syncStart();
  }

  // ── loading the cards and the places ───────────────────────────

  async #load() {
    this.loaded = true;
    try {
      const [tasks, lanes] = await Promise.all([request("/api/tasks"), request("/api/lanes")]);
      this.tasks = tasks;
      const options = cardOptions(tasks, lanes);
      this.combo.setOptions(options);
      this.cardNote.hidden = options.length > 0;
      const saved = rememberedCard(options, readJson(cardKey(this.graph.id)));
      if (saved) {
        this.combo.choose(saved);
      }
    } catch {
      this.loaded = false;
      this.cardNote.textContent = t("editor.dry_run.error_unknown");
      this.cardNote.hidden = false;
    }
    if (this.graph.kind === "action") await this.#loadPlacements();
    this.#syncStart();
  }

  async #loadPlacements() {
    try {
      this.placements = await request(`/api/actions/${encodeURIComponent(this.graph.id)}/placements`);
    } catch {
      this.placements = [];
    }
    const saved = readJson(`${cardKey(this.graph.id)}-place`);
    this.target = chooseTarget(this.placements, saved);
    this.placeMissing.hidden = this.placements.length > 0;
    this.placeBox.hidden = this.placements.length < 2;
    this.placeSelect.replaceChildren(...this.placements.map((p) => Object.assign(new Option(placementLabel(p), p.action_id), { selected: p.action_id === this.target?.action_id })));
    this.#scheduleCheck();
  }

  #pickCard(taskId) {
    this.taskId = taskId;
    if (taskId) writeJson(cardKey(this.graph.id), taskId);
    this.#scheduleCheck();
    this.#syncStart();
  }

  // ── the inputs ────────────────────────────────────────────────

  async #setVersion(version) {
    this.version = version;
    let fields = this.draftInputs ?? [];
    if (version === "published") {
      try {
        fields = formFields(await this.graph.contract());
      } catch {
        fields = [];
      }
    }
    this.#setFields(fields);
    this.#scheduleCheck();
  }

  #setFields(fields) {
    this.fields = fields;
    this.inputsList.replaceChildren(...fields.map((field, i) => this.#row(field, i)));
    this.noInputs.hidden = fields.length > 0;
  }

  #row(field, index) {
    const control = controlOf(field);
    const id = `${this.uid}-in-${index}`;
    const row = make("div", "ge-dry__row");
    const label = make("label", "field__label", field.name);
    label.htmlFor = id;
    if (field.required) label.append(make("span", "ge-dry__required", ` ${t("editor.dry_run.required")}`));
    if (field.description) label.title = field.description;
    let input;
    if (control === "boolean" || control === "choice") {
      input = make("select", "field__control");
      input.append(new Option(field.default ? t("editor.dry_run.use_default", { value: field.default }) : t("editor.dry_run.not_set"), ""));
      const values = control === "boolean" ? ["true", "false"] : field.choices;
      for (const value of values) input.append(new Option(value, value));
    } else if (control === "lines") {
      input = make("textarea", "field__control ge-dry__lines");
      input.rows = 3;
      input.placeholder = field.default || t("editor.dry_run.lines_placeholder");
      input.spellcheck = false;
    } else {
      input = make("input", "field__control");
      input.type = "text";
      if (control === "number") input.inputMode = "decimal";
      input.autocomplete = "off";
      input.spellcheck = false;
      input.placeholder = placeholderOf(field);
    }
    input.id = id;
    input.name = field.name;
    input.dataset.focusKey = `dry-input-${field.name}`;
    input.value = this.entered[field.name] ?? "";
    input.addEventListener("input", () => {
      this.entered[field.name] = input.value;
      this.#scheduleCheck();
    });
    input.addEventListener("change", () => {
      this.entered[field.name] = input.value;
      this.#scheduleCheck();
    });
    row.append(label, input);
    return row;
  }

  // ── the check before the start ─────────────────────────────────

  #scheduleCheck() {
    window.clearTimeout(this.checkTimer);
    this.checkTimer = window.setTimeout(() => this.#check(), 350);
  }

  #body() {
    return runBody({ target: this.target ?? { pipeline_id: this.graph.id }, fields: this.fields, entered: this.entered, version: this.version });
  }

  #ready() {
    return Boolean(this.taskId) && (this.graph.kind === "pipeline" || Boolean(this.target));
  }

  async #check() {
    if (!this.#ready()) {
      this.checkLine.replaceChildren();
      return;
    }
    const turn = (this.checkTurn += 1);
    this.checkLine.textContent = t("editor.dry_run.checking");
    let problems;
    try {
      problems = problemLines((await request(`/api/tasks/${encodeURIComponent(this.taskId)}/dry-run/check`, { method: "POST", body: JSON.stringify(this.#body()) })).problems);
    } catch (error) {
      if (turn !== this.checkTurn) return;
      this.checkLine.textContent = startErrorText(error);
      return;
    }
    if (turn !== this.checkTurn) return; // a newer question is on its way: only the last answer is shown
    if (!problems.length) {
      this.checkLine.textContent = t("editor.dry_run.check_ok");
      this.checkLine.dataset.state = "ok";
      return;
    }
    this.checkLine.dataset.state = "problems";
    const list = make("ul", "ge-dry__problems");
    for (const text of problems) list.append(make("li", "", text));
    this.checkLine.replaceChildren(make("p", "", t("editor.dry_run.check_problems")), list);
  }

  // ── the start ────────────────────────────────────────────────

  #syncStart() {
    const stopped = currentStop()?.active === true;
    let reason = "";
    if (stopped) reason = t("editor.dry_run.hint_stopped");
    else if (this.running) reason = t("editor.dry_run.hint_running");
    else if (this.graph.kind === "action" && this.placements && !this.target) reason = t("editor.dry_run.place_missing");
    else if (!this.taskId) reason = t("editor.dry_run.hint_no_card");
    this.startButton.disabled = Boolean(reason);
    this.startButton.title = reason;
    this.startHint.textContent = reason;
  }

  async #start() {
    if (this.startButton.disabled) return;
    this.errorLine.hidden = true;
    this.running = true;
    this.#syncStart();
    try {
      const body = { ...this.#body(), dry_run: true };
      const run = await request(`/api/tasks/${encodeURIComponent(this.taskId)}/run`, { method: "POST", body: JSON.stringify(body) });
      this.task = this.tasks?.find((task) => task.id === this.taskId) ?? null;
      this.run = run;
      this.#showRun(run);
      await this.#loadSteps();
    } catch (error) {
      this.errorLine.textContent = startErrorText(error);
      this.errorLine.hidden = false;
      this.running = false;
      this.#syncStart();
    }
  }

  #onRun(run) {
    this.run = run;
    this.#showRun(run);
    this.#loadSteps();
  }

  #showRun(run) {
    this.result.hidden = false;
    const mark = make("span", "history-flag", t("executions.dry_run"));
    const status = make("strong", "", statusLabel(run.status));
    const number = run.execution_number ? ` #${run.execution_number}` : "";
    this.resultHead.replaceChildren(mark, document.createTextNode(" "), status, document.createTextNode(number));
    this.resultHead.dataset.status = run.status;
    if (run.execution_id && this.task) this.historyLink.href = historyUrl(this.task.number, run.execution_id);
    this.historyLink.hidden = !(run.execution_id && this.task);
    if (run.status !== "running") {
      this.running = false;
      this.#syncStart();
    }
  }

  async #loadSteps() {
    if (!this.run) return;
    try {
      this.steps = await request(`/api/runs/${encodeURIComponent(this.run.task_id)}/results`);
    } catch {
      return;
    }
    const rows = stepRows(this.steps);
    this.stepList.replaceChildren(
      ...(rows.length
        ? rows.map((row) => {
            const li = make("li", "ge-dry__step");
            li.dataset.outcome = row.skipped ? "skipped" : row.outcome;
            const head = make("span", "ge-dry__stepname", row.name);
            const how = make("span", "ge-dry__stepoutcome", row.skipped ? t("editor.dry_run.skipped") : row.outcome === "fail" ? t("common.failed") : t("editor.dry_run.passed"));
            li.append(head, " ", how);
            if (row.text) li.append(make("p", "ge-dry__steptext", row.text));
            return li;
          })
        : [make("li", "ge-dry__step", t("editor.dry_run.no_steps"))]),
    );
  }
}
