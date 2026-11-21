/* Processing of an artifact in a pipeline: the Pipeline / Stage / Action fields and the Start / Stop
 * button of the dialog's rail, and the state of every run (kept current by `run.updated` events).
 * While a run is running the artifact is locked: lane, parent, pipeline, stage and action can only
 * be changed by the system, and the card cannot be moved or deleted. */
import { request } from "../http.js";

const send = (url, body) => request(url, { method: "POST", body: body && JSON.stringify(body) });

export const listRuns = () => request("/api/runs");
const startRun = (taskId, body) => send(`/api/tasks/${encodeURIComponent(taskId)}/run`, body);
const stopRun = (taskId) => send(`/api/tasks/${encodeURIComponent(taskId)}/run/stop`);
const listPipelines = () => request("/api/pipelines");
const listStages = (pipelineId) => request(`/api/pipelines/${encodeURIComponent(pipelineId)}/stages`);

const STATUS_TEXT = { running: "running", stopped: "stopped", done: "done", failed: "failed" };

export class ProcessingPanel {
  /**
   * @param {object} options
   * @param {HTMLElement} options.rail the card navigation of the dialog
   * @param {HTMLElement} options.button the Start / Stop button (in the footer of the dialog's reading view)
   * @param {import("../components/lane-picker.js").LanePicker} options.picker the popover list used by the other rail fields
   * @param {(taskId: string, locked: boolean) => void} options.onLock called when a task is locked or unlocked
   * @param {(message: string) => void} options.onError
   */
  constructor({ rail, button, picker, onLock, onError }) {
    this.picker = picker;
    this.onLock = onLock;
    this.onError = onError;
    this.runs = new Map();
    this.draft = new Map(); // task id -> {pipeline, stage, action} to start with
    this.touched = new Set(); // tasks whose fields show the user's choice instead of where the run is
    this.pipelines = [];
    this.chains = new Map(); // pipeline id -> stages with their actions
    this.taskId = null;

    this.fields = Object.fromEntries(
      ["pipeline", "stage", "action"].map((key) => [key, rail.querySelector(`[data-card-field="${key}"]`)]),
    );
    this.values = Object.fromEntries(
      ["pipeline", "stage", "action"].map((key) => [key, rail.querySelector(`[data-${key}-value]`)]),
    );
    this.button = button;
    this.buttonLabel = button.querySelector("[data-run-label]");
    this.buttonIcon = this.button.querySelector(".icon");
    this.lockedFields = rail.querySelectorAll('[data-card-field="lane"], [data-card-field="parent"], [data-card-field="pipeline"], [data-card-field="stage"], [data-card-field="action"]');

    for (const key of ["pipeline", "stage", "action"]) {
      this.fields[key].addEventListener("click", (event) => this.#pick(key, event.currentTarget));
    }
    this.button.addEventListener("click", () => this.#toggle());
  }

  isLocked(taskId) {
    return this.runs.get(taskId)?.status === "running";
  }

  setRuns(runs) {
    const was = new Set([...this.runs].filter(([, r]) => r.status === "running").map(([id]) => id));
    this.runs = new Map(runs.map((run) => [run.task_id, run]));
    this.touched.clear();
    for (const id of new Set([...was, ...this.runs.keys()])) this.#changed(id, was.has(id));
  }

  upsert(run) {
    const wasLocked = this.isLocked(run.task_id);
    this.runs.set(run.task_id, run);
    this.touched.delete(run.task_id); // the fields follow the run again
    this.#changed(run.task_id, wasLocked);
  }

  remove(taskId) {
    const wasLocked = this.isLocked(taskId);
    this.runs.delete(taskId);
    this.draft.delete(taskId);
    this.touched.delete(taskId);
    this.#changed(taskId, wasLocked);
  }

  #changed(taskId, wasLocked) {
    if (this.isLocked(taskId) !== wasLocked) this.onLock(taskId, this.isLocked(taskId));
    this.onRun?.(taskId, this.runs.get(taskId) ?? null);
    if (taskId === this.taskId) this.render();
  }

  /** Show the fields for this artifact (null: none is open). */
  async show(taskId) {
    this.taskId = taskId;
    if (!taskId) return;
    if (!this.pipelines.length) await this.#loadPipelines();
    await this.#ensureDraft(taskId);
    if (this.taskId === taskId) this.render();
  }

  async #loadPipelines() {
    try {
      this.pipelines = await listPipelines();
    } catch {
      this.onError("The pipelines could not be loaded.");
    }
  }

