/* Guards in the pipeline editor and in the action editor (ADR-060). A guard is a definition of the guard library (the
 * Guards page) that is *attached* to a scope; it is never a node of the canvas. In a pipeline the scopes are the
 * pipeline, a stage and an action; in an action definition they are the whole action (``definition``) and each of its
 * execution nodes (``node``, the kinds whose manifest says ``guardable``). Where a scope has attachments it shows ONE
 * small shield: the graph's next to the "+" of the canvas, a stage's in its header next to its "+", a card's as a bare
 * icon in its top right corner. The card of an action in a pipeline also counts the guards INSIDE its definition
 * (mirrored: the shield's popup lists them under "In the action"). The shield's tooltip says how many guards are
 * configured there; a click opens the popup of that scope's guards (guards/guard-popover.js): their names, the on/off
 * switch and Detach, a name opens the definition in the guard editor (guards/editor-window.js). The Guard entries (the
 * "+" menu, a stage's "+", a node's menu and settings) open the same popup as "Add a guard": "New guard" makes a new
 * definition, "Attach guard" opens the attach dialog (a combobox of the guards that are not attached here yet). One
 * implementation for every scope: only the scope's type and id differ. */
import { icon } from "../components/icons.js";
import { shieldButton, updateShield } from "../components/guard-shield.js";
import { Modal } from "../components/modal.js";
import { request } from "../http.js";
import { t } from "../i18n.js";
import { GuardEditor, loadSchema } from "../guards/editor-window.js";
import { GuardAttachDialog } from "../guards/attach-dialog.js";
import { GuardPopover } from "../guards/guard-popover.js";
import * as model from "../guards/model.js";

const ATTACHMENTS = "/api/guard-attachments";
const send = (url, method, data) => request(url, { method, body: data === undefined ? undefined : JSON.stringify(data) });

export class EditorGuards {
  /**
   * @param {HTMLElement} root the editor element
   * @param {{graphId: string, isAction: boolean, scopeName: (type: string, id: string) => string, actionsPath: string,
   *   pipelineSlug: () => string, confirm: (text: string, action: () => Promise<void>, options?: object) => void,
   *   guardable: (node: object) => boolean, definitionOf: (nodeId: string) => string|null,
   *   showError: (text: string) => void, redraw: () => void}} hooks
   *   graphId: the pipeline or action definition being edited; redraw: draw the canvas again (its nodes get their
   *   shields through `decorate`)
   */
  constructor(root, hooks) {
    this.hooks = hooks;
    this.graphId = hooks.graphId;
    this.rootType = hooks.isAction ? "definition" : "pipeline"; // what the shield next to the "+" stands for
    this.guards = [];
    this.schema = null;
    this.loaded = false;
    this.window = new GuardEditor(new Modal(document.getElementById("guard-modal")), {
      actionUrl: (actionId) => this.#actionUrl(actionId),
      confirm: hooks.confirm,
      onSaved: () => this.load(),
      onDeleted: () => this.load(),
    });
    this.attachDialog = new GuardAttachDialog(new Modal(document.getElementById("guard-attach-modal")), {
      attach: async (guard, scope) => {
        await this.#change(() => send(ATTACHMENTS, "POST", { guard_id: guard.id, graph_id: this.graphId, scope_type: scope.type, scope_id: model.isGraphScope(scope.type) ? null : scope.id }));
        this.#popup("add", scope.type, scope.id, this.opener); // back to the popup, now with the guard under "Attached here"
      },
    });
    this.popover = new GuardPopover({
      chooseAttach: () => {
        this.opener = this.popover.trigger;
        this.popover.close({ restoreFocus: false });
        this.attachDialog.open({ scope: this.scope, guards: this.guards, schema: this.schema });
      },
      toggle: (attachment, on) => this.#change(() => send(`${ATTACHMENTS}/${attachment.id}/enabled`, "PUT", { enabled: on })),
      detach: (attachment) => this.#change(() => send(`${ATTACHMENTS}/${attachment.id}`, "DELETE")),
      open: (guard) => this.#openWindow(() => this.window.open(guard)),
      create: () => this.#openWindow(() => this.window.openNew({ attachTo: { graphId: this.graphId, ...this.scope } })),
    });
    this.rootShield = root.querySelector("[data-pipeline-shield]"); // the graph's own shield (a pipeline's or an action's)
    this.rootShield?.addEventListener("click", () => this.list(this.rootType, this.graphId, this.rootShield));
  }

