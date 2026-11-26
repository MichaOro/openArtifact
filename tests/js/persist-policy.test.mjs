/* When the node dialog saves (persist-policy.js): the pure rules, and the flush of unsaved text. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { flushDirty, isTextEditing, persistText, persistsOn, registerDirty } from "../../openartifact/static/js/editor/persist-policy.js";

const ev = (type, extra = {}) => ({ type, ...extra });

test("no kind of control saves on a keystroke or on a timer", () => {
  for (const kind of ["text", "multiline", "choice", "toggle"]) {
    for (const type of ["input", "keyup", "keypress", "timer", "interval"]) assert.equal(persistsOn(kind, ev(type, { key: "a" })), false, `${kind} on ${type}`);
  }
});

test("a one-line text saves when it is left and on Enter, not on Shift+Enter or another key", () => {
  assert.equal(persistsOn("text", ev("focusout")), true);
  assert.equal(persistsOn("text", ev("keydown", { key: "Enter" })), true);
  assert.equal(persistsOn("text", ev("keydown", { key: "Enter", shiftKey: true })), false);
  assert.equal(persistsOn("text", ev("keydown", { key: "a" })), false);
  assert.equal(persistsOn("text", ev("change")), false, "the change event of a text is the same as leaving it: only one of them decides");
});

test("a textarea saves when it is left and on Ctrl+Enter; Enter is a new line", () => {
  assert.equal(persistsOn("multiline", ev("focusout")), true);
  assert.equal(persistsOn("multiline", ev("keydown", { key: "Enter" })), false);
  assert.equal(persistsOn("multiline", ev("keydown", { key: "Enter", ctrlKey: true })), true);
  assert.equal(persistsOn("multiline", ev("keydown", { key: "Enter", metaKey: true })), true);
});

test("a choice saves once when it changes, a switch when it is clicked, neither when left", () => {
  assert.equal(persistsOn("choice", ev("change")), true);
  assert.equal(persistsOn("choice", ev("focusout")), false);
  assert.equal(persistsOn("toggle", ev("click")), true);
  assert.equal(persistsOn("toggle", ev("focusout")), false);
});

test("which elements hold the caret", () => {
  assert.equal(isTextEditing("TEXTAREA"), true);
  assert.equal(isTextEditing("INPUT", "text"), true);
  assert.equal(isTextEditing("INPUT", "number"), true);
  assert.equal(isTextEditing("INPUT", "checkbox"), false);
  assert.equal(isTextEditing("SELECT"), false);
  assert.equal(isTextEditing("BUTTON"), false);
});

test("closing the dialog saves every field with unsaved text and only those", async () => {
  const saved = [];
  const forget = [
    registerDirty({ isDirty: () => true, commit: async () => saved.push("a") }),
    registerDirty({ isDirty: () => false, commit: async () => saved.push("clean") }),
    registerDirty({ isDirty: () => true, commit: async () => saved.push("b") }),
  ];
  await flushDirty();
  assert.deepEqual(saved, ["a", "b"]);
  forget.forEach((f) => f());
  await flushDirty();
  assert.deepEqual(saved, ["a", "b"], "forgotten fields are not saved again");
});

test("leaving a text while its save from Enter is still on its way does not send it a second time", async () => {
  const listeners = {};
  const input = { value: "", dataset: {}, closest: () => null, addEventListener: (name, fn) => (listeners[name] = fn) };
  const sent = [];
  let finish = () => {};
  persistText(input, (text) => new Promise((resolve) => { sent.push(text); finish = () => resolve(null); }));
  input.value = "t = ${card.title}";
  listeners.keydown({ type: "keydown", key: "Enter" });
  listeners.focusout({ type: "focusout" }); // the draw after the save takes the focus away before the save is back
  assert.deepEqual(sent, ["t = ${card.title}"], "one request for one text");
  finish();
  await new Promise((resolve) => setTimeout(resolve));
  listeners.focusout({ type: "focusout" });
  assert.equal(sent.length, 1, "saved: nothing to send when it is left");
  input.value = "other";
  listeners.focusout({ type: "focusout" });
  assert.equal(sent.length, 2, "a changed text is still saved on leaving");
});