  async #chain(pipelineId) {
    if (!this.chains.has(pipelineId)) {
      try {
        this.chains.set(pipelineId, await listStages(pipelineId));
      } catch {
        return [];
      }
    }
    return this.chains.get(pipelineId);
  }

  /** What would be started: where the artifact is, or else the first stage of its pipeline. */
  async #ensureDraft(taskId) {
    const run = this.runs.get(taskId);
    let draft = this.draft.get(taskId);
    if (run && run.status !== "running" && !draft) {
      const resume = run.status === "stopped" || run.status === "failed";
      draft = { pipeline: run.root_pipeline_id, stage: resume ? run.resume_stage_id : null, action: resume ? run.resume_action_id : null };
    }
    draft ??= { pipeline: this.pipelines.length === 1 ? this.pipelines[0].id : null, stage: null, action: null };
    if (draft.pipeline && !this.pipelines.some((p) => p.id === draft.pipeline)) draft = { pipeline: null, stage: null, action: null };
    if (draft.pipeline) {
      const chain = await this.#chain(draft.pipeline);
      const stage = chain.find((s) => s.id === draft.stage) ?? chain[0];
      const action = stage?.actions.find((a) => a.id === draft.action)?.id ?? stage?.first_action_id ?? null;
      draft = { ...draft, stage: stage?.id ?? null, action };
    }
    this.draft.set(taskId, draft);
  }

  render() {
    const run = this.runs.get(this.taskId);
    const locked = run?.status === "running";
    const draft = this.draft.get(this.taskId) ?? {};
    const chain = this.chains.get(draft.pipeline) ?? [];
    const stage = chain.find((s) => s.id === draft.stage);
    // while a run exists the fields show where it is (following the flow into called pipelines), until the
    // user picks something to start with
    const following = run && !this.touched.has(this.taskId);
    const text = following
      ? { pipeline: run.pipeline_name, stage: run.stage_name ?? "–", action: run.action_name ?? "–" }
      : {
          pipeline: this.pipelines.find((p) => p.id === draft.pipeline)?.name ?? "–",
          stage: stage?.name ?? "–",
          action: stage?.actions.find((a) => a.id === draft.action)?.name ?? "–",
        };
    for (const key of Object.keys(text)) {
      this.values[key].textContent = text[key];
      this.fields[key].setAttribute("aria-label", `${key[0].toUpperCase()}${key.slice(1)}: ${text[key]}`);
    }
    this.lockedFields.forEach((el) => {
      el.dataset.locked = String(locked);
      el.setAttribute("aria-disabled", String(locked));
    });
    const canStart = Boolean(draft.pipeline && draft.stage);
    this.button.dataset.state = locked ? "running" : "idle";
    this.button.disabled = !locked && !canStart;
    this.buttonLabel.textContent = locked ? "Stop processing" : "Start processing";
    this.button.title = locked ? "Stop processing" : canStart ? "Start processing" : "Choose a pipeline first";
    this.buttonIcon.replaceWith(this.#icon(locked ? "stop" : "play"));
    this.buttonIcon = this.button.querySelector(".icon");
  }

  #icon(name) {
    const template = document.getElementById("run-icons");
    return template.content.querySelector(`[data-icon=${name}]`).firstElementChild.cloneNode(true);
  }

  async #pick(key, trigger) {
    if (this.isLocked(this.taskId)) return;
    const taskId = this.taskId;
    const draft = { ...(this.draft.get(taskId) ?? {}) };
    let items = [];
    if (key === "pipeline") {
      items = this.pipelines.map((p) => ({ value: p.id, label: p.name, selected: p.id === draft.pipeline }));
    } else if (draft.pipeline) {
      const chain = await this.#chain(draft.pipeline);
      if (key === "stage") items = chain.map((s) => ({ value: s.id, label: s.name, selected: s.id === draft.stage }));
      else items = (chain.find((s) => s.id === draft.stage)?.actions ?? []).map((a) => ({ value: a.id, label: a.name, selected: a.id === draft.action }));
    }
    if (!items.length) return;
    this.picker.toggle({
      trigger,
      items,
      caption: key[0].toUpperCase() + key.slice(1),
      placement: "left",
      onSelect: async (value) => {
        const next = { ...draft, [key]: value };
        if (key === "pipeline") Object.assign(next, { stage: null, action: null });
        if (key === "stage") next.action = null;
        this.draft.set(taskId, next);
        this.touched.add(taskId);
        await this.#ensureDraft(taskId);
        if (this.taskId === taskId) this.render();
      },
    });
  }

  async #toggle() {
    const taskId = this.taskId;
    if (!taskId) return;
    try {
      if (this.isLocked(taskId)) {
        this.upsert(await stopRun(taskId));
      } else {
        const draft = this.draft.get(taskId);
        this.upsert(await startRun(taskId, { pipeline_id: draft.pipeline, stage_id: draft.stage, action_id: draft.action }));
      }
    } catch (error) {
      this.onError(error.status === 409 ? "The artifact is already being processed." : error.message || "That did not work.");
    }
  }

  /** Short text for the card: the stage and the state. */
  static summary(run) {
    if (!run) return null;
    return `${run.stage_name ?? run.pipeline_name} · ${STATUS_TEXT[run.status]}`;
  }
}
