/* A node's look and rules, recorded for every kind (tests/js/fixtures/views-golden.json): size, caption, ports and where
 * they sit, which are shown, the labels, what may feed what. The kinds of nodes are declared in YAML (ADR-054) and drawn by
 * one generic view per behaviour; this keeps what each kind looked like before that, and must keep passing.
 * UPDATE_GOLDEN=1 writes the file again (only after a change of a look was meant). */
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { test } from "node:test";
import { installDocument, loadTypes } from "./support.mjs";

const JS = "../../openartifact/static/js/editor/";
const DESCRIPTION = new URL("../fixtures/node-types.json", import.meta.url);
const GOLDEN = new URL("./fixtures/views-golden.json", import.meta.url);
const { loadNodeTypes, typeOf, rememberAgents } = await import(`${JS}node-types.js`);

const description = JSON.parse(readFileSync(DESCRIPTION, "utf8"));
installDocument(["code", "http", "if", "switch", "agent", "pencil", "github", "database", "plug", "message"]);
const real = globalThis.fetch;
globalThis.fetch = async () => ({ status: 200, ok: true, json: async () => description });
await loadNodeTypes();
globalThis.fetch = real;
rememberAgents([{ id: "agent-1", name: "Triage" }]);

const base = { id: "n", name: "Node", x: 0, y: 0, stage_id: null, config: {}, seconds: 5, fail_enabled: false, definition_id: null, definition_name: null, definition_fail_enabled: true, width: 300, height: 200 };

const CASES = {
  trigger: [{}],
  complete: [{}],
  stage: [{}, { width: 420, height: 260 }],
  action: [{}, { definition_id: "d", definition_name: "Check", definition_fail_enabled: false }, { definition_id: "d", definition_fail_enabled: true }],
  pipeline: [{}, { definition_id: "p", definition_name: "Build" }],
  timer: [{ seconds: 5 }, { seconds: 90 }],
  output: [{ fail_enabled: false }, { fail_enabled: true }],
  code: [{}, { config: { language: "python", code: "\n  print('hi')\nmore" } }, { config: { code: "echo one" } }],
  http: [{}, { config: { method: "POST", url: "https://user:pw@example.org/hook?token=secret#frag" } }, { config: { url: "user:pw@example.org/a?x=1" } }],
  if: [{}, { config: { left_1: "${var.p}", operator_1: "equals", right_1: "high" } }, { config: { left_2: "x", operator_2: "is empty", left_3: "y", right_3: "z", operator_3: "contains" } }, { config: { left_1: "a very long value that goes on and on and on forever", operator_1: "not equals", right_1: "b" } }],
  switch: [{}, { config: { value: "${var.tier}", case_1: "silver", case_2: "gold" } }, { config: { case_operator_1: "is empty", case_2: "10", case_operator_2: "greater than", case_3: "urgent", case_operator_3: "contains" } }, { config: { value: "v", case_1: "a", case_2: "b", case_3: "c", case_4: "d", case_5: "e", case_6: "f" } }],
  set: [{}, { config: { fields: "priority = high\nvar.score = 3\nBad = 1" } }, { config: { fields: "a = 1\nb = 2\nc = 3\nd = 4\ne = 5\nf = 6\ng = 7\nh = 8\ni = 9\nj = 10" } }],
  agent: [{}, { config: { agent_id: "agent-1" } }, { config: { agent_id: "unknown", temperature: 0.5, retries: 0, model: "m" } }, { config: { agent_id: "x" }, agent: { name: "Frozen" } }],
  github: [{}, { config: { operation: "Create comment", repository: "acme/tool" } }, { config: { operation: "Create comment", repository: "acme/tool", allow_comments: true } }, { config: { operation: "List issues", repository: "a/b" } }],
  postgres: [{}, { config: { query: "\n  SELECT 1\nFROM t" } }, { config: { query: "UPDATE t SET a = 1", allow_write: true } }],
  mcp_tool: [{}, { config: { url: "https://api.example.org/mcp/?k=1" } }],
  http_tool: [{}, { config: { method: "POST", url: "https://api.example.org/items/{id}?x=1" } }],
  code_tool: [{}, { config: { language: "sh", tool_name: "run_it" } }],
  artifact: [{}, { config: { operation: "Add comment" } }],
  postgres_tool: [{}, { config: { query: "SELECT 1", tool_name: "find" } }, { config: { query: "DELETE FROM t", allow_write: true } }],
};

const GROUPS = ["Condition 1", "Condition 2", "Case 1", "Case 2", "Case 3", "Model & Generation", "Other"];
const node = (kind, extra, stage = null) => ({ ...base, kind, id: `${kind}-1`, name: description.find((d) => d.kind === kind).label, stage_id: stage, ...extra });

function record() {
  const out = {};
  const targets = description.map((d) => node(d.kind, d.kind === "action" ? { stage_id: "stage-1" } : {}));
  targets.push({ ...node("stage", {}), id: "stage-1" });
  for (const [kind, variants] of Object.entries(CASES)) {
    const type = typeOf(kind);
    out[kind] = variants.map((extra) => {
      const n = node(kind, extra, kind === "action" ? "stage-1" : null);
      const ports = type.ports().map((p) => ({
        name: p.name,
        slot: p.slot,
        direction: p.direction,
        side: p.side,
        visible: type.isVisible(n, p.name),
        label: type.portLabel(p.name, n),
        labelled: type.labelled(p),
        local: type.portLocal(n, p.name, p.slot ?? 0),
      }));
      const feeds = {};
      for (const p of type.ports().filter((q) => q.direction !== "input")) {
        for (const target of targets) {
          const targetType = typeOf(target.kind);
          for (const q of targetType.ports().filter((x) => x.direction !== "output")) {
            feeds[`${p.name}>${target.id}:${q.name}`] = type.canFeed(n, p.name, target, q.name);
          }
        }
      }
      return {
        node: extra,
        size: type.size(n),
        caption: type.caption(n),
        subtitle: type.subtitle(n),
        displayName: type.displayName(n),
        renamable: type.renamable(n),
        icon: type.constructor.icon ?? null,
        ports,
        groups: Object.fromEntries(GROUPS.map((g) => [g, type.groupUsed?.(n, g) ?? null])),
        feeds,
      };
    });
  }
  return out;
}

test("every kind looks and behaves as it did before the kinds were declared in YAML", () => {
  const now = record();
  if (process.env.UPDATE_GOLDEN) {
    writeFileSync(GOLDEN, `${JSON.stringify(now, null, 1)}\n`);
    return;
  }
  const golden = JSON.parse(readFileSync(GOLDEN, "utf8"));
  assert.deepEqual(Object.keys(now), Object.keys(golden));
  for (const kind of Object.keys(golden)) assert.deepEqual(now[kind], golden[kind], `kind ${kind}`);
});
