/* The settings of a node as the dialog shows them (ADR-053): one canonical layout for every kind. What is shown is
 * decided by settings-plan.js from what the server says about each setting (section, level, parent); this draws it:
 *
 *  - *Definition* (left) and *Behaviour* (right) columns, two only when both have something, stacked when narrow;
 *  - core settings always, optional ones once set or added through "Add setting", advanced ones folded;
 *  - a setting that has a parent supplying its value is an override row (components/override-row.js);
 *  - groups: in Definition a group of settings folds when unused (If conditions, Switch cases); in Behaviour a
 *    group is a titled block (Model & Generation, Execution limits).
 * Controls save as the user works, as ever; nothing here has a Save button. */
import { ActionMenu } from "../components/action-menu.js";
import { icon } from "../components/icons.js";
import { overrideRow } from "../components/override-row.js";
import { createControl, settingValue } from "./setting-controls.js";
import { groupsOf, optionLabel, planSettings } from "./settings-plan.js";
import { typeOf } from "./node-types.js";
import { t } from "../i18n.js";

const menu = new ActionMenu();
/** Optional settings added (and overrides being made) that store nothing yet, by node: they live until the dialog closes. */
const opened = new Map();

export function forgetOpened(nodeId) {
  opened.delete(nodeId);
}

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

const TITLES = { definition: t("editor.node_types.definition"), behaviour: t("editor.settings_layout.behaviour") };

/**
 * @param {object} options
 * @param {object} options.node
 * @param {{saveSetting: Function, refresh: () => void}} options.editor what a setting's control calls
 * @param {{nodes: () => object[], exceptId?: string}|null} options.suggest for the ${...} suggestions
 * @param {string[]} [options.skip] keys the kind draws itself
 * @param {HTMLElement[]} [options.extras] what the kind puts at the top of the definition (the agent's choice, inputs)
 * @param {object|null} [options.inheritance] the parent's side: `source` ("Agent"), `state(key)` -> `{value, inherited,
 *   overridden}` or null, `show(setting, value)` -> text, `setting(setting)` -> the setting a control is made from,
 *   `refresh()` to draw again after a change
 */
