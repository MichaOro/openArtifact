import assert from "node:assert/strict";
import { before, test } from "node:test";
import { FakeNode, installDocument, loadTypes, textOf } from "./support.mjs";

const JS = "../../openartifact/static/js/editor/";
const { HEADER, SLOTS, slotY, NodeView, registerView, loadNodeTypes, typeOf, addableIn } = await import(`${JS}node-types.js`);

before(async () => {
  installDocument(["code", "http"]);
  await loadTypes(loadNodeTypes);
});

const node = (kind, fields = {}) => ({ id: `${kind}-1`, kind, name: kind, x: 0, y: 0, config: {}, ...fields });

test("slot heights: header middle, body middle, bottom", () => {
  assert.equal(SLOTS, 3);
  assert.deepEqual([0, 1, 2].map((s) => slotY(200, s)), [HEADER / 2, 100, 200 - HEADER / 2]);
});

test("typeOf takes a node or a kind name; an unknown kind is undefined", () => {
  assert.equal(typeOf("stage").label, "Stage");
  assert.equal(typeOf(node("stage")).label, "Stage");
  assert.equal(typeOf("nothing"), undefined);
});

test("a kind without a view class gets the base view", () => {
  assert.equal(Object.getPrototypeOf(typeOf("note")), NodeView.prototype);
});

test("registerView replaces the view of a kind for kinds loaded afterwards", async () => {
  class Custom extends NodeView {
    static kind = "note";
  }
  registerView(Custom);
  await loadTypes(loadNodeTypes);
  assert.ok(typeOf("note") instanceof Custom);
  registerView(class extends NodeView { static kind = "note"; });
});

test("addableIn lists the addable kinds of one scope, in server order", () => {
  assert.deepEqual(addableIn("pipeline").map((t) => t.kind), ["stage", "pipeline", "timer"]);
  assert.deepEqual(addableIn("action").map((t) => t.kind), ["code", "http", "if", "switch", "set", "note"]);
  assert.deepEqual(addableIn("elsewhere"), []);
});

test("names and captions: a linked node shows the name of its definition", () => {
  const action = typeOf("action");
  assert.equal(action.displayName(node("action", { name: "Action", definition_name: "Deploy" })), "Deploy");
  assert.equal(action.displayName(node("action")), "action");
  assert.equal(action.caption(node("action", { definition_id: "d" })), "Action");
  assert.equal(action.caption(node("action")), "Empty action");
  assert.equal(action.subtitle(node("action")), "Empty action");
  const pipeline = typeOf("pipeline");
  assert.equal(pipeline.caption(node("pipeline", { definition_id: "p" })), "Pipeline");
  assert.equal(pipeline.caption(node("pipeline")), "No pipeline chosen");
  const trigger = typeOf("trigger");
  assert.equal(trigger.caption(node("trigger", { name: "Trigger" })), null, "a caption that repeats the name is dropped");
  assert.equal(trigger.subtitle(node("trigger", { name: "Trigger" })), "Trigger");
  assert.equal(trigger.caption(node("trigger", { name: "Manual start" })), "Trigger");
  assert.equal(typeOf("stage").caption(), "Stage");
  assert.equal(typeOf("timer").caption(node("timer", { seconds: 30 })), "30 s");
});

test("sizes", () => {
  assert.deepEqual(typeOf("trigger").size(), { width: 160, height: 64 });
  assert.deepEqual(typeOf("complete").size(), { width: 160, height: 56 });
  assert.deepEqual(typeOf("stage").size({ width: 400, height: 300 }), { width: 400, height: 300 });
  assert.deepEqual(typeOf("action").size(), { width: 190, height: 68 });
  assert.deepEqual(typeOf("pipeline").size(), { width: 200, height: 64 });
  assert.deepEqual(typeOf("output").size(), { width: 250, height: 104 });
  assert.deepEqual(typeOf("code").size(), { width: 250, height: 84 });
});

test("the code caption is the language and the first non-empty line", () => {
  const code = typeOf("code");
  assert.equal(code.caption(node("code", { config: { language: "python", code: "\n  \n  print(1)\nx" } })), "python · print(1)");
  assert.equal(code.caption(node("code", { config: { language: "python", code: "  " } })), "python · no code yet");
  assert.equal(code.caption(node("code", { config: undefined })), "sh · no code yet");
  assert.equal(code.subtitle(), "Code");
});

