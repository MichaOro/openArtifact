import test from "node:test";
import assert from "node:assert/strict";
import { ATTACHMENT_SOURCE_PORT, ATTACHMENT_TARGET_PORT, EDGE_KINDS, LINE_STYLES, attachmentLink, isAttachmentTarget, kindOfEdge, kindOfPort } from "../../openartifact/static/js/editor/edge-kinds.js";
import { attachmentPath, edgePath } from "../../openartifact/static/js/editor/geometry.js";

// The kinds of connection are data (ADR-093): this checks the table itself and that the common builder serves every row.

const FIELDS = ["route", "arrow", "styles", "hangs", "levelsPorts", "flowDecoration", "cssName"];

test("every kind of connection declares every field the common code reads", () => {
  assert.deepEqual(Object.keys(EDGE_KINDS).sort(), ["attachment", "flow"]);
  for (const [name, kind] of Object.entries(EDGE_KINDS)) {
    for (const field of FIELDS) assert.ok(field in kind, `${name} lacks ${field}`);
    assert.equal(typeof kind.cssName({ source_port: "pass", target_port: "in" }), "string");
    assert.ok(kind.styles.length >= 1 && kind.styles.every((s) => LINE_STYLES.includes(s)), `${name} offers an unknown style`);
  }
});

test("the toolbar of a connection offers exactly the styles of its kind: the tool attachment offers the same three as a flow edge", () => {
  assert.deepEqual(EDGE_KINDS.attachment.styles, EDGE_KINDS.flow.styles);
  assert.deepEqual(EDGE_KINDS.flow.styles, ["curved", "straight", "elbow"]);
});

test("the kind of an edge, and of a connection being dragged, comes from its ports", () => {
  assert.equal(kindOfEdge({ source_port: "pass", target_port: "in" }), EDGE_KINDS.flow);
  assert.equal(kindOfEdge({ source_port: ATTACHMENT_SOURCE_PORT, target_port: ATTACHMENT_TARGET_PORT }), EDGE_KINDS.attachment);
  assert.equal(kindOfPort(ATTACHMENT_SOURCE_PORT), EDGE_KINDS.attachment);
  assert.equal(kindOfPort(ATTACHMENT_TARGET_PORT), EDGE_KINDS.attachment);
  assert.equal(kindOfPort("pass"), EDGE_KINDS.flow);
  assert.equal(isAttachmentTarget(ATTACHMENT_TARGET_PORT), true);
  assert.equal(isAttachmentTarget("in"), false);
});

test("the attachment is the kind that hangs on its target: no arrow, not levelled with the ports of a stage, decorated as a tool", () => {
  assert.equal(EDGE_KINDS.attachment.hangs, true);
  assert.equal(EDGE_KINDS.attachment.arrow, false);
  assert.equal(EDGE_KINDS.attachment.levelsPorts, false);
  assert.equal(EDGE_KINDS.attachment.flowDecoration, "tool");
  assert.equal(EDGE_KINDS.flow.hangs, false);
  assert.equal(EDGE_KINDS.flow.arrow, true);
  assert.equal(EDGE_KINDS.flow.levelsPorts, true);
});

test("a new attachment names its tool as the source and its agent as the target", () => {
  assert.deepEqual(attachmentLink("t1", "a1"), { source_id: "t1", source_port: "tool", target_id: "a1", target_port: "tools" });
});

test("the common builder serves every kind and style: the attachment's route is the attachment builder, a flow edge is not", () => {
  const agent = { x: 400, y: 300, width: 250, height: 84 };
  const tool = { x: 430, y: 504, width: 180, height: 52 };
  const from = { x: tool.x + tool.width / 2, y: tool.y };
  const to = { x: agent.x + agent.width / 2, y: agent.y + agent.height };
  for (const style of LINE_STYLES) {
    assert.equal(edgePath(from, to, tool, agent, { style, kind: EDGE_KINDS.attachment }), attachmentPath(from, to, tool, agent, { style }), style);
    assert.notEqual(edgePath(from, to, tool, agent, { style, kind: EDGE_KINDS.attachment }), edgePath(from, to, tool, agent, { style, kind: EDGE_KINDS.flow }), style);
  }
  // the three styles of a tool below its agent are three different lines that start and end at the same ports
  const lines = LINE_STYLES.map((style) => attachmentPath(from, to, tool, agent, { style }));
  assert.equal(new Set(lines).size, 3);
  for (const d of lines) {
    assert.ok(d.startsWith(`M ${from.x} ${from.y}`), d);
    assert.ok(d.endsWith(`${to.x} ${to.y}`), d);
  }
});
