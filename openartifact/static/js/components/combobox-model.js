/* The pure part of the combobox (components/combobox.js): which options a typed text leaves and in which order, and
 * where the keyboard moves the highlighted option. No DOM: tests/js/combobox-model.test.mjs. */

/**
 * The options a query leaves, best first: the label starts with it, a word of the label starts with it, the label
 * contains it, only the description or the keywords (more text to search that is not shown) contain it (any case). An
 * empty query leaves all options by label. Options that do not contain the query anywhere are dropped.
 * @param {{value: string, label: string, description?: string, keywords?: string}[]} options
 * @param {string} query
 */
export function filterOptions(options, query) {
  const wanted = query.trim().toLowerCase();
  const byLabel = (a, b) => a.option.label.localeCompare(b.option.label);
  const scored = options.map((option) => ({ option, rank: rank(option, wanted) })).filter((entry) => entry.rank !== null);
  return scored.sort((a, b) => a.rank - b.rank || byLabel(a, b)).map((entry) => entry.option);
}

function rank(option, wanted) {
  if (!wanted) return 0;
  const label = option.label.toLowerCase();
  if (label.startsWith(wanted)) return 0;
  if (label.split(/[^\p{L}\p{N}]+/u).some((word) => word.startsWith(wanted))) return 1;
  if (label.includes(wanted)) return 2;
  if (`${option.description ?? ""} ${option.keywords ?? ""}`.toLowerCase().includes(wanted)) return 3;
  return null;
}

/**
 * Where an arrow key or Home/End moves the highlight (-1 = none yet). Down from none lands on the first option, Up from
 * none on the last; the ends wrap.
 * @param {number} current the highlighted index or -1
 * @param {string} key ArrowDown | ArrowUp | Home | End
 * @param {number} count how many options there are
 */
export function moveHighlight(current, key, count) {
  if (!count) return -1;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  if (key === "ArrowDown") return current < 0 ? 0 : (current + 1) % count;
  if (key === "ArrowUp") return current < 0 ? count - 1 : (current - 1 + count) % count;
  return current;
}