export function buildSettings({ node, editor, suggest, skip = [], extras = [], inheritance = null }) {
  const type = typeOf(node);
  const plan = planSettings(type.settings, node, { skip });
  const order = new Map(type.settings.map((s, i) => [s.key, i]));
  const redraw = () => (inheritance ? inheritance.refresh() : editor.refresh());
  const open = () => {
    if (!opened.has(node.id)) opened.set(node.id, new Set());
    return opened.get(node.id);
  };
  const save = (setting) => (value) => editor.saveSetting(node, setting, value);

  /** An unset optional setting just added: an empty control that shows the default, with a bin to take it away. */
  const addedRow = (setting) => {
    const control = createControl(setting, null, save(setting), suggest, { unsaved: true });
    if (setting.default !== null && setting.default !== undefined && setting.default !== "") control.input.placeholder = String(setting.default);
    return withBin(control.element, setting, t("editor.settings_layout.remove"), () => {
      open().delete(setting.key);
      redraw();
    });
  };

  /** An optional setting that has a value: its control and a bin that makes it not set again. */
  const shownRow = (setting) =>
    withBin(createControl(setting, settingValue(node, setting), save(setting), suggest).element, setting, t("editor.settings_layout.use_default_again"), async () => {
      const message = await editor.saveSetting(node, setting, null);
      if (!message) {
        open().delete(setting.key);
        redraw();
      }
    });

  const overrideOf = (setting) => {
    const state = inheritance.state(setting.key);
    const overridden = Boolean(state?.overridden);
    const inherited = state?.inherited;
    const has = inherited !== null && inherited !== undefined && inherited !== "";
    return overrideRow({
      key: setting.key,
      label: setting.label,
      source: inheritance.source,
      inheritedText: has ? inheritance.show(setting, inherited) : null,
      overridden,
      editing: !overridden && open().has(setting.key),
      wide: setting.type === "lines",
      makeControl: ({ unsaved }) =>
        createControl(
          inheritance.setting(setting),
          unsaved ? (has ? inherited : null) : state.value,
          async (value) => {
            const message = await editor.saveSetting(node, setting, value);
            if (!message) {
              open().delete(setting.key);
              window.setTimeout(redraw);
            }
            return message;
          },
          suggest,
          { unsaved },
        ),
      begin: () => {
        open().add(setting.key);
        redraw();
      },
      cancel: () => {
        open().delete(setting.key);
        redraw();
      },
      remove: async () => {
        const message = await editor.saveSetting(node, setting, null);
        if (!message) redraw();
        return message;
      },
    });
  };

  const rowOf = (setting, listed) => {
    if (setting.inherits && inheritance) return overrideOf(setting);
    if (setting.level === "optional") return listed === "added" ? addedRow(setting) : shownRow(setting);
    return createControl(setting, settingValue(node, setting), save(setting), suggest).element;
  };

  /** A group in Definition folds while unused; a group of Behaviour is a titled block. */
  const groupOf = (group, rows, section, settings) => {
    if (group === null) return rows;
    if (section === "behaviour") {
      const block = make("section", "ge-settings__group");
      block.dataset.group = group;
      block.append(make("h4", "ge-settings__group-title", group), ...rows);
      return [block];
    }
    const details = make("details", "ge-group");
    details.dataset.group = group;
    const first = settings[0];
    const used = type.groupUsed?.(node, group) ?? String(settingValue(node, first) ?? "").trim() !== "";
    details.append(Object.assign(make("summary"), { textContent: used ? group : t("editor.settings_layout.group_empty", { group }) }), ...rows);
    details.open = used || first.key.endsWith("_1");
    return [details];
  };

  const addMenu = (available, section) => {
    const button = make("button", "button button--ghost button--sm ge-settings__add");
    button.type = "button";
    button.dataset.focusKey = `add-${section}`;
    button.setAttribute("aria-haspopup", "menu");
    button.append(icon("plus"), document.createTextNode(available.every((s) => s.inherits) ? t("editor.settings_layout.add_override") : t("editor.settings_layout.add_setting")));
    button.addEventListener("click", () => {
      const items = available.map((setting) => {
        const state = inheritance?.state(setting.key);
        const text = state && state.inherited != null && state.inherited !== "" ? inheritance.show(setting, state.inherited) : null;
        return { label: optionLabel(setting, text), icon: "plus", onSelect: () => {
          open().add(setting.key);
          redraw();
        } };
      });
      menu.toggle(button, items, "Settings that are not set");
    });
    return button;
  };

  const column = (section) => {
    const el = make("div", "ge-settings__column");
    el.dataset.section = section.id;
    if (plan.columns === 2) el.append(make("h3", "ge-settings__title", TITLES[section.id]));
    if (section.id === "definition") el.append(...extras);
    const added = open();
    const visible = [...section.core, ...section.shown, ...section.available.filter((s) => added.has(s.key))].sort((a, b) => order.get(a.key) - order.get(b.key));
    for (const { group, settings } of groupsOf(visible)) {
      const rows = settings.map((s) => rowOf(s, section.available.includes(s) ? "added" : "shown"));
      el.append(...groupOf(group, rows, section.id, settings));
    }
    const available = section.available.filter((s) => !added.has(s.key));
    if (available.length) el.append(addMenu(available, section.id));
    if (section.advanced.settings.length) {
      const details = make("details", "ge-advanced");
      details.dataset.section = section.id;
      details.append(make("summary", "", t("editor.settings_layout.advanced")), ...section.advanced.settings.map((s) => rowOf(s, "shown")));
      details.open = section.advanced.open;
      el.append(details);
    }
    return el;
  };

  const wrap = make("div", "ge-settings-wrap");
  const root = make("div", "ge-settings");
  root.dataset.columns = String(plan.columns);
  const columns = plan.sections.map(column);
  if (extras.length && !columns.some((c) => c.dataset.section === "definition")) {
    const only = make("div", "ge-settings__column");
    only.dataset.section = "definition";
    only.append(...extras);
    columns.unshift(only);
    root.dataset.columns = String(columns.length);
  }
  root.append(...columns);
  const overridden = inheritance ? type.settings.filter((s) => s.inherits && inheritance.state(s.key)?.overridden).map((s) => s.key) : [];
  if (overridden.length) root.append(resetAll(overridden, node, editor, redraw, inheritance.source));
  wrap.append(root);
  return wrap;
}

function withBin(controlElement, setting, title, onClick) {
  const row = make("div", "ge-optional");
  row.dataset.setting = setting.key;
  const bin = make("button", "icon-button icon-button--sm is-danger ge-optional__remove");
  bin.type = "button";
  bin.title = title;
  bin.dataset.focusKey = `remove-${setting.key}`;
  bin.setAttribute("aria-label", `${title}: ${setting.label}`);
  bin.append(icon("trash"));
  bin.addEventListener("click", onClick);
  row.append(controlElement, bin);
  return row;
}

function resetAll(keys, node, editor, redraw, source) {
  const button = make("button", "button button--ghost button--sm ge-settings__reset", t("editor.settings_layout.reset_all_length_overrides", { length: keys.length }));
  button.type = "button";
  button.dataset.focusKey = "reset-all";
  button.title = t("editor.settings_layout.use_source_values", { source: source.toLowerCase() });
  button.addEventListener("click", async () => {
    const type = typeOf(node);
    for (const key of keys) await editor.saveSetting(node, type.settings.find((s) => s.key === key), null);
    opened.delete(node.id);
    redraw();
  });
  return button;
}
