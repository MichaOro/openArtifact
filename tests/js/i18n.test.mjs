/* The translations in the browser (static/js/i18n.js): t, plural, fallback to the key, the dictionary a page delivers. */
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";

import { language, languages, loadI18n, plural, t, tn } from "../../openartifact/static/js/i18n.js";

const english = JSON.parse(readFileSync(new URL("../../openartifact/i18n/locales/en.json", import.meta.url), "utf8"));

test("under Node the dictionary is the English source file, so unit tests see what a visitor sees", () => {
  assert.equal(language(), "en");
  assert.equal(t("common.save"), "Save");
  assert.equal(t("tasks.comments_tab.comment_deleted"), "Comment deleted");
});

test("t puts variables in, leaves unknown placeholders and unknown keys as they are", () => {
  loadI18n({ lang: "en", messages: { "a.hello": "Hello {name}, {name}!", "a.two": "{a} and {b}" } });
  assert.equal(t("a.hello", { name: "Ann" }), "Hello Ann, Ann!");
  assert.equal(t("a.two", { a: 1 }), "1 and {b}");
  assert.equal(t("a.hello"), "Hello {name}, {name}!");
  assert.equal(t("not.there"), "not.there"); // never an error
  assert.equal(t("a.hello", { name: 0 }), "Hello 0, 0!"); // 0 is a value
});

test("plural picks the form by the language's rule and fills {count}", () => {
  loadI18n({ lang: "en", messages: { "n.files.one": "{count} file", "n.files.other": "{count} files", "n.only.other": "{count} things" } });
  assert.equal(plural("n.files", 1), "1 file");
  assert.equal(plural("n.files", 0), "0 files");
  assert.equal(plural("n.files", 5), "5 files");
  assert.equal(tn("n.only", 1), "1 things"); // no `one` form: `other` serves
  assert.equal(plural("n.none", 2), "n.none");
  loadI18n({ lang: "ru", messages: { "n.f.one": "{count} файл", "n.f.few": "{count} файла", "n.f.many": "{count} файлов", "n.f.other": "{count} файла" } });
  assert.equal(plural("n.f", 2), "2 файла"); // a language with more forms uses them
  assert.equal(plural("n.f", 5), "5 файлов");
});

test("a page's dictionary replaces the English one and lists the languages", () => {
  loadI18n({ lang: "de", languages: [{ code: "en", name: "English" }, { code: "de", name: "Deutsch" }], messages: { "common.save": "Speichern" } });
  assert.equal(language(), "de");
  assert.equal(t("common.save"), "Speichern");
  assert.equal(t("common.cancel"), "common.cancel"); // the server fills missing keys with English: here nothing is left to fall back to
  assert.deepEqual(languages().map((l) => l.code), ["en", "de"]);
  loadI18n({ lang: "en", messages: english });
});

test("every key the page scripts call exists in the English file (no script shows a bare key)", () => {
  const root = new URL("../../openartifact/static/js/", import.meta.url);
  const files = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) walk(new URL(`${entry.name}/`, dir));
      else if (entry.name.endsWith(".js")) files.push(new URL(entry.name, dir));
    }
  };
  walk(root);
  const missing = [];
  for (const file of files) {
    for (const [, key] of readFileSync(file, "utf8").matchAll(/\b(?:t|tn|plural)\(\s*"((?:[a-z0-9_]+\.)+[a-z0-9_]+)"/g)) {
      const known = key in english || `${key}.other` in english || `${key}.one` in english;
      if (!known) missing.push(`${file.pathname.split("/js/")[1]}: ${key}`);
    }
  }
  assert.deepEqual(missing, []);
});