test("the http caption never shows the query string, the fragment or credentials", () => {
  const http = typeOf("http");
  const caption = (config) => http.caption(node("http", { config }));
  assert.equal(caption({ method: "POST", url: "https://user:pw@example.org/hook?token=x#y" }), "POST example.org/hook");
  assert.equal(caption({ url: "https://example.org/" }), "GET example.org");
  assert.equal(caption({ url: "user:pw@example.org/hook?token=x" }), "GET example.org/hook", "userinfo without a scheme is not shown either");
  assert.equal(caption({ url: "" }), "GET no URL yet");
  assert.equal(caption(undefined), "GET no URL yet");
  assert.equal(caption({ method: "PUT", url: "user@host/path?secret=1#frag" }), "PUT host/path", "an unparsable URL is cut as well");
  assert.equal(caption({ url: "not a url?token=abc" }), "GET not a url");
});

test("ports: inputs on the left, outputs on the right, a stage has three points per side", () => {
  assert.deepEqual(typeOf("action").ports().map((p) => [p.name, p.direction, p.side, p.slot]), [
    ["in", "input", "left", 0], ["out", "output", "right", 0], ["pass", "output", "right", 0], ["error", "output", "right", 0],
  ]);
  const stage = typeOf("stage").ports();
  assert.equal(stage.length, 6);
  assert.deepEqual(stage.filter((p) => p.name === "start").map((p) => [p.direction, p.side, p.slot]), [["both", "left", 0], ["both", "left", 1], ["both", "left", 2]]);
  assert.deepEqual(stage.filter((p) => p.name === "end").map((p) => p.side), ["right", "right", "right"]);
});

test("visibility: an action without On Fail has no error port, an output without fail has no Fail port", () => {
  const action = typeOf("action");
  assert.equal(action.isVisible(node("action", { definition_fail_enabled: false }), "error"), false);
  assert.equal(action.isVisible(node("action", { definition_fail_enabled: true }), "error"), true);
  assert.equal(action.isVisible(node("action"), "error"), true, "unknown (no definition): shown");
  assert.equal(action.isVisible(node("action", { definition_fail_enabled: false }), "pass"), true);
  const output = typeOf("output");
  assert.equal(output.isVisible(node("output", { fail_enabled: false }), "fail"), false);
  assert.equal(output.isVisible(node("output", { fail_enabled: true }), "fail"), true);
  assert.equal(output.isVisible(node("output", { fail_enabled: false }), "pass"), true);
  assert.equal(typeOf("trigger").isVisible(node("trigger"), "out"), true);
});

test("port labels: only the outcomes of kinds that label ports, not in and out", () => {
  assert.equal(typeOf("action").labelled({ name: "pass" }), true);
  assert.equal(typeOf("action").labelled({ name: "in" }), false);
  assert.equal(typeOf("action").labelled({ name: "out" }), false);
  assert.equal(typeOf("trigger").labelled({ name: "pass" }), false);
  assert.equal(typeOf("output").portLabel("fail"), "On Fail");
  assert.equal(typeOf("output").portLabel("unknown"), "unknown");
});

test("portLocal spreads the shown ports down their side; the output kind pins its connectors", () => {
  const action = typeOf("action");
  const withFail = node("action", { definition_fail_enabled: true });
  assert.deepEqual(action.portLocal(withFail, "in"), { x: 0, y: 34 });
  assert.deepEqual(action.portLocal(withFail, "out"), { x: 190, y: 17 });
  assert.deepEqual(action.portLocal(withFail, "error"), { x: 190, y: 51 });
  const withoutFail = node("action", { definition_fail_enabled: false });
  assert.deepEqual(action.portLocal(withoutFail, "pass"), { x: 190, y: 68 / 3 * 2 });
  assert.deepEqual(action.portLocal(withoutFail, "nonsense"), { x: 190, y: 68 / 3 }, "an unknown port falls back to the first");
  const output = typeOf("output");
  assert.deepEqual(output.portLocal(node("output"), "pass"), { x: 0, y: 60 });
  assert.deepEqual(output.portLocal(node("output"), "fail"), { x: 0, y: 84 });
  const stage = node("stage", { width: 400, height: 300 });
  assert.deepEqual(typeOf("stage").portLocal(stage, "start", 2), { x: 0, y: 300 - HEADER / 2 });
  assert.deepEqual(typeOf("stage").portLocal(stage, "end"), { x: 400, y: HEADER / 2 });
});

