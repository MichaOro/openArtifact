/* Building blocks of the inspector. A node's view (node-types.js) lists which blocks it shows; the
 * blocks look and behave the same for every kind: the title renamed in place, the settings of the
 * kind, the choice of what it links to, and one action row New · Edit · Delete. */
import { icon } from "../components/icons.js";
import { InlineName } from "../components/inline-name.js";
import { EDGE_STYLES, displayName } from "./geometry.js";
import { typeOf } from "./node-types.js";

let fieldCount = 0;

/** Title and caption; `rename` ({label, onCommit}) makes the title editable in place. */
export function heading(text, caption, rename = null) {
  const wrap = document.createElement("div");
  wrap.className = "ge-inspector__heading";
  const title = document.createElement("h2");
  title.textContent = text;
  title.dataset.focusKey = "title";
  wrap.append(title);
  if (rename) new InlineName(title, rename);
  if (caption && caption !== text) {
    const small = document.createElement("p");
    small.textContent = caption;
    wrap.append(small);
  }
  return wrap;
}

/** A labelled control; `row` puts label and control on one line. */
export function field(label, control, { row = false } = {}) {
  const wrap = document.createElement("div");
  wrap.className = row ? "field field--row" : "field";
  const text = document.createElement("label");
  text.className = "field__label";
  text.textContent = label;
  control.id ||= `ge-field-${(fieldCount += 1)}`;
  text.htmlFor = control.id;
  wrap.append(text, control);
  return wrap;
}

export function note(text) {
  const p = document.createElement("p");
  p.className = "ge-inspector__note";
  p.textContent = text;
  return p;
}

function section(title, ...children) {
  const wrap = document.createElement("div");
  wrap.className = "ge-inspector__section";
  if (title) {
    const h = document.createElement("h3");
    h.textContent = title;
    wrap.append(h);
  }
  wrap.append(...children);
  return wrap;
}

/** An On / Off switch with its state written in it. */
function switchControl(key, on, onChange) {
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "ge-switch";
  toggle.dataset.focusKey = `setting-${key}`;
  toggle.setAttribute("role", "switch");
  toggle.setAttribute("aria-checked", String(on));
  const state = document.createElement("span");
  state.className = "ge-switch__state";
  state.textContent = on ? "On" : "Off";
  const thumb = document.createElement("span");
  thumb.className = "ge-switch__thumb";
  toggle.append(state, thumb);
  toggle.addEventListener("click", () => onChange(!on));
  return toggle;
}

function integerControl(setting, value, onChange) {
  const input = document.createElement("input");
  input.className = "field__control";
  input.dataset.focusKey = `setting-${setting.key}`;
  input.type = "number";
  input.step = "1";
  if (setting.minimum != null) input.min = String(setting.minimum);
  if (setting.maximum != null) input.max = String(setting.maximum);
  input.value = String(value ?? setting.default ?? "");
  input.addEventListener("change", () => {
    let number = Math.round(Number(input.value));
    if (!Number.isFinite(number)) number = value;
    if (setting.minimum != null) number = Math.max(setting.minimum, number);
    if (setting.maximum != null) number = Math.min(setting.maximum, number);
    input.value = String(number);
    if (number !== value) onChange(number);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") input.blur();
  });
  return input;
}

/**
 * The blocks for one editor. `editor` provides what the blocks do:
 *   setSetting(node, key, value), link(node, targetId), askNew(node), linkUrl(node), remove(node),
 *   addAction(stage), listTargets(kind), showError(message), renameNode(node, name),
 *   renameGraph(name), removeEdge(id), restyle(edge, style)
 * `model` is the GraphModel the blocks describe.
 */
export class InspectorBlocks {
  constructor(editor, model) {
    this.editor = editor;
    this.model = model;
  }

  /** What the inspector shows when nothing is selected. */
  summary() {
    const { graph, isAction } = this.model;
    return [
      heading(graph?.name ?? "Pipeline", "Draft", { label: isAction ? "Action name" : "Pipeline name", onCommit: (name) => this.editor.renameGraph(name) }),
      note(
        isAction
          ? "The trigger starts this action automatically; the output always offers On Pass and optionally On Fail."
          : `${this.model.count("stage")} stages, ${this.model.count("action")} actions. Select a node to edit it, drag from a port to connect.`,
      ),
    ];
  }

