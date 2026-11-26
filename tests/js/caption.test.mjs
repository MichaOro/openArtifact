import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const JS = "../../openartifact/static/js/editor/";
const { renderCaption, hostAndPath, short } = await import(`${JS}caption.js`);
const { FUNCTIONS } = await import(`${JS}view-functions.js`);

const node = (config = {}, extra = {}) => ({ id: "n", name: "My node", seconds: 90, config, ...extra });

test("a key is a setting of the node, an @ key a field of it, and an empty one takes the default", () => {
  assert.equal(renderCaption("{language} · {code}", node({ language: "sh", code: "echo" })), "sh · echo");
  assert.equal(renderCaption("{@seconds} s", node()), "90 s");
  assert.equal(renderCaption("{language|default:sh}", node()), "sh");
  assert.equal(renderCaption("{language|default:sh}", node({ language: "python" })), "python");
  assert.equal(renderCaption("{tool_name|default:@name}", node()), "My node", "a default may be a field of the node");
  assert.equal(renderCaption("{tool_name|default:@name}", node({ tool_name: "find" })), "find");
});

test("filters run left to right", () => {
  assert.equal(renderCaption("{code|first_line}", node({ code: "\n  \n  print('hi')  \nmore" })), "print('hi')");
  assert.equal(renderCaption("{code|first_line|default:no code yet}", node({ code: "  \n " })), "no code yet");
  assert.equal(renderCaption("{text|trim|short}", node({ text: `  ${"x".repeat(60)}  ` })), `${"x".repeat(40)}…`);
  assert.equal(renderCaption("{fields|field_names|short|default:no field yet}", node({ fields: "priority = high\nvar.score = 3\nBad = 1" })), "priority, score");
  assert.equal(renderCaption("{fields|field_names|default:no field yet}", node({})), "no field yet");
});

test("an address is shown as host and path, never with its query, fragment or credentials", () => {
  assert.equal(hostAndPath("https://user:pw@example.org/hook?token=secret#frag"), "example.org/hook");
  assert.equal(hostAndPath("https://example.org/"), "example.org");
  assert.equal(hostAndPath("user:pw@example.org/a?x=1"), "example.org/a");
  assert.equal(renderCaption("{method|default:GET} {url|host_path|default:no URL yet}", node({ method: "POST", url: "https://a.org/x?k=1" })), "POST a.org/x");
  assert.equal(renderCaption("{url|host_path|default:no endpoint yet}", node({ url: "" })), "no endpoint yet");
  assert.equal(short("y".repeat(41)), `${"y".repeat(40)}…`);
  assert.equal(short("y".repeat(40)), "y".repeat(40));
});

test("a conditional part is there only when every clause holds", () => {
  const t = "{?allow_write:changes · }{query|default:no query}";
  assert.equal(renderCaption(t, node({ query: "q", allow_write: true })), "changes · q");
  assert.equal(renderCaption(t, node({ query: "q", allow_write: false })), "q");
  const off = "{operation}{?operation=Create comment&!allow_comments: (off)}";
  assert.equal(renderCaption(off, node({ operation: "Create comment" })), "Create comment (off)");
  assert.equal(renderCaption(off, node({ operation: "Create comment", allow_comments: true })), "Create comment");
  assert.equal(renderCaption(off, node({ operation: "List issues" })), "List issues");
  assert.equal(renderCaption("{?@definition_id:linked}", node({}, { definition_id: "d" })), "linked");
  assert.equal(renderCaption("{?@definition_id:linked}", node({}, { definition_id: null })), "");
});

test("a text without parts stays as it is", () => {
  assert.equal(renderCaption("just text", node()), "just text");
});

test("every function the descriptions of the kinds name exists in the editor's registry, and the registry offers nothing a manifest cannot name", () => {
  const description = JSON.parse(readFileSync(new URL("../fixtures/node-types.json", import.meta.url), "utf8"));
  const named = { caption: new Set(), visible: new Set(), label: new Set(), size: new Set(), group_used: new Set() };
  for (const kind of description) {
    if (kind.ui.caption?.fn) named.caption.add(kind.ui.caption.fn);
    if (kind.ui.size_fn) named.size.add(kind.ui.size_fn);
    if (kind.ui.group_used_fn) named.group_used.add(kind.ui.group_used_fn);
    for (const port of [...kind.inputs, ...kind.outputs]) {
      if (port.visible_when?.fn) named.visible.add(port.visible_when.fn);
      if (port.label_from) named.label.add(port.label_from);
    }
  }
  for (const [group, names] of Object.entries(named)) {
    for (const name of names) assert.equal(typeof FUNCTIONS[group][name], "function", `${group}: ${name}`);
  }
  assert.ok(named.caption.size >= 3 && named.visible.has("switch_case_used"));
  // the list the server checks manifests against (CLIENT_FUNCTIONS in graph/manifest.py)
  const server = {
    caption: ["if_summary", "switch_summary", "agent_summary"],
    visible: ["switch_case_used"],
    label: ["switch_case_label"],
    size: ["switch_size"],
    group_used: ["switch_group_used"],
  };
  for (const [group, names] of Object.entries(server)) assert.deepEqual(Object.keys(FUNCTIONS[group]).sort(), [...names].sort(), group);
});
