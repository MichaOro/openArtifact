import assert from "node:assert/strict";
import { before, test } from "node:test";
import { FakeNode, NODE_TYPES, PLACEHOLDERS, installDocument, loadTypes, textOf } from "./support.mjs";

const JS = "../../openartifact/static/js/editor/";
const { HEADER, FIRST_ROW, STAGE_MARGIN, SLOTS, slotY, slotHeights, NodeView, registerView, loadNodeTypes, typeOf, addableIn, groupAddable, searchAddable, setPlaceholders, placeholderOf, placeholdersIn } = await import(`${JS}node-types.js`);

before(async () => {
  installDocument(["code", "http", "plus"]);
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
  assert.deepEqual(addableIn("pipeline").map((t) => t.kind), ["stage", "pipeline"]);
  assert.deepEqual(addableIn("action").map((t) => t.kind), ["timer", "code", "http", "if", "switch", "agent", "set", "github", "postgres", "sqlite", "mcp_tool", "github_tool", "http_tool", "code_tool", "postgres_tool", "sqlite_tool", "handover_tool", "artifact", "context", "note"]);
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
  assert.equal(code.subtitle(), "Execute Command");
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
    ["in", "input", "left", 0], ["pass", "output", "right", 0], ["error", "output", "right", 0],
  ]);
  const stage = typeOf("stage").ports();
  assert.equal(stage.length, 6);
  assert.deepEqual(stage.filter((p) => p.name === "start").map((p) => [p.direction, p.side, p.slot]), [["both", "left", 0], ["both", "left", 1], ["both", "left", 2]]);
  assert.deepEqual(stage.filter((p) => p.name === "end").map((p) => p.side), ["right", "right", "right"]);
});

