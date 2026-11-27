/* The Dry run tab of the Trigger window (ADR-086): give the inputs the Trigger declares, choose the version, see what the server says would
 * refuse the run, start it (the Start button is the Stop while it runs), and see the dry runs as rows of the same list the artifact's History
 * tab has: a click on a row leads to the execution in the history. The test card is one of the optional items behind "+ Add" (ADR-086
 * addendum 2). One panel lives as long as the editor page: the window redraws its
 * contents on every change, the panel keeps what was entered and is placed into the new tab each time (`show`).
 * The rules are the server's (`POST /api/tasks/{id}/dry-run/check`, the start itself); the model (dry-run-model.js) is the pure part. */
import { ActionMenu } from "../components/action-menu.js";
import { Combobox } from "../components/combobox.js";
import { icon } from "../components/icons.js";
import { currentStop, followStop, subscribeStop } from "../components/stop-state.js";
import { editorOrigin } from "../execution/back-link.js";
import { request } from "../http.js";
import { t } from "../i18n.js";
import { readJson, writeJson } from "../storage.js";
import { stopRun } from "../tasks/api.js";
import { connectEvents } from "../tasks/events.js";
import { HistoryList } from "../tasks/history-list.js";
import {
  allDryRunsUrl,
  availableItems,
  cardKey,
  cardOptions,
  controlOf,
  dryRunUrls,
  formFields,
  historyUrl,
  listedCard,
  listedRuns,
  placeholderOf,
  problemLines,
  rememberedCard,
  runBody,
  runningRun,
  startErrorText,
} from "./dry-run-model.js";

const make = (tag, className = "", text = null) => {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
};

let counter = 0;
let addMenu = null;