test("connection rules of each kind", () => {
  const trigger = node("trigger");
  const stage = node("stage", { id: "s" });
  const inside = node("action", { id: "a", stage_id: "s" });
  const sibling = node("action", { id: "b", stage_id: "s" });
  const stranger = node("action", { id: "c", stage_id: "other" });
  const other = node("stage", { id: "s2" });
  // base: never itself, never an action, a stage only at "start"
  assert.equal(typeOf("trigger").canFeed(trigger, "out", trigger, "in"), false);
  assert.equal(typeOf("trigger").canFeed(trigger, "out", inside, "in"), false);
  assert.equal(typeOf("trigger").canFeed(trigger, "out", stage, "start"), true);
  assert.equal(typeOf("trigger").canFeed(trigger, "out", stage, "end"), false);
  assert.equal(typeOf("trigger").canFeed(trigger, "out", node("timer"), "in"), true);
  // a stage: "start" feeds its own actions only, "end" follows the base rules
  assert.equal(typeOf("stage").canFeed(stage, "start", inside, "in"), true);
  assert.equal(typeOf("stage").canFeed(stage, "start", stranger, "in"), false);
  assert.equal(typeOf("stage").canFeed(stage, "start", other, "start"), false);
  assert.equal(typeOf("stage").canFeed(stage, "end", other, "start"), true);
  assert.equal(typeOf("stage").canFeed(stage, "end", inside, "in"), false);
  // an action: another action of its stage, or the end of its own stage
  assert.equal(typeOf("action").canFeed(inside, "out", sibling, "in"), true);
  assert.equal(typeOf("action").canFeed(inside, "out", stranger, "in"), false);
  assert.equal(typeOf("action").canFeed(inside, "out", stage, "end"), true);
  assert.equal(typeOf("action").canFeed(inside, "out", stage, "start"), false);
  assert.equal(typeOf("action").canFeed(inside, "out", other, "end"), false);
  assert.equal(typeOf("action").canFeed(inside, "out", trigger, "in"), false);
});

test("renaming in place is allowed except for linked kinds", () => {
  assert.deepEqual(["trigger", "stage", "timer", "action", "pipeline"].map((k) => typeOf(k).renamable()), [true, true, true, false, false]);
});

test("the inspector sections each kind asks for", () => {
  const calls = [];
  const blocks = {
    settings: (n) => `settings:${n.kind}`,
    actions: (n, options) => `actions:${n.kind}:${JSON.stringify(options, (k, v) => (typeof v === "function" ? "fn" : v))}`,
    addAction: (stage) => calls.push(["addAction", stage.id]),
    link: (n, ...labels) => `link:${n.kind}:${labels.join("/")}`,
    linkActions: () => ({ open: true }),
  };
  const sections = (kind) => typeOf(kind).sections(node(kind), blocks);
  assert.deepEqual(sections("trigger"), ["settings:trigger", 'actions:trigger:{"remove":false}']);
  assert.deepEqual(sections("timer"), ["settings:timer", 'actions:timer:{"remove":true}']);
  assert.deepEqual(sections("stage"), ['actions:stage:{"create":"fn","remove":true}']);
  assert.deepEqual(sections("action"), ["link:action:Definition/Action/Not defined", 'actions:action:{"open":true}']);
  assert.deepEqual(sections("pipeline"), ["link:pipeline:Calls/Pipeline/Not chosen", 'actions:pipeline:{"open":true}']);
  const stage = node("stage");
  typeOf("stage").sections(stage, { actions: (n, options) => options.create(), addAction: (s) => calls.push(s.id) });
  assert.deepEqual(calls, [stage.id]);
});

test("render: a plain card gets its text, an icon kind gets its icon first", () => {
  const parts = { name: "NAME", caption: "CAPTION" };
  const plain = new FakeNode("div");
  typeOf("trigger").render(plain, node("trigger"), parts);
  assert.equal(plain.children.length, 1);
  assert.equal(plain.children[0].className, "ge-node__text");
  assert.deepEqual(plain.children[0].children, ["NAME", "CAPTION"]);
  const code = new FakeNode("div");
  typeOf("code").render(code, node("code"), parts);
  assert.equal(code.children.length, 2);
  assert.equal(code.children[0].iconName, "code");
  assert.ok(code.children[0].classes.has("ge-node__icon"));
});

test("render: a stage has a header with caption, name and the add button, and an empty body", () => {
  const el = new FakeNode("div");
  typeOf("stage").render(el, node("stage"), { name: "NAME", caption: "CAPTION" });
  const [header, body] = el.children;
  assert.equal(header.className, "ge-stage__header");
  assert.equal(body.className, "ge-stage__body");
  const [caption, name, add] = header.children;
  assert.deepEqual([caption, name], ["CAPTION", "NAME"]);
  assert.equal(add.type, "button");
  assert.equal(add.textContent, "+ Action");
  assert.equal(textOf(add), "+ Action");
  assert.equal(add.dataset.addAction, "");
});