test("visibility: the error output exists only with the setting, an output without fail has no Fail port", () => {
  const action = typeOf("action");
  assert.equal(action.isVisible(node("action", { config: {} }), "error"), false);
  assert.equal(action.isVisible(node("action", { config: { on_failure: "error_output" } }), "error"), true);
  assert.equal(action.isVisible(node("action"), "error"), false, "not set means the default, Stop the run");
  assert.equal(action.isVisible(node("action", { config: { on_failure: "continue" } }), "error"), false);
  assert.equal(action.isVisible(node("action", { config: {} }), "pass"), true);
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

test("slotHeights: from the first row of a new action to the lowest one, the middle one halfway, all inside the stage", () => {
  const near = (actual, expected, message) => assert.ok(Math.abs(actual - expected) < 1e-9, `${message}: ${actual} against ${expected}`);
  // the action is 68 high and 190 wide: its input sits at 34, and so does its On Pass (the error output is hidden by default, ADR-061); the highest row is FIRST_ROW (12)
  assert.equal(FIRST_ROW, 12, "the highest row an action can sit in");
  const topIn = HEADER + FIRST_ROW + 34;
  const bottomIn = 360 - STAGE_MARGIN - 68 + 34;
  assert.deepEqual(slotHeights(360, "in"), [topIn, (topIn + bottomIn) / 2, bottomIn], "left: the inputs");
  const out = slotHeights(360, "out");
  near(out[0], HEADER + FIRST_ROW + 34, "right: the first row's On Pass");
  near(out[2], 360 - STAGE_MARGIN - 68 + 34, "right: the lowest On Pass");
  near(out[1], (out[0] + out[2]) / 2, "right: halfway");
  assert.deepEqual(slotHeights(460, "in").map((y, i) => y - slotHeights(360, "in")[i]), [0, 50, 100], "a taller stage moves the lower points");
  assert.ok(slotHeights(100, "in").every((y) => y >= HEADER / 2 && y <= 100 - 8), "never outside the stage, however small it is");
});

test("portLocal spreads the shown ports down their side; the output kind pins its connectors", () => {
  const action = typeOf("action");
  const withFail = node("action", { config: { on_failure: "error_output" } });
  assert.deepEqual(action.portLocal(withFail, "in"), { x: 0, y: 34 });
  assert.deepEqual(action.portLocal(withFail, "pass"), { x: 190, y: 68 / 3 });
  assert.deepEqual(action.portLocal(withFail, "error"), { x: 190, y: (68 / 3) * 2 });
  const withoutFail = node("action", { config: {} });
  assert.deepEqual(action.portLocal(withoutFail, "pass"), { x: 190, y: 34 }, "the only shown output sits in the middle");
  assert.deepEqual(action.portLocal(withoutFail, "nonsense"), { x: 190, y: 34 }, "an unknown port falls back to the first");
  const output = typeOf("output");
  assert.deepEqual(output.portLocal(node("output"), "pass"), { x: 0, y: 60 });
  assert.deepEqual(output.portLocal(node("output"), "fail"), { x: 0, y: 84 });
  const stage = node("stage", { width: 400, height: 300 });
  assert.deepEqual(typeOf("stage").portLocal(stage, "start", 2), { x: 0, y: slotHeights(300, "in")[2] }, "the left points use the heights of the inputs");
  assert.deepEqual(typeOf("stage").portLocal(stage, "end"), { x: 400, y: slotHeights(300, "out")[0] }, "the right ones those of the On Pass");
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
  assert.deepEqual(sections("action"), ["link:action:Definition/Action/Not defined", "settings:action", 'actions:action:{"open":true}']);
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

test("render: a stage has a header with caption, name and the \"+\" button that opens a menu, and an empty body", () => {
  const el = new FakeNode("div");
  typeOf("stage").render(el, node("stage"), { name: "NAME", caption: "CAPTION" });
  const [header, body] = el.children;
  assert.equal(header.className, "ge-stage__header");
  assert.equal(body.className, "ge-stage__body");
  const [caption, name, add] = header.children;
  assert.deepEqual([caption, name], ["CAPTION", "NAME"]);
  assert.equal(add.type, "button");
  assert.equal(add.textContent, "", "an icon only: the name is its accessible name");
  assert.equal(add.children[0].iconName, "plus");
  assert.match(add.className, /\bicon-button\b/, "a catalog button (ADR-059), not a style of its own");
  assert.equal(add.attributes["aria-label"], "Add to stage");
  assert.equal(add.attributes["aria-haspopup"], "menu", "it opens a menu (Action, Guard), it does not add by itself");
  assert.equal(add.dataset.stageAdd, "");
  assert.equal(add.dataset.addAction, undefined);
});

// the add menu of the real manifests, plus a kind that has no place in it
const KINDS = [
  ...NODE_TYPES.filter((t) => t.addable && t.kind !== "note").map(({ kind, label, menu, menu_icon }) => ({ kind, label, menu, menu_icon })),
  { kind: "future_kind", label: "Something new", menu: null, menu_icon: undefined },
];

test("the kinds of the add menu are grouped in a fixed order, and a kind nobody grouped is still offered", () => {
  const groups = groupAddable(KINDS);
  assert.deepEqual(groups.map((g) => g.group), ["Structure", "AI", "Agent tools", "Apps and data", "Core", "Data", "Flow", "More"]);
  assert.deepEqual(groups.find((g) => g.group === "Flow").types.map((t) => t.kind), ["if", "switch", "timer"]);
  assert.deepEqual(groups.find((g) => g.group === "More").types.map((t) => t.kind), ["future_kind"]);
  assert.equal(groups.flatMap((g) => g.types).length, KINDS.length, "nothing is lost");
});

test("a kind the instance has switched off keeps its reason in the search results, so the menu can mark it (ADR-075)", () => {
  const kinds = KINDS.map((t) => (t.kind === "code" ? { ...t, unavailable: "switched off here" } : t));
  assert.equal(searchAddable(kinds, "code").find((t) => t.kind === "code").unavailable, "switched off here");
  assert.equal(searchAddable(kinds, "http").find((t) => t.kind === "http").unavailable, undefined, "a kind that can run says nothing");
});

test("searching looks at the elements only, by name or kind, ignoring case, and says which cluster each is in", () => {
  assert.deepEqual(searchAddable(KINDS, "git").map((t) => t.kind), ["github_tool", "github"]); // the GitHub MCP node is found by its name too
  assert.deepEqual(searchAddable(KINDS, "HTTP").map((t) => t.kind), ["http_tool", "http"], "in the order of the clusters: the tool before the core kind");
  assert.deepEqual(searchAddable(KINDS, "mcp").map((t) => t.kind), ["mcp_tool", "github_tool"]); // the kind matches, and the GitHub MCP node by its name
  assert.deepEqual(searchAddable(KINDS, "  CODE "), searchAddable(KINDS, "code"));
  assert.deepEqual(searchAddable(KINDS, "flow"), [], "a cluster's name is no search term: the clusters only help to find your way");
  assert.deepEqual(searchAddable(KINDS, "zzz"), []);
  assert.deepEqual(searchAddable(KINDS, "").length, KINDS.length, "no search: everything, in the order of the clusters");
});

test("a placeholder of the menu is no kind: it is offered in its scopes, in its cluster after Pipeline, and found by its name", () => {
  setPlaceholders(PLACEHOLDERS);
  try {
    assert.deepEqual(addableIn("pipeline").map((t) => t.kind), ["stage", "pipeline"], "kinds only: choosing a placeholder never adds a node");
    assert.deepEqual(placeholdersIn("pipeline").map((p) => p.kind), ["guard"]);
    assert.deepEqual(placeholdersIn("action").map((p) => p.kind), ["guard"], "an action definition offers it too: it watches the whole action (ADR-060)");
    assert.deepEqual(placeholdersIn("elsewhere"), []);
    const structure = groupAddable([...addableIn("pipeline"), ...placeholdersIn("pipeline")]).find((g) => g.group === "Structure");
    assert.deepEqual(structure.types.map((t) => t.kind), ["stage", "pipeline", "guard"]);
    const found = searchAddable([...addableIn("pipeline"), ...placeholdersIn("pipeline")], "guard");
    assert.deepEqual(found, [{ kind: "guard", label: "Guard", group: "Structure", menu_icon: "shield", placeholder: true, icon: "shield", soon: false }]);
    assert.equal(placeholderOf("guard").soon, false, "guards exist: the entry is no longer a place held for later");
    assert.equal(placeholderOf("nothing"), null);
  } finally {
    setPlaceholders([]);
  }
  assert.deepEqual(placeholdersIn("pipeline"), [], "without what the server declares there is nothing to offer");
  setPlaceholders("not a list");
  assert.deepEqual(placeholdersIn("pipeline"), [], "a bad answer is no list");
});

test("every kind that can be added has a glyph for the menus: its manifest's menu_icon or its card icon", () => {
  for (const scope of ["pipeline", "action"])
    for (const type of addableIn(scope).filter((t) => t.kind !== "note")) assert.ok(type.menu_icon, `${type.kind} has no glyph`); // "note" is the tests' own kind, without a manifest
  assert.equal(typeOf("stage").menu_icon, "layers", "no icon on its card, one in the menus");
  assert.equal(typeOf("action").menu_icon, "action", "the stage's \"+\" menu reads it from here");
  assert.deepEqual(searchAddable(KINDS, "stage").map((t) => t.menu_icon), ["layers"], "the search keeps the glyph");
});
