/* Building blocks of the inspector. A node's view (node-types.js) lists which blocks it shows; the
 * blocks look and behave the same for every kind: the title renamed in place, the settings of the
 * kind, the choice of what it links to, and one action row New · Edit · Delete. */
import { InlineName } from "../components/inline-name.js";
import { typeOf } from "./node-types.js";

/** Title and caption; `rename` ({label, onCommit}) makes the title editable in place. */
export function heading(text, caption, rename = null) {
  const wrap = document.createElement("div");
  wrap.className = "wf-inspector__heading";
  const title = document.createElement("h2");
  title.textContent = text;
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
  control.id = control.id || `wf-field-${Math.random().toString(36).slice(2, 8)}`;
  text.htmlFor = control.id;
  wrap.append(text, control);
  return wrap;
}

export function note(text) {
  const p = document.createElement("p");
  p.className = "wf-inspector__note";
  p.textContent = text;
  return p;
}

function section(title, ...children) {
  const wrap = document.createElement("div");
  wrap.className = "wf-inspector__section";
  if (title) {
    const h = document.createElement("h3");
    h.textContent = title;
    wrap.append(h);
  }
  wrap.append(...children);
  return wrap;
}

/** An On / Off switch with its state written in it. */
function switchControl(on, onChange) {
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "wf-switch";
  toggle.setAttribute("role", "switch");
  toggle.setAttribute("aria-checked", String(on));
  const state = document.createElement("span");
  state.className = "wf-switch__state";
  state.textContent = on ? "On" : "Off";
  const thumb = document.createElement("span");
  thumb.className = "wf-switch__thumb";
  toggle.append(state, thumb);
  toggle.addEventListener("click", () => onChange(!on));
  return toggle;
}

function integerControl(setting, value, onChange) {
  const input = document.createElement("input");
  input.className = "field__control";
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

const ICON_PATHS = {
  plus: "M12 5v14M5 12h14",
  pencil: "M17 3a2.85 2.85 0 0 1 4 4L7.5 20.5 2 22l1.5-5.5Z",
  trash: "M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6",
};

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.75");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICON_PATHS[name]);
  svg.append(path);
  return svg;
}

/**
 * The blocks for one editor. `editor` provides what the blocks do:
 *   setSetting(node, key, value), link(node, targetId), askNew(node), linkUrl(node),
 *   remove(node), addAction(stage), listTargets(kind), currentId, showError(message)
 */
export class InspectorBlocks {
  constructor(editor) {
    this.editor = editor;
  }

  /** The kind's settings (a number, a switch ...), or nothing. */
  settings(node) {
    const settings = typeOf(node).settings;
    if (!settings.length) return null;
    return section(
      null,
      ...settings.map((setting) =>
        setting.type === "switch"
          ? field(setting.label, switchControl(Boolean(node[setting.key]), (on) => this.editor.setSetting(node, setting.key, on)), { row: true })
          : field(setting.label, integerControl(setting, node[setting.key], (n) => this.editor.setSetting(node, setting.key, n))),
      ),
    );
  }

  /** The choice of what the node links to (an action definition, a pipeline to call). */
  link(node, title, label, none) {
    const select = document.createElement("select");
    select.className = "field__control";
    select.append(new Option(none, ""));
    select.addEventListener("change", () => this.editor.link(node, select.value || null));
    this.editor
      .listTargets(typeOf(node).links_to)
      .then((targets) => {
        for (const target of targets.filter((t) => t.id !== this.editor.currentId)) {
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
    bar.className = "wf-actionbar";
    const make = (tag, glyph, text, className = "") => {
      const el = document.createElement(tag);
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
    const removeButton = make("button", "trash", "Delete", "wf-delete");
    if (remove) removeButton.addEventListener("click", () => this.editor.remove(node));
    else removeButton.disabled = true;
    bar.append(newButton, editLink, removeButton);
    return bar;
  }
}
