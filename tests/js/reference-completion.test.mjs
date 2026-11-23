import assert from "node:assert/strict";
import { test } from "node:test";

const { applyCompletion, candidatesFor, filterCandidates, nodeKey, openReference } = await import("../../openartifact/static/js/editor/reference-completion.js");

const NODES = [
  { id: "a", kind: "code", name: "Fetch user", config: { sets_variables: "priority\nscore\n\n" } },
  { id: "b", kind: "http", name: "Ping" },
  { id: "c", kind: "trigger", name: "Trigger" },
  { id: "d", kind: "if", name: "Decide" },
  { id: "e", kind: "code", name: "Other", config: { sets_variables: "score" } },
];

test("a node key is the name with other characters as underscores, like the server's", () => {
  assert.equal(nodeKey("Fetch user"), "Fetch_user");
  assert.equal(nodeKey("  a-b_c.d/é "), "a-b_c_d__");
  assert.equal(nodeKey("   "), "_");
});

test("a reference is open after ${ until it is closed or broken", () => {
  assert.deepEqual(openReference("a ${", 4), { start: 2, query: "" });
  assert.deepEqual(openReference("x ${node.Fe", 11), { start: 2, query: "node.Fe" });
  assert.equal(openReference("x ${node.A.output}", 18), null); // closed
  assert.equal(openReference("x ${node. A", 11), null); // white space ends it
  assert.equal(openReference("no reference", 5), null);
  assert.deepEqual(openReference("${a} and ${v", 12), { start: 9, query: "v" }); // the last one counts
  assert.deepEqual(openReference("${x", 3), { start: 0, query: "x" });
  assert.deepEqual(openReference("${abc} tail", 4), { start: 0, query: "ab" }); // the caret decides, not the end of the text
});

test("candidates list the nodes with results, the declared variables once, and secrets only when allowed", () => {
  const found = candidatesFor(NODES, { exceptId: "d", secrets: ["API_KEY"] }).map((c) => c.insert);
  assert.deepEqual(found.filter((i) => i.startsWith("node.Fetch_user")), ["node.Fetch_user.output", "node.Fetch_user.exit_code", "node.Fetch_user.outcome", "node.Fetch_user.reason", "node.Fetch_user.data."]);
  assert.ok(found.includes("node.Ping.output"));
  assert.ok(!found.some((i) => i.startsWith("node.Trigger") || i.startsWith("node.Decide")), "no trigger, not the node itself");
  assert.deepEqual(found.filter((i) => i.startsWith("var.")), ["var.priority", "var.score"]);
  assert.ok(!found.some((i) => i.startsWith("secret:")));
  const withSecrets = candidatesFor(NODES, { secrets: ["API_KEY"], allowSecrets: true }).map((c) => c.insert);
  assert.ok(withSecrets.includes("secret:API_KEY"));
});

test("two nodes with one name are not offered (the reference would be ambiguous)", () => {
  const twice = [{ id: "1", kind: "code", name: "Same" }, { id: "2", kind: "http", name: "Same" }];
  assert.equal(candidatesFor(twice).filter((c) => c.insert.endsWith(".output")).length, 1);
});

test("filtering is case-insensitive, prefix matches first, and bounded", () => {
  const all = candidatesFor(NODES, {});
  assert.equal(filterCandidates(all, "").length, all.length);
  const hits = filterCandidates(all, "node.ping").map((c) => c.insert);
  assert.deepEqual(hits.slice(0, 2), ["node.Ping.output", "node.Ping.exit_code"]);
  const loose = filterCandidates(all, "score").map((c) => c.insert);
  assert.deepEqual(loose, ["var.score"]);
  assert.deepEqual(filterCandidates(all, "zzz"), []);
  const many = Array.from({ length: 100 }, (_, i) => ({ insert: `var.v${i}`, detail: "", complete: true }));
  assert.equal(filterCandidates(many, "var").length, 40);
});

test("a completion replaces what was typed and closes the brace", () => {
  const text = "url/${node.Pi?x=1";
  const reference = openReference(text, 13);
  const candidate = { insert: "node.Ping.output", detail: "", complete: true };
  assert.deepEqual(applyCompletion(text, 13, reference, candidate), { text: "url/${node.Ping.output}?x=1", caret: 23 });
});

test("an existing closing brace is kept once, a data path stays open", () => {
  const text = "${va}";
  const done = applyCompletion(text, 4, openReference(text, 4), { insert: "var.score", detail: "", complete: true });
  assert.deepEqual(done, { text: "${var.score}", caret: 12 });
  const path = applyCompletion("${no", 4, openReference("${no", 4), { insert: "node.A.data.", detail: "", complete: false });
  assert.deepEqual(path, { text: "${node.A.data.", caret: 14 });
});

test("an Edit Fields node offers its result and the variables it sets", async () => {
  const { fieldNames } = await import("../../openartifact/static/js/editor/reference-completion.js");
  assert.deepEqual(fieldNames("a = 1\n var.b=2\nBad = 3\nno equals\n\nc ="), ["a", "b", "c"]);
  assert.deepEqual(fieldNames(null), []);
  const nodes = [
    { id: "s", kind: "set", name: "Prepare", config: { fields: "priority = high\nscore = 3" } },
    { id: "c", kind: "code", name: "Code", config: { sets_variables: "score" } },
  ];
  const inserts = candidatesFor(nodes).map((c) => c.insert);
  assert.ok(inserts.includes("node.Prepare.output"));
  assert.deepEqual(inserts.filter((i) => i.startsWith("var.")), ["var.priority", "var.score"]); // once each
});
