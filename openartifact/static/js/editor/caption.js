/* The line under a card's name, from a template a node kind's manifest declares (ADR-054), so no kind needs code of its own
 * for it. A template is text with these parts:
 *
 *   {key}              a setting of the node (its config), or {@field} a field of the node (seconds, name, ...)
 *   {key|filter|f:arg} the value passed through filters, left to right
 *   {?cond:text}       `text` only when the condition holds; clauses joined by &: `key` (set), `!key` (not set),
 *                      `key=value` (equals)
 *
 * Filters: default:text (the text, or @field, when the value is empty), trim, first_line (the first line that says
 * something), short (at most 40 characters), host_path (an address as `host/path`, never its query or credentials),
 * field_names (the names an Edit Fields text sets, joined by ", "). The list is `CAPTION_FILTERS` in graph/manifest.py. */
import { fieldNames } from "./reference-completion.js";

/** Longest text a card shows of a setting. */
const SHORT = 40;
export const short = (text) => (text.length > SHORT ? `${text.slice(0, SHORT)}…` : text);

/** `https://user:pw@example.org/hook?token=x#y` as `example.org/hook`. */
export function hostAndPath(url) {
  const plain = () => url.split(/[?#]/)[0].replace(/^[^/]*@/, "");
  try {
    const { host, pathname } = new URL(url);
    // `user:pw@host/path` without a scheme parses as an opaque URL with no host: never show the userinfo
    // the path as written: a tool's {parameter} stays readable
    return host ? `${host}${pathname === "/" ? "" : decodeURI(pathname)}` : plain();
  } catch {
    return plain();
  }
}

const FILTERS = {
  trim: (value) => value.trim(),
  first_line: (value) => value.split("\n").find((line) => line.trim() !== "")?.trim() ?? "",
  short,
  host_path: (value) => hostAndPath(value),
  field_names: (value) => fieldNames(value).join(", "),
};

function read(node, key) {
  const raw = key.startsWith("@") ? node[key.slice(1)] : node.config?.[key];
  return raw === null || raw === undefined ? "" : String(raw);
}

const truthy = (node, key) => {
  const value = key.startsWith("@") ? node[key.slice(1)] : node.config?.[key];
  return Boolean(value) && value !== "false";
};

function holds(node, condition) {
  return condition.split("&").every((clause) => {
    const text = clause.trim();
    if (text.startsWith("!")) return !truthy(node, text.slice(1));
    const at = text.indexOf("=");
    return at < 0 ? truthy(node, text) : read(node, text.slice(0, at)) === text.slice(at + 1);
  });
}

function value(node, body) {
  const [key, ...filters] = body.split("|");
  let result = read(node, key.trim());
  for (const filter of filters) {
    const at = filter.indexOf(":");
    const name = (at < 0 ? filter : filter.slice(0, at)).trim();
    const argument = at < 0 ? "" : filter.slice(at + 1);
    if (name === "default") {
      if (result === "") result = argument.startsWith("@") ? read(node, argument) : argument;
    } else if (FILTERS[name]) {
      result = FILTERS[name](result);
    }
  }
  return result;
}

/** The template for a node. */
export function renderCaption(template, node) {
  return template.replace(/\{(\?)?([^{}]*)\}/g, (_, conditional, body) => {
    if (!conditional) return value(node, body);
    const at = body.indexOf(":");
    return holds(node, body.slice(0, at)) ? body.slice(at + 1) : "";
  });
}
