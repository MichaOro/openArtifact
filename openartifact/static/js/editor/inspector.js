/* Building blocks of the inspector. A node's view (node-types.js) lists which blocks it shows; the
 * blocks look and behave the same for every kind: the title renamed in place, the settings of the
 * kind, the choice of what it links to, and one action row New · Edit · Delete. */
import { icon } from "../components/icons.js";
import { InlineName } from "../components/inline-name.js";
import { field } from "./field.js";
import { agentBlock } from "./agent-inspector.js";
import { displayName } from "./geometry.js";
import { typeOf } from "./node-types.js";
import { buildSettings } from "./settings-layout.js";
import { t } from "../i18n.js";

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
    const head = heading(displayName(node), type.subtitle(node), rename);
    const glyph = type.constructor.icon;
    if (!glyph) return head;
    // the icon of the node's kind in its colour, as on the canvas
    const wrap = document.createElement("div");
    wrap.className = "ge-inspector__identity";
    const card = document.querySelector(`.ge-node[data-node-id="${node.id}"]`);
    const colour = card ? getComputedStyle(card).getPropertyValue("--node-color").trim() : "";
    if (colour) wrap.style.setProperty("--node-color", colour);
    const mark = document.createElement("span");
    mark.className = "ge-inspector__icon";
    if (type.ui?.hint) mark.title = type.ui.hint; // a hover line, nothing marks that it is there
    mark.append(icon(glyph));
    wrap.append(mark, head);
    return wrap;
  }

  /** The kind's settings, one control per setting (see setting-controls.js), or nothing. Settings of one
   * `group` (the rows of an If node's conditions) are shown together; a group whose first value is empty
   * is folded away, so five rows do not fill the panel. */
  settings(node) {
    if (!typeOf(node).settings.length) return null;
    return section(null, buildSettings({ node, editor: this.editor, suggest: this.editor.suggestions?.(node) ?? null }));
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
      .catch(() => this.editor.showError(t("editor.inspector.list_could_not_be_loaded")));
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
   * The action row of the settings: only what applies to the node. *New* where it can make what it links to or holds,
   * *Edit* where it links (greyed until it links to something), *Delete* where the node may be deleted.
   * @param {{create?: Function|null, edit?: string|null, remove?: boolean}} actions `edit`: omitted for a node that links to nothing
   */
  actions(node, { create = null, edit = undefined, remove = false } = {}) {
    if (!create && edit === undefined && !remove) return null;
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
    if (create) {
      const newButton = make("button", "plus", t("common.new"));
      newButton.addEventListener("click", create);
      bar.append(newButton);
    }
    if (edit !== undefined) {
      const editLink = make("a", "pencil", t("common.edit"));
      if (edit) editLink.href = edit;
      else editLink.setAttribute("aria-disabled", "true");
      bar.append(editLink);
    }
    if (remove) {
      const removeButton = make("button", "trash", t("common.delete"), "is-danger ge-delete");
      removeButton.addEventListener("click", () => this.editor.remove(node));
      bar.append(removeButton);
    }
    return bar;
  }
}

/**
 * Puts *Delete* (the action row of a node that has nothing else in it) and *Add guard* on one line at the end of the settings:
 * both are short, so they share the width instead of each taking a whole row. Any node with a guard section gets it.
 * @param {HTMLElement} root the settings of the node (the inspector element)
 */
export function joinFooter(root) {
  const bar = [...root.querySelectorAll(".ge-actionbar")].find((b) => b.children.length === 1 && b.querySelector(".ge-delete"));
  const add = root.querySelector("[data-guard-section] [data-add-guard]");
  if (!bar || !add) return;
  const line = document.createElement("div");
  line.className = "ge-footer";
  line.append(add, bar.firstElementChild); // Delete is always the last, on the right
  bar.remove();
  root.querySelector("[data-guard-section]").append(line);
}
