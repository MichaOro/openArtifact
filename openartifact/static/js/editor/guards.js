/* Guards in the pipeline editor (ADR-060). A guard is a definition of the guard library (the Guards page) that is
 * *attached* to the pipeline, a stage or an action; it is never a node of the canvas. Where a scope has attachments it
 * shows ONE small shield: the pipeline's next to the "+" of the canvas, a stage's in its header next to its "+", an
 * action's as a badge on its card. The shield's tooltip says how many guards are configured there; a click opens the
 * popup of that scope's guards (guards/guard-popover.js): their names, the on/off switch and Detach, a name opens the
 * definition in the guard editor (guards/editor-window.js). The Guard entries (the "+" menu, a stage's "+", an action's
 * menu and settings) open the same popup as "Add a guard": attach a definition of the library or make a new one. */
import { icon } from "../components/icons.js";
import { Modal } from "../components/modal.js";
import { request } from "../http.js";
import { t } from "../i18n.js";
import { GuardEditor, loadSchema } from "../guards/editor-window.js";
import { GuardPopover } from "../guards/guard-popover.js";
import * as model from "../guards/model.js";

const ATTACHMENTS = "/api/guard-attachments";
const send = (url, method, data) => request(url, { method, body: data === undefined ? undefined : JSON.stringify(data) });

/** The shield of a scope: an icon button whose tooltip and name say how many guards are configured there. */
export function shieldButton(count, scopeName) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "icon-button icon-button--sm gd-shield";
  button.dataset.guardShield = "";
  button.setAttribute("aria-haspopup", "dialog");
  button.setAttribute("aria-expanded", "false");
  button.append(icon("shield"));
  updateShield(button, count, scopeName);
  button.addEventListener("pointerdown", (event) => event.stopPropagation()); // not the start of dragging a node
  button.addEventListener("dblclick", (event) => event.stopPropagation()); // not the node's settings
  return button;
}

function updateShield(button, count, scopeName) {
  const text = model.shieldText(count);
  button.title = text;
  button.setAttribute("aria-label", scopeName ? `${text}: ${scopeName}` : text);
  button.dataset.count = String(count);
}

export class EditorGuards {
  /**
   * @param {HTMLElement} root the editor element
   * @param {{pipelineId: string, scopeName: (type: string, id: string) => string, actionsPath: string,
   *   pipelineSlug: () => string, confirm: (text: string, action: () => Promise<void>) => void,
   *   showError: (text: string) => void, redraw: () => void}} hooks
   *   redraw: draw the canvas again (its nodes get their shields through `decorate`)
   */
  constructor(root, hooks) {
    this.hooks = hooks;
    this.pipelineId = hooks.pipelineId;
    this.guards = [];
    this.schema = null;
    this.loaded = false;
    this.window = new GuardEditor(new Modal(document.getElementById("guard-modal")), {
      actionUrl: (actionId) => `${hooks.actionsPath}/${encodeURIComponent(actionId)}?from=${encodeURIComponent(hooks.pipelineSlug())}`,
      confirm: hooks.confirm,
      onSaved: () => this.load(),
      onDeleted: () => this.load(),
    });
    this.popover = new GuardPopover({
      attach: (guard) => this.#change(() => send(ATTACHMENTS, "POST", { guard_id: guard.id, pipeline_id: this.pipelineId, scope_type: this.scope.type, scope_id: this.scope.type === "pipeline" ? null : this.scope.id })),
      toggle: (attachment, on) => this.#change(() => send(`${ATTACHMENTS}/${attachment.id}/enabled`, "PUT", { enabled: on })),
      detach: (attachment) => this.#change(() => send(`${ATTACHMENTS}/${attachment.id}`, "DELETE")),
      open: (guard) => this.#openWindow(() => this.window.open(guard)),
      create: () => this.#openWindow(() => this.window.openNew({ attachTo: { pipelineId: this.pipelineId, ...this.scope } })),
    });
    this.pipelineShield = root.querySelector("[data-pipeline-shield]");
    this.pipelineShield?.addEventListener("click", () => this.list("pipeline", this.pipelineId, this.pipelineShield));
  }