  #actionUrl(actionId) {
    const from = this.hooks.pipelineSlug();
    return `${this.hooks.actionsPath}/${encodeURIComponent(actionId)}${from ? `?from=${encodeURIComponent(from)}` : ""}`;
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
    this.counts = model.countsByScope(this.guards, this.graphId);
    this.#drawRootShield();
    this.hooks.redraw();
    this.popover.refresh(this.guards, this.schema);
    for (const section of document.querySelectorAll("[data-guard-section]")) {
      section.querySelector(".gd-names")?.replaceWith(this.#names(section.dataset.scopeType ?? "action", section.dataset.nodeId));
      section.querySelector("h3").hidden = !section.querySelector(".gd-names:not([hidden])");
    }
  }

  count(type, id) {
    return this.counts?.get(`${type}|${id}`) ?? 0;
  }

  /** The guards inside the action definition an action card runs (zero when it is not linked or in an action editor). */
  #inner(type, id) {
    const definitionId = type === "action" ? this.hooks.definitionOf?.(id) : null;
    return { definitionId, inner: model.innerOf(this.guards, definitionId) };
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
    const { definitionId, inner } = this.#inner(type, id);
    this.scope = { type, id, name: this.hooks.scopeName(type, id), definitionId, inner, actionHref: definitionId ? this.#actionUrl(definitionId) : null };
    // opened from a stage header or a card it would cover them side by side: the buttons stack there (ui-catalog.md)
    const stack = Boolean(trigger?.closest?.(".ge-node"));
    this.popover.toggle(trigger, { mode, scope: this.scope, guards: this.guards, schema: this.schema, stack });
  }

  /** Which scope a node of the editor stands for: a stage or an action in a pipeline, a guardable node in an action. */
  scopeTypeOf(node) {
    if (this.hooks.isAction) return this.hooks.guardable(node) ? "node" : null;
    return node.kind === "stage" || node.kind === "action" ? node.kind : null;
  }

  /** Called for every node the canvas draws: what can be watched gets its shield (or loses it). */
  decorate(node, el) {
    const type = this.scopeTypeOf(node);
    if (!type) return;
    const host = type === "stage" ? el.querySelector(".ge-stage__header") : el;
    if (!host) return;
    const count = this.count(type, node.id) + this.#inner(type, node.id).inner.length;
    let shield = host.querySelector(":scope > [data-guard-shield]");
    if (!count) {
      shield?.remove();
      return;
    }
    const name = this.hooks.scopeName(type, node.id);
    if (shield) {
      updateShield(shield, count, name);
      return;
    }
    shield = shieldButton(count, name);
    if (type !== "stage") shield.classList.add("gd-shield--node");
    shield.addEventListener("click", (event) => {
      event.stopPropagation();
      this.list(type, node.id, shield);
    });
    if (type === "stage") host.insertBefore(shield, host.querySelector("[data-stage-add]"));
    else host.append(shield);
  }

  #drawRootShield() {
    const button = this.rootShield;
    if (!button) return;
    const count = this.count(this.rootType, this.graphId);
    if (this.hooks.bar) this.hooks.bar.set("guard", Boolean(count));
    else button.hidden = !count;
    if (count) updateShield(button, count, this.hooks.scopeName(this.rootType, this.graphId));
    if (!count && this.popover.isOpen && this.popover.trigger === button) this.popover.close({ restoreFocus: false });
  }

  /** The "Guards" section of the settings of an action (in a pipeline) or of a node (in an action): the names of its
   * guards and "Add guard". */
  section(node) {
    const type = this.scopeTypeOf(node) ?? "action";
    const section = document.createElement("div");
    section.className = "ge-inspector__section ge-guard-section";
    section.dataset.guardSection = "";
    const heading = document.createElement("h3");
    heading.textContent = t("guards.guards");
    section.append(heading);
    section.dataset.nodeId = node.id;
    section.dataset.scopeType = type;
    section.append(this.#names(type, node.id));
    heading.hidden = Boolean(section.querySelector(".gd-names[hidden]")); // nothing to say, nothing shown: no empty area
    const add = document.createElement("button");
    add.type = "button";
    add.className = "button button--ghost button--sm";
    add.dataset.addGuard = "";
    add.setAttribute("aria-haspopup", "dialog");
    add.setAttribute("aria-expanded", "false");
    add.append(icon("shield"), document.createTextNode(t("guards.add_guard")));
    add.addEventListener("click", () => this.add(type, node.id, add));
    section.append(add);
    return section;
  }

  /** The names of a scope's guards (muted while off), or the note that none watches it. */
  #names(type, id) {
    const attached = model.attachedTo(this.guards, type, id);
    if (!attached.length) return Object.assign(document.createElement("ul"), { className: "gd-names", hidden: true });
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
