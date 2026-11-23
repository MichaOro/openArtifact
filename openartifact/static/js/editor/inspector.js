/* Building blocks of the inspector. A node's view (node-types.js) lists which blocks it shows; the
 * blocks look and behave the same for every kind: the title renamed in place, the settings of the
 * kind, the choice of what it links to, and one action row New · Edit · Delete. */
import { icon } from "../components/icons.js";
import { InlineName } from "../components/inline-name.js";
import { field } from "./field.js";
import { agentBlock } from "./agent-inspector.js";
import { displayName } from "./geometry.js";
import { typeOf } from "./node-types.js";
import { createControl, settingValue } from "./setting-controls.js";

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

/**
 * The blocks for one editor. `editor` provides what the blocks do:
 *   saveSetting(node, setting, value) (resolves to null, or to why it was refused), link(node, targetId), askNew(node), linkUrl(node), remove(node),
 *   addAction(stage), listTargets(kind), showError(message), renameNode(node, name)
 * `model` is the GraphModel the blocks describe.
 */
export class InspectorBlocks {
  constructor(editor, model) {
    this.editor = editor;
    this.model = model;
  }

  /** The title of a node (renamable in place if its kind allows it). */
  title(node) {
    const type = typeOf(node);
    const rename = type.renamable(node) ? { label: `${type.label} name`, onCommit: (name) => this.editor.renameNode(node, name) } : null;
    return heading(displayName(node), type.subtitle(node), rename);
  }

  /** The kind's settings, one control per setting (see setting-controls.js), or nothing. Settings of one
   * `group` (the rows of an If node's conditions) are shown together; a group whose first value is empty
   * is folded away, so five rows do not fill the panel. */
  settings(node) {
    const settings = typeOf(node).settings;
    if (!settings.length) return null;
    const suggest = this.editor.suggestions?.(node) ?? null;
    const control = (setting) => createControl(setting, settingValue(node, setting), (value) => this.editor.saveSetting(node, setting, value), suggest);
    const parts = [];
    for (const setting of settings) {
      const made = control(setting);
      if (!setting.group) {
        parts.push(made.element);
        continue;
      }
      let group = parts.at(-1);
      if (group?.dataset.group !== setting.group) {
        group = document.createElement("details");
        group.className = "ge-group";
        group.dataset.group = setting.group;
        // the kind may know better (a Switch case with "is empty" is used without a value); else the first
        // setting of a group is its main value
        const used = typeOf(node).groupUsed?.(node, setting.group) ?? String(settingValue(node, setting) ?? "").trim() !== "";
        group.append(Object.assign(document.createElement("summary"), { textContent: used ? setting.group : `${setting.group} (empty)` }));
        group.open = used || setting.key.endsWith("_1");
        parts.push(group);
      }
      group.append(made.element);
    }
    return section(null, ...parts);
  }

  /** An agent node: its agent, the input mapping and the settings with their overrides (agent-inspector.js). */
  agent(node) {
    return agentBlock(node, typeOf(node), this.editor);
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
    const removeButton = make("button", "trash", "Delete", "is-danger ge-delete");
    if (remove) removeButton.addEventListener("click", () => this.editor.remove(node));
    else removeButton.disabled = true;
    bar.append(newButton, editLink, removeButton);
    return bar;
  }
}
