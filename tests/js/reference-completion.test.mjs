import assert from "node:assert/strict";
import { test } from "node:test";

const { applyCompletion, candidatesFor, filterCandidates, nodeKey, nodeLabel, openReference, suggestionsFor } = await import("../../openartifact/static/js/editor/reference-completion.js");

// what the server says about each kind (the manifests): which kinds leave a result, their data keys and the variables they set
const { readFileSync } = await import("node:fs");
const DESCRIBED = new Map(JSON.parse(readFileSync(new URL("../fixtures/node-types.json", import.meta.url), "utf8")).map((d) => [d.kind, d]));
const kinds = (kind) => DESCRIBED.get(kind);
/** What the list shows of a candidate: its name form when it has one (a node is inserted by its id, ADR-082), else the text itself. */
const shown = (c) => c.label ?? c.insert;

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
  const all = candidatesFor(NODES, { kinds, exceptId: "d", secrets: ["API_KEY"] });
  const found = all.map(shown);
  assert.deepEqual(found.filter((i) => i.startsWith("(Fetch user)")), ["(Fetch user).output", "(Fetch user).exit_code", "(Fetch user).outcome", "(Fetch user).success", "(Fetch user).reason", "(Fetch user).attempts", "(Fetch user).duration_ms", "(Fetch user).data."]);
  assert.ok(found.includes("(Ping).output"));
  assert.ok(!found.some((i) => i.startsWith("(Trigger)") || i.startsWith("(Decide)")), "no trigger, not the node itself");
  assert.deepEqual(found.filter((i) => i.startsWith("var.")), ["var.priority", "var.score"]);
  assert.ok(!found.some((i) => i.startsWith("secret:")));
  const withSecrets = candidatesFor(NODES, { kinds, secrets: ["API_KEY"], allowSecrets: true }).map((c) => c.insert);
  assert.ok(withSecrets.includes("secret:API_KEY"));
});

test("a node is listed and inserted by its name (the field shows names, never ids), the id is what is stored (ADR-082 add. 1)", () => {
  const all = candidatesFor(NODES, { kinds });
  const output = all.find((c) => c.label === "(Fetch user).output");
  assert.equal(output.insert, "node:Fetch user.output");
  assert.equal(output.head, "node:Fetch user.");
  assert.equal(output.headLabel, "(Fetch user).");
  const renamed = candidatesFor([{ ...NODES[0], name: "Download" }], { kinds }).find((c) => c.insert === "node:Download.output");
  assert.equal(renamed.label, "(Download).output", "a rename shows at once: the name is only shown, reference-names.js turns it into the id when the field is saved");
});

test("a node of an action that is placed more than once is listed with its number", () => {
  assert.equal(nodeLabel({ name: "Check", definition_name: "Check", placement_number: 2 }), "Check #2");
  assert.equal(nodeLabel({ name: "Check", definition_name: "Check", placement_number: null }), "Check");
  assert.equal(nodeLabel({ name: "Own name" }), "Own name");
});

test("the declared inputs of the graph are offered as input.NAME and a placement with a contract by its outputs (ADR-083)", () => {
  const nodes = [
    { id: "t", kind: "trigger", name: "Trigger", config: { inputs: [{ name: "who", type: "text", required: true, description: "The person" }] } },
    { id: "p1", kind: "action", name: "Greet", definition_name: "Greet", placement_number: 1, definition_id: "d1" },
    { id: "p2", kind: "action", name: "Nothing", definition_name: "Nothing", definition_id: "d2" },
  ];
  const contracts = (node) => (node.definition_id === "d1" ? { outputs: ["greeting", "count"] } : null);
  const all = candidatesFor(nodes, { kinds, contracts });
  assert.deepEqual(all.filter((c) => c.head === "input.").map((c) => c.insert), ["input.who"]);
  const placement = all.filter((c) => c.head === "node:Greet #1.");
  assert.deepEqual(placement.map(shown), ["(Greet #1).outcome", "(Greet #1).success", "(Greet #1).reason", "(Greet #1).attempts", "(Greet #1).duration_ms", "(Greet #1).data.", "(Greet #1).data.greeting", "(Greet #1).data.count"]);
  assert.ok(!all.some((c) => c.head === "node:Nothing."), "an action without a contract leaves no result to read");
});

test("two nodes with one name are both offered, told apart by (1) and (2), never by an id (ADR-082 add. 1)", () => {
  const twice = [{ id: "1", kind: "code", name: "Same" }, { id: "2", kind: "http", name: "Same" }];
  const outputs = candidatesFor(twice, { kinds }).filter((c) => c.insert.endsWith(".output"));
  assert.deepEqual(outputs.map((c) => c.insert), ["node:Same (1).output", "node:Same (2).output"]);
});

test("filtering is case-insensitive, prefix matches first, and bounded", () => {
  const all = candidatesFor(NODES, { kinds });
  assert.equal(filterCandidates(all, "").length, all.length);
  const hits = filterCandidates(all, "(ping").map(shown);
  assert.deepEqual(hits.slice(0, 2), ["(Ping).output", "(Ping).exit_code"]);
  assert.deepEqual(filterCandidates(all, "node:Ping.").slice(0, 2).map(shown), ["(Ping).output", "(Ping).exit_code"], "the form with the node: head finds it too");
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
  const inserts = candidatesFor(nodes, { kinds }).map(shown);
  assert.ok(inserts.includes("(Prepare).output"));
  assert.deepEqual(inserts.filter((i) => i.startsWith("var.")), ["var.priority", "var.score"]); // once each
});

