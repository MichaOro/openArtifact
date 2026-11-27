import assert from "node:assert/strict";
import test from "node:test";
import { MIN_LENGTH, blockText, shouldOffer } from "../../openartifact/static/js/components/copy-model.js";

test("a text gets a copy button when it is long or has several lines; a short single line and an empty text do not", () => {
  assert.equal(shouldOffer(""), false);
  assert.equal(shouldOffer("   \n  "), false, "only white space is nothing to copy");
  assert.equal(shouldOffer(undefined), false);
  assert.equal(shouldOffer("a name"), false);
  assert.equal(shouldOffer("x".repeat(MIN_LENGTH - 1)), false);
  assert.equal(shouldOffer("x".repeat(MIN_LENGTH)), true);
  assert.equal(shouldOffer("one\ntwo"), true, "two lines are quicker to copy than to select");
  assert.equal(shouldOffer("short\n"), false, "the newline at the end of an output is not a second line");
});

test("a field that is never short (a prompt) gets the button as soon as it holds something", () => {
  assert.equal(shouldOffer("Hi", { always: true }), true);
  assert.equal(shouldOffer("", { always: true }), false);
  assert.equal(shouldOffer("x".repeat(30), { minLength: 20 }), true, "the length is a setting");
});

test("the text of a block is the current value of a field, else the whole text content (never what is merely visible)", () => {
  assert.equal(blockText({ value: "typed", textContent: "ignored" }), "typed");
  assert.equal(blockText({ textContent: "all of the text" }), "all of the text");
  assert.equal(blockText({ value: "", textContent: "x" }), "", "an emptied field is empty");
  assert.equal(blockText(null), "");
});
