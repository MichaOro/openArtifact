/* The legend under text that marks resolved references (components/resolved-legend.js). */
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { installDocument, textOf, uninstallDocument } from "./support.mjs";

const { ResolvedLegend } = await import("../../openartifact/static/js/components/resolved-legend.js");

beforeEach(() => installDocument());
afterEach(() => uninstallDocument());

test("the legend is a closed disclosure with the colour swatch and the words, hidden until it is shown", () => {
  const legend = new ResolvedLegend();
  const { element } = legend;
  assert.equal(element.tagName, "details");
  assert.equal(element.className, "resolved-legend");
  assert.equal(element.hidden, true);
  const [summary, line] = element.children;
  assert.equal(summary.tagName, "summary");
  const [swatch, words] = line.children;
  assert.equal(swatch.className, "resolved-legend__mark", "the colour comes from the token through the class, not from a character");
  assert.equal(swatch.attributes["aria-hidden"], "true");
  assert.ok(!/[\u2580-\u259f]/.test(textOf(element)), "no block glyph in the text");
  assert.ok(typeof words === "string" && words.length > 0);
});

test("show switches the legend on and off", () => {
  const legend = new ResolvedLegend();
  legend.show(true);
  assert.equal(legend.element.hidden, false);
  legend.show(false);
  assert.equal(legend.element.hidden, true);
});