  /** The title of a node (renamable in place if its kind allows it). */
  title(node) {
    const type = typeOf(node);
    const rename = type.renamable(node) ? { label: `${type.label} name`, onCommit: (name) => this.editor.renameNode(node, name) } : null;
    return heading(displayName(node), type.caption(node) ?? type.label, rename);
  }

  /** A connection: where it goes, its line style, and removing it. */
  connection(edge) {
    const source = this.model.nodes.get(edge.source_id);
    const target = this.model.nodes.get(edge.target_id);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "button button--ghost ge-delete";
    remove.dataset.focusKey = "remove";
    remove.textContent = "Delete connection";
    remove.addEventListener("click", () => this.editor.removeEdge(edge.id));
    const styles = document.createElement("div");
    styles.className = "ge-styles";
    styles.setAttribute("role", "group");
    styles.setAttribute("aria-label", "Line style");
    for (const [value, label] of Object.entries(EDGE_STYLES)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ge-style";
      button.dataset.style = value;
      button.dataset.focusKey = `style-${value}`;
      button.textContent = label;
      button.setAttribute("aria-pressed", String(edge.style === value));
      button.addEventListener("click", () => this.editor.restyle(edge, value));
      styles.append(button);
    }
    const route = `${source ? displayName(source) : "?"} (${source ? typeOf(source).portLabel(edge.source_port) : "?"}) → ${target ? displayName(target) : "?"}`;
    return [heading("Connection", route), field("Line", styles), remove];
  }

  /** The kind's settings (a number, a switch ...), or nothing. */
  settings(node) {
    const settings = typeOf(node).settings;
    if (!settings.length) return null;
    return section(
      null,
      ...settings.map((setting) =>
        setting.type === "switch"
          ? field(setting.label, switchControl(setting.key, Boolean(node[setting.key]), (on) => this.editor.setSetting(node, setting.key, on)), { row: true })
          : field(setting.label, integerControl(setting, node[setting.key], (n) => this.editor.setSetting(node, setting.key, n))),
      ),
    );
  }

  /** The choice of what the node links to (an action definition, a pipeline to call). */
  link(node, title, label, none) {
    const select = document.createElement("select");
    select.className = "field__control";
    select.dataset.focusKey = "link";
    select.append(new Option(none, ""));
    select.addEventListener("change", () => this.editor.link(node, select.value || null));
    this.editor
      .listTargets(typeOf(node).links_to)
      .then((targets) => {
        for (const target of targets.filter((t) => t.id !== this.model.id)) {
          const option = new Option(target.name, target.id);
          option.selected = target.id === node.definition_id;
          select.append(option);
        }
      })
      .catch(() => this.editor.showError("The list could not be loaded."));
    return section(title, field(label, select));
  }

  /** New / Edit / Delete for a node that links to something: create one, open it, remove the node. */
  linkActions(node) {
    return {
      create: () => this.editor.askNew(node),
      edit: node.definition_id ? this.editor.linkUrl(node) : null,
      remove: true,
    };
  }

  addAction(stage) {
    this.editor.addAction(stage);
  }

  /**
   * The action row, always New · Edit · Delete in this order; what does not apply is greyed out.
   * @param {{create?: Function, edit?: string|null, remove?: boolean}} actions
   */
  actions(node, { create = null, edit = null, remove = false } = {}) {
    if (!create && !edit && !remove) return null;
    const bar = document.createElement("div");
    bar.className = "ge-actionbar";
    const make = (tag, glyph, text, className = "") => {
      const el = document.createElement(tag);
      el.dataset.focusKey = text.toLowerCase();
      el.className = `button button--ghost button--sm ${className}`.trim();
      if (tag === "button") el.type = "button";
      el.append(icon(glyph), document.createTextNode(text));
      return el;
    };
    const newButton = make("button", "plus", "New");
    if (create) newButton.addEventListener("click", create);
    else newButton.disabled = true;
    const editLink = make("a", "pencil", "Edit");
    if (edit) editLink.href = edit;
    else editLink.setAttribute("aria-disabled", "true");
    const removeButton = make("button", "trash", "Delete", "ge-delete");
    if (remove) removeButton.addEventListener("click", () => this.editor.remove(node));
    else removeButton.disabled = true;
    bar.append(newButton, editLink, removeButton);
    return bar;
  }
}