test("a name with blanks and a colon stays open while its parenthesis is typed, and a name with a bracket falls back to the key", () => {
  assert.deepEqual(openReference("${(Code: he", 11), { start: 0, query: "(Code: he" });
  assert.deepEqual(openReference("${(Code: hello).da", 18), { start: 0, query: "(Code: hello).da" });
  assert.equal(openReference("${(Code: hello).data x", 22), null); // blanks after the name end it
  assert.equal(openReference("${(Code\nx", 9), null);
  assert.deepEqual(openReference("${node:Fetch user.ou", 20), { start: 0, query: "node:Fetch user.ou" }, "a name with blanks in the node: form stays open");
  assert.equal(openReference("${node:Fetch user.output x", 26), null);
  const odd = candidatesFor([{ id: "1", kind: "code", name: "Say (hi)" }], { kinds }).map(shown);
  assert.ok(odd.includes("node:Say (hi).output"), "a name the list cannot spell in parentheses is shown in the node: form");
});

test("suggestions lead in steps: groups and nodes first, then what is behind the one chosen", () => {
  const all = candidatesFor(NODES, { kinds, secrets: ["API_KEY"], allowSecrets: true, cardFields: [{ name: "repo", label: "repo" }, { name: "date", label: "Date" }] });
  const first = suggestionsFor(all, "").map(shown);
  assert.deepEqual(first, ["card.", "var.", "secret:", "(Fetch user).", "(Ping).", "(Decide).", "(Other)."]);
  assert.deepEqual(suggestionsFor(all, "").filter((c) => c.label).map((c) => c.insert), ["node:Fetch user.", "node:Ping.", "node:Decide.", "node:Other."], "a group is inserted by the name of the node");
  assert.ok(suggestionsFor(all, "").every((c) => c.complete === false), "choosing one goes on to the next step");
  assert.deepEqual(suggestionsFor(all, "card.").map((c) => c.insert), ["card.title", "card.body", "card.text", "card.number", "card.repo", "card.date"]);
  assert.deepEqual(suggestionsFor(all, "card.d").map((c) => c.insert), ["card.date"]);
  assert.deepEqual(suggestionsFor(all, "(Fetch user).").map(shown), ["(Fetch user).output", "(Fetch user).exit_code", "(Fetch user).outcome", "(Fetch user).success", "(Fetch user).reason", "(Fetch user).attempts", "(Fetch user).duration_ms", "(Fetch user).data."]);
  assert.deepEqual(suggestionsFor(all, "(Fetch user).ou").map(shown), ["(Fetch user).output", "(Fetch user).outcome"]);
  assert.deepEqual(suggestionsFor(all, "node:Fetch user.ou").map(shown), ["(Fetch user).output", "(Fetch user).outcome"], "once the node: head is inserted the same list follows");
  assert.deepEqual(suggestionsFor(all, "var.").map((c) => c.insert), ["var.priority", "var.score"]);
  assert.deepEqual(suggestionsFor(all, "secret:").map((c) => c.insert), ["secret:API_KEY"]);
  assert.deepEqual(suggestionsFor(all, "pin").map(shown), ["(Ping)."], "typing a part of a name finds the node");
  assert.deepEqual(suggestionsFor(all, "zzz"), []);
});

test("a group shows how much is behind it", () => {
  const all = candidatesFor([], { kinds, cardFields: [{ name: "a", label: "A" }, { name: "b", label: "B" }] });
  assert.equal(suggestionsFor(all, "")[0].detail, "Card of this run");
  assert.equal(suggestionsFor(all, "")[0].icon, "card");
  const one = candidatesFor([{ id: "1", kind: "http", name: "Ping" }], { kinds });
  assert.equal(suggestionsFor(one, "").find((c) => c.label === "(Ping).").detail, "http node");
});

test("every kind the manifests say leaves a result is offered, with no list of kinds in the editor", () => {
  const nodes = ["code", "http", "github", "postgres", "artifact", "set", "agent", "if", "switch", "timer"].map((kind, i) => ({ id: String(i), kind, name: kind }));
  const withResult = candidatesFor(nodes, { kinds }).filter((c) => c.insert.endsWith(".output")).map((c) => c.kind);
  assert.deepEqual(withResult.sort(), ["agent", "artifact", "code", "github", "http", "if", "postgres", "set", "switch", "timer"]);
  // a trigger, an output and a tool leave nothing; a kind nobody described is not offered either
  const ofNodes = (list) => list.filter((c) => c.head !== "card."); // the card of the run is always offered
  const none = candidatesFor([{ id: "t", kind: "trigger", name: "T" }, { id: "o", kind: "output", name: "O" }, { id: "m", kind: "mcp_tool", name: "M" }, { id: "x", kind: "unheard_of", name: "X" }], { kinds });
  assert.deepEqual(ofNodes(none), []);
  assert.deepEqual(ofNodes(candidatesFor(nodes)), [], "without a description of the kinds nothing is assumed");
});

test("a kind offers the keys of data it declares, and the variables it sets come from its manifest", () => {
  const nodes = [
    { id: "a", kind: "artifact", name: "Artifact" },
    { id: "p", kind: "postgres", name: "Postgres" },
    { id: "s", kind: "set", name: "Edit", config: { fields: "score = 3\nvar.tag = x" } },
    { id: "c", kind: "code", name: "Code", config: { sets_variables: "level\n\nowner" } },
  ];
  const inserts = candidatesFor(nodes, { kinds }).map(shown);
  assert.ok(inserts.includes("(Artifact).data.comments"), "the comments of the artifact node");
  assert.ok(inserts.includes("(Postgres).data.rows"));
  for (const variable of ["var.score", "var.tag", "var.level", "var.owner"]) assert.ok(inserts.includes(variable), variable);
});