  /** Load the library with its attachments and draw the shields. The editor works without them. */
  async load() {
    try {
      const [guards, schema] = await Promise.all([request("/api/guards"), loadSchema()]);
      this.guards = guards;
      this.schema = model.builderSchema(schema);
      this.loaded = true;
    } catch {
      return;
    }
    this.counts = model.countsByScope(this.guards, this.pipelineId);
    this.#drawPipelineShield();
    this.hooks.redraw();
    this.popover.refresh(this.guards, this.schema);
    for (const section of document.querySelectorAll("[data-guard-section]")) {
      section.querySelector(".gd-names")?.replaceWith(this.#names(section.dataset.nodeId));
    }
  }

  count(type, id) {
    return this.counts?.get(`${type}|${id}`) ?? 0;
  }

  /** "Add a guard" for a scope, next to the control that asked for it. */
  add(type, id, trigger) {
    this.#popup("add", type, id, trigger);
  }

  /** The guards of a scope (its shield). */
  list(type, id, trigger) {
    this.#popup("list", type, id, trigger);
  }

  #popup(mode, type, id, trigger) {
    if (!this.loaded) return this.hooks.showError(t("guards.not_loaded"));
    this.scope = { type, id, name: this.hooks.scopeName(type, id) };
    this.popover.toggle(trigger, { mode, scope: this.scope, guards: this.guards, schema: this.schema });
  }

  /** Called for every node the canvas draws: a stage's header and an action's card get their shield (or lose it). */
  decorate(node, el) {
    if (node.kind !== "stage" && node.kind !== "action") return;
    const host = node.kind === "stage" ? el.querySelector(".ge-stage__header") : el;
    if (!host) return;
    const count = this.count(node.kind, node.id);
    let shield = host.querySelector(":scope > [data-guard-shield]");
    if (!count) {
      shield?.remove();
      return;
    }
    const name = this.hooks.scopeName(node.kind, node.id);
    if (shield) {
      updateShield(shield, count, name);
      return;
    }
    shield = shieldButton(count, name);
    if (node.kind === "action") shield.classList.add("gd-shield--node");
    shield.addEventListener("click", (event) => {
      event.stopPropagation();
      this.list(node.kind, node.id, shield);
    });
    if (node.kind === "stage") host.insertBefore(shield, host.querySelector("[data-stage-add]"));
    else host.append(shield);
  }

  #drawPipelineShield() {
    const button = this.pipelineShield;
    if (!button) return;
    const count = this.count("pipeline", this.pipelineId);
    button.hidden = !count;
    if (count) updateShield(button, count, this.hooks.scopeName("pipeline", this.pipelineId));
    if (!count && this.popover.isOpen && this.popover.trigger === button) this.popover.close({ restoreFocus: false });
  }

  /** The "Guards" section of an action's settings: the names of its guards and "Add guard". */
  section(node) {
    const section = document.createElement("div");
    section.className = "ge-inspector__section ge-guard-section";
    section.dataset.guardSection = "";
    const heading = document.createElement("h3");
    heading.textContent = t("guards.guards");
    section.append(heading);
    section.dataset.nodeId = node.id;
    section.append(this.#names(node.id));
    const add = document.createElement("button");
    add.type = "button";
    add.className = "button button--ghost button--sm";
    add.setAttribute("aria-haspopup", "dialog");
    add.setAttribute("aria-expanded", "false");
    add.append(icon("shield"), document.createTextNode(t("guards.add_guard")));
    add.addEventListener("click", () => this.add("action", node.id, add));
    section.append(add);
    return section;
  }

  /** The names of an action's guards (muted while off), or the note that none watches it. */
  #names(actionId) {
    const attached = model.attachedTo(this.guards, "action", actionId);
    if (!attached.length) return Object.assign(document.createElement("p"), { className: "field__help gd-names", textContent: t("guards.none_on_action") });
    const list = document.createElement("ul");
    list.className = "gd-names";
    for (const { attachment, guard } of attached) {
      const item = document.createElement("li");
      item.classList.toggle("is-off", !attachment.enabled);
      item.textContent = attachment.enabled ? guard.name : `${guard.name} (${t("components.switch.off")})`;
      list.append(item);
    }
    return list;
  }

  async #change(call) {
    try {
      await call();
    } catch (error) {
      this.hooks.showError(error.detail ?? t("guards.change_failed"));
    }
    await this.load();
  }

  async #openWindow(show) {
    try {
      await show();
    } catch (error) {
      this.hooks.showError(error.message || t("guards.not_loaded"));
    }
  }
}
