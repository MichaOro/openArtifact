/* The translations in the browser (ADR-056): the same `t` and `plural` as the server's (openartifact/i18n), with the
 * dictionary of the page's language delivered inline (`<script type="application/json" id="i18n">`, a data block the
 * strict CSP allows). English is the source: a key without a translation was already filled with the English text on
 * the server; a key that is nowhere is shown as it is, never an error.
 *
 * t(KEY) ; t(KEY, { subject: "x" }) ; plural(KEY, 3) -> "3 executions" (KEY: a dotted key of en.json)
 * (plural looks for `key.<category>` by Intl.PluralRules, then `key.other`; `{count}` is filled in). */

let state = { lang: "en", languages: [{ code: "en", name: "English" }], messages: {} };

/** Install a dictionary: `{lang, languages?, messages}` (also what tests use). */
export function loadI18n(payload) {
  state = { lang: payload.lang ?? "en", languages: payload.languages ?? [{ code: payload.lang ?? "en", name: payload.lang ?? "en" }], messages: payload.messages ?? {} };
}

if (typeof document !== "undefined" && document.getElementById) {
  const block = document.getElementById("i18n");
  if (block) {
    try {
      loadI18n(JSON.parse(block.textContent));
    } catch {
      /* a broken dictionary leaves the keys as they are */
    }
  }
} else if (typeof process !== "undefined" && process.versions?.node) {
  // Under Node (the unit tests) there is no page: the English source file is the dictionary, so a test sees the same
  // texts as a visitor and a key that is not in it shows up as the key.
  const { readFileSync } = await import("node:fs");
  const url = new URL("../../i18n/locales/en.json", import.meta.url);
  loadI18n({ lang: "en", messages: JSON.parse(readFileSync(url, "utf8")) });
}

/** The page's language code. */
export const language = () => state.lang;

/** The languages that exist: [{code, name}]. */
export const languages = () => state.languages;

/** `{name}` replaced by the variable of that name; an unknown placeholder stays. */
function fill(text, variables) {
  return variables ? text.replace(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g, (whole, name) => (name in variables ? String(variables[name]) : whole)) : text;
}

/** The text of a key with the variables put in; the key itself when nothing has it. */
export function t(key, variables) {
  const found = state.messages[key];
  return fill(found ?? key, variables);
}

/** The text of `key.<category>` for the count (`{count}` is filled in), else `key.other`, else the key. */
export function plural(key, count, variables) {
  let category;
  try {
    category = new Intl.PluralRules(state.lang).select(count);
  } catch {
    category = count === 1 ? "one" : "other";
  }
  const found = state.messages[`${key}.${category}`] ?? state.messages[`${key}.other`];
  return fill(found ?? key, { count, ...variables });
}

/** The usual short name for `plural` in code that has a local noun-counting helper of its own. */
export const tn = plural;

/** Choose a language: remembered in a cookie the server reads, then the page is loaded again in it. */
export function chooseLanguage(code) {
  document.cookie = `oa_lang=${encodeURIComponent(code)}; Path=/; Max-Age=${365 * 24 * 3600}; SameSite=Lax`;
  window.location.reload();
}
