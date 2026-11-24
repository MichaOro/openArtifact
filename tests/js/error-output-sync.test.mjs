/* The messages of the error output sync (static/js/editor/error-output-sync.js): what the server's notices say, and
 * when an answer asks the editor to load the graph again. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { needsReload, noticeMessages, noticeText, placeText } from "../../openartifact/static/js/editor/error-output-sync.js";

test("a place is named from the graph down to the node, without what is missing", () => {
  assert.equal(placeText({ graph: "Flow", stage: "Stage 1", node: "Action" }), "Flow › Stage 1 › Action");
  assert.equal(placeText({ graph: "Work", stage: null, node: "Output" }), "Work › Output");
});

test("the definition that got On Fail says how many other uses it applies to, in the singular and the plural", () => {
  assert.deepEqual(noticeMessages([{ kind: "definition_on", definition: "Work", uses: 1 }]), ["Also switched on in the action 'Work'; it applies to 1 other use."]);
  assert.deepEqual(noticeMessages([{ kind: "definition_on", definition: "Work", uses: 3 }]), ["Also switched on in the action 'Work'; it applies to 3 other uses."]);
});

test("a definition that stays on names the uses that still need it", () => {
  assert.equal(noticeText([{ kind: "definition_stays_on", definition: "Work", uses: 2 }]), "Stays on in the action 'Work': 2 other uses still have the error output.");
});

test("disconnected connections are counted and placed", () => {
  const notice = { kind: "disconnected", count: 3, inner: 1, places: [{ graph: "Flow", stage: "Stage 1", node: "A", count: 2 }, { graph: "Work", stage: null, node: "Output", count: 1 }] };
  assert.equal(noticeText([notice]), "Disconnected 3 connections (Flow › Stage 1 › A; Work › Output).");
  assert.equal(noticeText([{ kind: "disconnected", count: 1, inner: 0, places: [{ graph: "Flow", stage: null, node: "Code", count: 1 }] }]), "Disconnected 1 connection (Flow › Code).");
});

test("no notice, no message; an unknown kind says nothing", () => {
  assert.equal(noticeText([]), "");
  assert.equal(noticeText(undefined), "");
  assert.deepEqual(noticeMessages([{ kind: "something_new" }]), []);
});

test("an answer asks for a reload when other nodes changed or connections went, not otherwise", () => {
  assert.equal(needsReload({ reload: true, notices: [] }), true);
  assert.equal(needsReload({ reload: false, notices: [{ kind: "disconnected", count: 1, places: [] }] }), true);
  assert.equal(needsReload({ reload: false, notices: [{ kind: "definition_on", definition: "W", uses: 1 }] }), false);
  assert.equal(needsReload({ reload: false, notices: [] }), false);
  assert.equal(needsReload(undefined), false);
});
