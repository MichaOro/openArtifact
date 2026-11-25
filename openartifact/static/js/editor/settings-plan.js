/* What the dialog of a node shows, decided without a DOM (ADR-053): the server describes every setting with a section
 * (definition / behaviour), a level (core / optional / advanced) and perhaps a parent it inherits from; this turns the
 * list and the node's stored values into the plan the layout draws.
 *
 *  - core: always shown. optional: shown once the node stores a value for it, else offered ("Add setting").
 *  - advanced: folded, and open while one of them has a value, so a configured value is never hidden.
 *  - a section without anything is not part of the plan (so an empty area of the user's own is not drawn); two columns when
 *    there are two or more sections. */

import { t } from "../i18n.js";
const SECTIONS = ["definition", "behaviour"];

/**
 * Whether the node has a value of its own for the setting, one worth showing. A setting with a parent is set when the
 * node stores a value. Any other setting is set when the stored value is not what applies anyway: a new node stores the
 * defaults of its config settings, and a default is no configuration, so it does not keep an optional setting open.
 */
export function isSet(node, setting) {
  const stored = setting.stored_in === "config" ? node.config?.[setting.key] : node[setting.key];
  if (stored === null || stored === undefined) return false;
  if (setting.inherits) return true;
  if (setting.stored_in !== "config") return true; // a column setting (the seconds of a timer) always has its value
  return stored !== "" && stored !== (setting.default ?? null);
}

/** What the node has for a setting, or the setting's default. */
function valueOf(node, setting) {
  const stored = setting.stored_in === "config" ? node.config?.[setting.key] : node[setting.key];
  return stored ?? setting.default ?? null;
}

/**
 * The value of a select that other selects take their options from (a resource): what is stored, unless the node's
 * dependent select (the operation) holds a value that belongs to another one, which then says what the node works on.
 */
export function controllerValue(settings, node, setting) {
  const current = valueOf(node, setting);
  for (const dependent of settings.filter((s) => s.options_by?.setting === setting.key)) {
    const held = valueOf(node, dependent);
    const map = dependent.options_by.map;
    if (held && !(map[current] ?? []).includes(held)) {
      const owner = Object.keys(map).find((value) => map[value].includes(held));
      if (owner) return owner;
    }
  }
  return current;
}

/** Whether a setting is drawn for the node: it has no `shown_when`, or the other setting has one of the values. */
export function isShown(settings, node, setting) {
  const when = setting.shown_when;
  if (!when) return true;
  const other = settings.find((s) => s.key === when.setting);
  return other ? when.values.includes(valueOf(node, other)) : true;
}

/** The setting as a control draws it: a select whose options depend on another select shows the options of its value. */
export function shaped(settings, node, setting) {
  const by = setting.options_by;
  if (!by) return setting;
  const other = settings.find((s) => s.key === by.setting);
  const options = (other && by.map[controllerValue(settings, node, other)]) || setting.options;
  return { ...setting, options };
}

/**
 * @param {object[]} settings the kind's settings as the server describes them
 * @param {object} node the node (its config holds the values)
 * @param {{skip?: string[], sections?: string[]}} [options] `skip`: keys a kind draws itself; `sections`: the areas, in order
 *   (the saved layout of the kind names Definition, Behaviour and the user's own; a setting's `section` is the area it sits in)
 * @returns {{columns: 1|2, sections: {id: string, core: object[], shown: object[], available: object[], advanced: {settings: object[], open: boolean}}[]}}
 */
export function planSettings(settings, node, { skip = [], sections: order = SECTIONS, added = new Set() } = {}) {
  const left = settings.filter((s) => !skip.includes(s.key) && isShown(settings, node, s));
  // the areas in order: the saved layout of the kind (ADR-063) may swap them and add areas of the user's own; a shipped area it
  // does not name comes after them
  const ids = [...order, ...SECTIONS.filter((id) => !order.includes(id))];
  const all = ids.map((id) => {
    const own = left.filter((s) => (s.section ?? "definition") === id);
    const optional = own.filter((s) => s.level === "optional");
    const advanced = own.filter((s) => s.level === "advanced");
    return {
      id,
      core: own.filter((s) => !s.level || s.level === "core"),
      shown: optional.filter((s) => isSet(node, s)),
      available: optional.filter((s) => !isSet(node, s)),
      advanced: { settings: advanced, open: advanced.some((s) => isSet(node, s)) },
    };
  });
  // an area that only offers settings nobody has set or added is not drawn (no empty column); what it offers is still offered
  // through the one "Add setting" of the dialog (`hidden`), and the area appears once one of them is added
  const drawn = (s) => s.core.length || s.shown.length || s.advanced.settings.length || s.available.some((a) => added.has(a.key));
  let sections = all.filter(drawn);
  if (!sections.length) sections = all.filter((s) => s.available.length).slice(0, 1);
  const hidden = all.filter((s) => !sections.includes(s)).flatMap((s) => s.available);
  return { columns: sections.length >= 2 ? 2 : 1, sections, hidden };
}

/** Settings of one group together, in the order declared; settings without a group are their own entries. */
export function groupsOf(settings) {
  const groups = [];
  for (const setting of settings) {
    const group = setting.group ?? null;
    const last = groups.at(-1);
    if (group !== null && last?.group === group) last.settings.push(setting);
    else groups.push({ group, settings: [setting] });
  }
  return groups;
}

/** How the "Add setting" menu names a setting: with its default, or with the value its parent supplies. */
export function optionLabel(setting, inheritedText = null) {
  if (setting.inherits) return inheritedText != null ? `${setting.label} · ${capital(setting.inherits)}: ${inheritedText}` : setting.label;
  const hasDefault = setting.default !== null && setting.default !== undefined && setting.default !== "";
  return hasDefault ? t("editor.settings_plan.label_default_default", { label: setting.label, default: setting.default }) : setting.label;
}

const capital = (text) => text.charAt(0).toUpperCase() + text.slice(1);