export class DryRunPanel {
  /** @param {{kind: "pipeline"|"action", id: string, contract: (version: string) => Promise<object[]>}} graph what is edited */
  constructor(graph) {
    this.graph = graph;
    this.uid = `dry-${(counter += 1)}`;
    this.entered = {}; // input name -> what was typed; kept across redraws of the window
    this.version = "draft";
    this.taskId = null; // the card chosen with "+ Add"; without one the dry runs belong to the graph's hidden card (ADR-089)
    this.hidden = { task_id: null, number: null };
    this.urls = dryRunUrls(graph.id);
    this.running = false; // a start is on its way
    this.runs = []; // the dry runs listed (executions of this graph on the card)
    this.shown = new Set(); // the optional items on the form ("card")
    this.inputsSource = []; // the declared inputs shown now
    this.checkTurn = 0;
    this.element = make("div", "ge-dry");
    this.element.dataset.dryRun = "";
    this.#build();
    subscribeStop(() => this.#syncStart());
    followStop();
    connectEvents({
      onEvent: (type, data) => {
        if (type === "run.updated" && this.#listTaskId() && data.task_id === this.#listTaskId()) this.#scheduleRuns();
        if (type === "graph.changed" || type === "graph.contract_changed") this.#scheduleCheck();
      },
      onOpen: () => this.#loadRuns(), // what happened while the stream was away is read again
      onClosed: () => {},
    });
  }

  /** Put the panel into a fresh window: `inputs` are what the Trigger declares in the draft, now. */
  show(inputs, cases = null) {
    if (cases) this.casesApi = cases; // {list: () => [{name, inputs}], save: (cases) => Promise<string|null>}: the test cases of the Trigger (ADR-087)
    this.#drawCases();
    this.draftInputs = formFields(inputs);
    if (this.version === "draft") this.#setFields(this.draftInputs);
    if (!this.loaded) this.#load();
    return this.element;
  }

  // ── building ──────────────────────────────────────────────────

  #build() {
    const id = (name) => `${this.uid}-${name}`;
    const lead = make("p", "ge-dry__lead", this.graph.kind === "action" ? t("editor.dry_run.lead_action") : t("editor.dry_run.lead_pipeline"));
    this.cardBox = make("div", "field ge-dry__card");
    this.cardBox.hidden = true;
    const cardHead = make("div", "ge-dry__cardhead");
    const cardLabel = make("span", "field__label", t("editor.dry_run.card_label"));
    cardLabel.id = id("card-label");
    const cardRemove = make("button", "icon-button icon-button--sm");
    cardRemove.type = "button";
    cardRemove.append(icon("x"));
    cardRemove.setAttribute("aria-label", t("editor.dry_run.card_remove"));
    cardRemove.title = t("editor.dry_run.card_remove");
    cardRemove.dataset.focusKey = "dry-card-remove";
    cardRemove.addEventListener("click", () => this.#dropItem("card"));
    cardHead.append(cardLabel, cardRemove);
    this.cardHost = make("div", "ge-dry__combo");
    this.cardBox.append(cardHead, this.cardHost);
    this.addButton = make("button", "button button--ghost button--sm ge-dry__add");
    this.addButton.type = "button";
    this.addButton.dataset.dryAdd = "";
    this.addButton.dataset.focusKey = "dry-add";
    this.addButton.setAttribute("aria-haspopup", "menu");
    this.addButton.append(icon("plus"), make("span", "", t("editor.dry_run.add")));
    this.addButton.addEventListener("click", () => this.#openAdd());
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
    this.startButton = make("button", "button button--primary");
    this.startButton.type = "button";
    this.startButton.dataset.dryStart = "";
    this.startButton.dataset.focusKey = "dry-start";
    this.startLabel = make("span", "", t("editor.dry_run.start"));
    this.startIcon = icon("play");
    this.startButton.append(this.startIcon, this.startLabel);
    this.startButton.addEventListener("click", () => (runningRun(this.runs) ? this.#stop() : this.#start()));
    this.startHint = make("span", "ge-dry__hint");
    this.startHint.id = id("hint");
    this.startButton.setAttribute("aria-describedby", this.startHint.id);
    actions.append(this.startButton, this.startHint);

    this.errorLine = make("p", "ge-dry__error");
    this.errorLine.setAttribute("role", "alert");
    this.errorLine.hidden = true;

    this.result = make("section", "ge-dry__result");
    this.result.setAttribute("aria-label", t("editor.dry_run.result_title"));
    this.result.hidden = true;
    this.runList = make("ul", "history-list ge-dry__runs");
    this.runList.setAttribute("aria-label", t("editor.dry_run.result_title"));
    this.historyLink = make("a", "ge-dry__history", t("editor.dry_run.all_in_history"));
    this.historyLink.href = allDryRunsUrl;
    this.result.append(this.runList, this.historyLink);
    this.rows = new HistoryList({ root: this.runList, onOpen: (execution) => this.#open(execution), onDelete: () => {} });

    this.casesBox = make("fieldset", "ge-dry__cases ge-cases");
    this.casesBox.dataset.testCases = "";
    this.casesBox.append(make("legend", "ge-dry__legend", t("editor.dry_run.cases_title")));
    this.casesPick = make("select", "field__control");
    this.casesPick.id = id("cases");
    this.casesPick.setAttribute("aria-label", t("editor.dry_run.cases_pick"));
    this.casesPick.dataset.focusKey = "dry-cases";
    this.casesPick.addEventListener("change", () => this.#useCase(this.casesPick.value));
    this.caseName = make("input", "field__control");
    this.caseName.type = "text";
    this.caseName.maxLength = 60;
    this.caseName.placeholder = t("editor.dry_run.cases_name");
    this.caseName.setAttribute("aria-label", t("editor.dry_run.cases_name"));
    this.caseName.dataset.focusKey = "dry-case-name";
    this.caseSave = make("button", "button button--ghost button--sm", t("editor.dry_run.cases_save"));
    this.caseSave.type = "button";
    this.caseSave.dataset.focusKey = "dry-case-save";
    this.caseSave.addEventListener("click", () => this.#saveCase());
    this.caseDelete = make("button", "button button--ghost button--sm is-danger", t("editor.dry_run.cases_delete"));
    this.caseDelete.type = "button";
    this.caseDelete.dataset.focusKey = "dry-case-delete";
    this.caseDelete.addEventListener("click", () => this.#deleteCase());
    this.caseError = make("p", "ge-mock__error");
    this.caseError.setAttribute("role", "alert");
    this.caseError.hidden = true;
    const caseRow = make("div", "ge-cases__row");
    caseRow.append(this.caseName, this.caseSave, this.caseDelete);
    this.casesBox.append(this.casesPick, caseRow, this.caseError);

    this.element.append(lead, this.cardBox, this.cardNote, this.addButton, this.casesBox, this.inputsBox, versionBox, this.checkLine, actions, this.errorLine, this.result);
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
      this.cardNoCards = options.length === 0;
      const saved = rememberedCard(options, readJson(cardKey(this.graph.id)));
      if (saved) {
        this.shown.add("card");
        this.combo.choose(saved);
      }
      this.#drawItems();
    } catch {
      this.loaded = false;
      this.cardNote.textContent = t("editor.dry_run.error_unknown");
      this.cardFailed = true;
      this.#drawItems();
    }
    await this.#loadHidden();
    this.#syncStart();
  }

  /** The hidden card of this graph, when a card-less dry run made it: its executions are the rows when no card is chosen. */
  async #loadHidden() {
    try {
      this.hidden = await request(this.urls.card);
    } catch {
      this.hidden = { task_id: null, number: null };
    }
    this.#loadRuns();
    this.#scheduleCheck();
  }

  #listTaskId() {
    return listedCard(this.taskId, this.hidden.task_id);
  }

  #pickCard(taskId) {
    this.taskId = taskId;
    if (taskId) writeJson(cardKey(this.graph.id), taskId);
    this.runs = [];
    this.#drawRuns();
    this.#loadRuns();
    this.#scheduleCheck();
    this.#syncStart();
  }

  // ── the optional items behind "+ Add" ───────────────────────────

  #dropItem(key) {
    this.shown.delete(key);
    if (key === "card") {
      this.combo.choose(null);
      this.#pickCard(null);
      writeJson(cardKey(this.graph.id), null); // the card taken away is not brought back by the next window
    }
    this.#drawItems();
    this.addButton.focus();
  }

  /** The optional items that are on the form are drawn, the "+ Add" button offers the rest and is gone when nothing is left. */
  #drawItems() {
    this.cardBox.hidden = !this.shown.has("card");
    this.cardNote.hidden = !(this.shown.has("card") && (this.cardNoCards || this.cardFailed));
    this.addButton.hidden = availableItems(this.shown).length === 0;
  }

  #openAdd() {
    addMenu ??= new ActionMenu();
    const items = availableItems(this.shown).map((item) => ({
      label: t(item.labelKey),
      icon: item.icon,
      onSelect: () => {
        this.shown.add(item.key);
        this.#drawItems();
        if (item.key === "card") this.combo.input.focus();
        this.#syncStart();
      },
    }));
    addMenu.toggle(this.addButton, items, t("editor.dry_run.add_label"));
  }

  // ── the test cases of the Trigger (ADR-087) ────────────────────

  #cases() {
    return this.casesApi?.list() ?? [];
  }

  #drawCases() {
    const cases = this.#cases();
    const chosen = this.chosenCase && cases.some((c) => c.name === this.chosenCase) ? this.chosenCase : "";
    this.chosenCase = chosen;
    this.casesPick.replaceChildren(new Option(t("editor.dry_run.cases_none"), ""), ...cases.map((c) => Object.assign(new Option(c.name, c.name), { selected: c.name === chosen })));
    this.caseDelete.disabled = !chosen;
    this.casesBox.hidden = !this.casesApi;
  }

  /** The values of a test case go into the inputs (what was typed before is replaced); no case leaves them as they are. */
  #useCase(name) {
    this.chosenCase = name;
    const found = this.#cases().find((c) => c.name === name);
    if (found) {
      this.entered = { ...found.inputs };
      this.caseName.value = found.name;
      this.#setFields(this.fields);
      this.#scheduleCheck();
    }
    this.caseDelete.disabled = !found;
  }

