/* What the dialog of a node shows, decided without a DOM (ADR-053): the server describes every setting with a section
 * (definition / behaviour), a level (core / optional / advanced) and perhaps a parent it inherits from; this turns the
 * list and the node's stored values into the plan the layout draws.
 *
 *  - core: always shown. optional: shown once the node stores a value for it, else offered ("Add setting").
 *  - advanced: folded, and open while one of them has a value, so a configured value is never hidden.
 *  - a section without anything is not part of the plan; two columns only when both sections have something. */

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

/**
 * @param {object[]} settings the kind's settings as the server describes them
 * @param {object} node the node (its config holds the values)
 * @param {{skip?: string[]}} [options] `skip`: keys a kind draws itself
 * @returns {{columns: 1|2, sections: {id: string, core: object[], shown: object[], available: object[], advanced: {settings: object[], open: boolean}}[]}}
 */
export function planSettings(settings, node, { skip = [] } = {}) {
  const left = settings.filter((s) => !skip.includes(s.key));
  const sections = SECTIONS.map((id) => {
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
  }).filter((s) => s.core.length || s.shown.length || s.available.length || s.advanced.settings.length);
  return { columns: sections.length === 2 ? 2 : 1, sections };
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
  return hasDefault ? `${setting.label} · default ${setting.default}` : setting.label;
}

const capital = (text) => text.charAt(0).toUpperCase() + text.slice(1);