  async #storeCases(cases) {
    const refused = await this.casesApi.save(cases);
    this.caseError.textContent = refused ?? "";
    this.caseError.hidden = !refused;
    this.#drawCases();
    return !refused;
  }

  async #saveCase() {
    const name = this.caseName.value.trim();
    if (!name) {
      this.caseError.textContent = t("editor.dry_run.cases_name_needed");
      this.caseError.hidden = false;
      return;
    }
    const given = Object.fromEntries(Object.entries(this.entered).filter(([, v]) => typeof v === "string" && v !== ""));
    const others = this.#cases().filter((c) => c.name !== name);
    if (await this.#storeCases([...others, { name, inputs: given }])) {
      this.chosenCase = name;
      this.#drawCases();
    }
  }

  async #deleteCase() {
    const name = this.chosenCase;
    if (!name) return;
    this.chosenCase = "";
    await this.#storeCases(this.#cases().filter((c) => c.name !== name));
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
    return runBody({ fields: this.fields, entered: this.entered, version: this.version, taskId: this.taskId });
  }

  async #check() {
    const turn = (this.checkTurn += 1);
    this.checkLine.textContent = t("editor.dry_run.checking");
    let problems;
    try {
      problems = problemLines((await request(this.urls.check, { method: "POST", body: JSON.stringify(this.#body()) })).problems);
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

  // ── the start and the stop ────────────────────────────────────

  #syncStart() {
    const stopped = currentStop()?.active === true;
    const active = runningRun(this.runs);
    let reason = "";
    if (active) reason = "";
    else if (stopped) reason = t("editor.dry_run.hint_stopped");
    else if (this.running) reason = t("editor.dry_run.hint_running");
    // While a dry run runs the button is the Stop, as the processing button of an artifact is (ADR-086 addendum 2)
    this.startButton.disabled = Boolean(reason);
    this.startButton.classList.toggle("is-danger", Boolean(active));
    this.startButton.classList.toggle("button--primary", !active);
    this.startButton.dataset.state = active ? "running" : "idle";
    this.startLabel.textContent = active ? t("tasks.processing.stop_processing") : t("editor.dry_run.start");
    const glyph = icon(active ? "stop" : "play");
    this.startIcon.replaceWith(glyph);
    this.startIcon = glyph;
    this.startButton.title = active ? t("tasks.processing.stop_processing") : reason;
    this.startHint.textContent = reason;
  }

  async #start() {
    if (this.startButton.disabled) return;
    this.errorLine.hidden = true;
    this.running = true;
    this.#syncStart();
    try {
      await request(this.urls.start, { method: "POST", body: JSON.stringify(this.#body()) });
      if (!this.taskId) await this.#loadHidden(); // the first run without a card makes the graph's hidden card: its number is what a row opens
    } catch (error) {
      this.errorLine.textContent = startErrorText(error);
      this.errorLine.hidden = false;
      this.running = false;
      this.#syncStart();
      return;
    }
    await this.#loadRuns();
    this.running = false;
    this.#syncStart();
  }

  async #stop() {
    const taskId = this.#listTaskId();
    if (!taskId) return;
    this.errorLine.hidden = true;
    try {
      await stopRun(taskId);
    } catch (error) {
      this.errorLine.textContent = error?.message || t("editor.dry_run.error_unknown");
      this.errorLine.hidden = false;
    }
    await this.#loadRuns();
  }

  // ── the dry runs as rows ─────────────────────────────────────

  #scheduleRuns() {
    window.clearTimeout(this.runsTimer);
    this.runsTimer = window.setTimeout(() => this.#loadRuns(), 250);
  }

  async #loadRuns() {
    const taskId = this.#listTaskId();
    if (!taskId) {
      this.runs = [];
      this.#drawRuns();
      this.#syncStart();
      return;
    }
    let all;
    try {
      all = (await request(`/api/tasks/${encodeURIComponent(taskId)}/executions?limit=100`)).items;
    } catch {
      return;
    }
    if (taskId !== this.#listTaskId()) return; // another card was chosen meanwhile
    this.task = this.tasks?.find((task) => task.id === taskId) ?? null;
    this.runs = listedRuns(all, this.graph.id);
    this.#drawRuns();
    this.#syncStart();
    // the events say when a step is done; a safety net reads again while a run is running, so a missed event never leaves the row at "Running"
    window.clearTimeout(this.pollTimer);
    if (runningRun(this.runs)) this.pollTimer = window.setTimeout(() => this.#loadRuns(), 3000);
  }

  #drawRuns() {
    this.rows.render(this.runs);
    this.result.hidden = this.runs.length === 0;
  }

  /** A click on a row goes where the artifact's list goes: the execution in the history. */
  #open(execution) {
    const number = this.task?.number ?? this.tasks?.find((task) => task.id === execution.task_id)?.number ?? (execution.task_id === this.hidden.task_id ? this.hidden.number : null);
    if (number) window.location.assign(historyUrl(number, execution.id, editorOrigin(window.location.pathname))); // the Back button there returns to this editor
  }
}
