/* The layout of a graph preview (components/graph-preview.js), without a DOM: where each node, each stage and each connection of a small
 * picture of a pipeline or an action sits. It is derived from the STRUCTURE of the graph (what follows what), not from the coordinates
 * of the editor (they only order the nodes of one layer the way the editor shows them), so it can be drawn as wide as the place is
 * and turned when it does not fit: layers side by side (horizontal) while that stays legible, otherwise one below the other (vertical).
 *
 *  - every connection of the graph is drawn once: a connection to the next layer is a curve; one that skips layers runs in a channel
 *    above the nodes, a connection back (a retry, a loop) in a channel below them; they use the gaps between the layers, so no line
 *    crosses a node it does not belong to;
 *  - a stage is a cluster: a frame around its actions, which are laid out by their own connections; the stage's start and end are
 *    the middle of the frame's two sides (the lines of the pipeline end there and the lines to the first and from the last actions
 *    start there);
 *  - tools below an agent hang in the agent's layer, linked by dashed lines.
 *
 *   const scene = sceneOfGraph(detail, (kind) => isTool(kind));   // an action or a pipeline: {nodes, edges} as the API gives them
 *   const picture = layoutScene(scene, { available: 280 });        // {orientation, scale, width, height, nodes, clusters, edges}
 */

const FAILING_PORTS = ["error", "fail", "else"]; // their connections are drawn as failures, like the canvas does
const PASSING_PORTS = ["pass", "yes", "true"];
const CHANNEL = 6; // the distance between two lines that run side by side in a channel
const HEAD = 14; // the room at the top of a stage's frame for its symbol

/** @typedef {{id: string, kind: string, name: string, x: number, y: number, stage: string|null, tool: boolean, cluster: boolean}} SceneNode */
/** @typedef {{id: string, from: string, to: string, fromPort: string, toPort: string, failing: boolean, passing: boolean}} SceneEdge */

/**
 * @param {{nodes: object[], edges: object[]}} detail the graph as the API gives it (a pipeline's nodes carry `stage_id`)
 * @param {(kind: string) => boolean} [isTool] whether a kind of node is a tool (hangs below an agent)
 * @returns {{nodes: SceneNode[], edges: SceneEdge[]}}
 */
export function sceneOfGraph(detail, isTool = () => false) {
  const nodes = (detail.nodes ?? []).map((n) => ({
    id: n.id,
    kind: n.kind,
    name: n.name ?? "",
    x: n.x ?? 0,
    y: n.y ?? 0,
    stage: n.stage_id ?? null,
    tool: Boolean(isTool(n.kind)),
    cluster: n.kind === "stage",
  }));
  const known = new Set(nodes.map((n) => n.id));
  const edges = (detail.edges ?? [])
    .filter((e) => known.has(e.source_id) && known.has(e.target_id))
    .map((e) => ({
      id: e.id ?? `${e.source_id}:${e.source_port}>${e.target_id}:${e.target_port}`,
      from: e.source_id,
      to: e.target_id,
      fromPort: e.source_port,
      toPort: e.target_port,
      failing: FAILING_PORTS.includes(e.source_port) || e.target_port === "fail",
      passing: PASSING_PORTS.includes(e.source_port),
    }));
  return { nodes, edges };
}

const byEditorOrder = (a, b) => a.y - b.y || a.x - b.x || String(a.id).localeCompare(String(b.id));

/**
 * The layer of every unit: the longest way to it, connections that lead back (found by a walk from the units nothing leads to) left out.
 * @returns {{layer: Map<string, number>, back: Set<string>}} `back`: the ids of the connections that lead back
 */
function layering(units, links, seeds) {
  const ids = units.map((u) => u.id);
  const out = new Map(ids.map((id) => [id, []]));
  const indegree = new Map(ids.map((id) => [id, 0]));
  for (const l of links) {
    out.get(l.from).push(l);
    if (l.from !== l.to) indegree.set(l.to, indegree.get(l.to) + 1);
  }
  const back = new Set();
  const state = new Map(); // 1: on the walk's way, 2: done
  const post = [];
  const walk = (id) => {
    state.set(id, 1);
    for (const l of out.get(id)) {
      const seen = state.get(l.to);
      if (l.from === l.to || seen === 1) back.add(l.id);
      else if (!seen) walk(l.to);
    }
    state.set(id, 2);
    post.push(id);
  };
  const first = [...seeds, ...ids.filter((id) => indegree.get(id) === 0), ...ids];
  for (const id of first) if (!state.get(id)) walk(id);
  const layer = new Map(ids.map((id) => [id, 0]));
  for (const id of post.reverse()) {
    for (const l of out.get(id)) if (!back.has(l.id)) layer.set(l.to, Math.max(layer.get(l.to), layer.get(id) + 1));
  }
  return { layer, back };
}

/**
 * @param {{nodes: SceneNode[], edges: SceneEdge[]}} scene
 * @param {{available: number, node?: number, gap?: number, minScale?: number, pad?: number}} options `available`: the width the picture may
 *   take (px); `node`, `gap`: the size of a node and the space between two layers; `minScale`: how far a horizontal picture may shrink
 *   before it is turned; `pad`: the room between a stage's frame and what it holds
 * @returns {{orientation: "horizontal"|"vertical", scale: number, width: number, height: number, node: number,
 *   nodes: (SceneNode & {x: number, y: number, width: number, height: number, cluster: string|null})[],
 *   clusters: {id: string, name: string, x: number, y: number, width: number, height: number}[],
 *   edges: {id: string, from: string, to: string, role: string, d: string, points: number[][], failing: boolean, passing: boolean, tool: boolean}[]}}
 */
export function layoutScene(scene, { available, node = 36, gap = 20, minScale = 0.6, pad = 10 } = {}) {
  const byId = new Map(scene.nodes.map((n) => [n.id, n]));
  const containerOf = (n) => n.stage ?? null;
  const toolsOf = new Map(); // the node a tool hangs below -> its tools
  const links = []; // the connections that are not tools, with their place in the structure
  const toolLinks = [];
  for (const e of scene.edges) {
    const f = byId.get(e.from);
    const t = byId.get(e.to);
    if (!f || !t) continue;
    if (f.tool) {
      if (!toolsOf.has(e.to)) toolsOf.set(e.to, []);
      toolsOf.get(e.to).push(f);
      toolLinks.push({ ...e, role: "tool" });
    } else if (f.cluster && containerOf(t) === f.id) links.push({ ...e, role: "entry", container: f.id });
    else if (t.cluster && containerOf(f) === t.id) links.push({ ...e, role: "exit", container: t.id });
    else if (containerOf(f) === containerOf(t)) links.push({ ...e, role: "flow", container: containerOf(f) });
  }
  const hanging = new Set([...toolsOf.values()].flat().map((n) => n.id));
  const isHanging = (n) => hanging.has(n.id);

  // ── the arrangement of one container (the whole graph, or the inside of one stage) in layers ──
  const arranged = new Map();
  function arrange(cid) {
    if (arranged.has(cid)) return arranged.get(cid);
    const units = scene.nodes.filter((n) => containerOf(n) === cid && !isHanging(n)).sort(byEditorOrder);
    const flow = links.filter((l) => l.role === "flow" && l.container === cid);
    const entries = links.filter((l) => l.role === "entry" && l.container === cid);
    const exits = links.filter((l) => l.role === "exit" && l.container === cid);
    const { layer, back } = layering(units, flow, entries.map((l) => l.to));
    const count = units.length ? Math.max(...layer.values()) + 1 : 0;
    const layers = Array.from({ length: count }, () => ({ rows: [], a: 0, size: 0, b: 0 }));
    for (const u of units) {
      const l = layers[layer.get(u.id)];
      l.rows.push(u);
      for (const tool of (toolsOf.get(u.id) ?? []).sort(byEditorOrder)) l.rows.push(tool);
    }
    const sizeOf = (u) => (u.cluster ? clusterSize(u.id) : { sa: node, sb: node });
    let A = 0;
    let B = 0;
    layers.forEach((l, i) => {
      l.size = Math.max(...l.rows.map((u) => sizeOf(u).sa));
      l.b = l.rows.reduce((sum, u) => sum + sizeOf(u).sb, 0) + gap * Math.max(0, l.rows.length - 1);
      l.a = A;
      A += l.size + (i < layers.length - 1 ? gap : 0);
      B = Math.max(B, l.b);
    });
    const long = flow.filter((l) => !back.has(l.id) && layer.get(l.to) - layer.get(l.from) > 1).length;
    const exitsAbove = exits.filter((l) => layer.get(l.from) < count - 1).length;
    const entriesAbove = entries.filter((l) => layer.get(l.to) > 0).length;
    const result = { units, layer, back, layers, A, B, above: long + exitsAbove + entriesAbove, below: back.size, sizeOf };
    arranged.set(cid, result);
    return result;
  }
  function clusterSize(id) {
    const ar = arrange(id);
    return { sa: ar.A + 2 * pad, sb: ar.B + 2 * pad + HEAD + CHANNEL * (ar.above + ar.below) };
  }

  // ── placing: boxes (a: along the layers, b: across them) ──
  const boxes = new Map(); // id -> {a, b, sa, sb, layer}
  const frames = new Map(); // stage id -> its frame {a, b, sa, sb}
  const content = new Map(); // container id -> {top, bottom, a0(i), a1(i)}
  function place(cid, oa, ob) {
    const ar = arrange(cid);
    ar.layers.forEach((l, i) => {
      let b = ob + (ar.B - l.b) / 2;
      for (const u of l.rows) {
        const { sa, sb } = ar.sizeOf(u);
        boxes.set(u.id, { a: oa + l.a, b, sa, sb, layer: i });
        b += sb + gap;
      }
    });
    content.set(cid, { top: ob, bottom: ob + ar.B, a0: (i) => oa + ar.layers[i].a, a1: (i) => oa + ar.layers[i].a + ar.layers[i].size });
    for (const u of ar.units) {
      if (!u.cluster) continue;
      const frame = boxes.get(u.id);
      frames.set(u.id, frame);
      place(u.id, frame.a + pad, frame.b + pad + HEAD + CHANNEL * arrange(u.id).above);
    }
  }
  place(null, 0, 0);

  // ── the lines ──
  const edges = [];
  const draw = (link, commands) => edges.push({ link, commands });
  const outPoint = (b) => [b.a + b.sa, b.b + b.sb / 2];
  const inPoint = (b) => [b.a, b.b + b.sb / 2];
  const curve = (p0, p3, s1) => {
    const mid = (s1 + p3[0]) / 2;
    return [["M", p0], ["L", [s1, p0[1]]], ["C", [mid, p0[1]], [mid, p3[1]], p3]];
  };
  const channel = (p0, s1, g1, g2, p3, y) => [["M", p0], ["L", [s1, p0[1]]], ["L", [g1, p0[1]]], ["L", [g1, y]], ["L", [g2, y]], ["L", [g2, p3[1]]], ["L", p3]];
  for (const cid of new Set(links.map((l) => l.container))) {
    const ar = arrange(cid);
    if (!ar.layers.length) continue;
    const { top, bottom, a0, a1 } = content.get(cid);
    const frame = cid === null ? null : frames.get(cid);
    let above = 0;
    let below = 0;
    const lanes = { top: () => top - CHANNEL * (1 + above++), bottom: () => bottom + CHANNEL * (1 + below++) };
    const last = ar.layers.length - 1;
    for (const l of links.filter((x) => x.container === cid)) {
      if (l.role === "flow") {
        const s = boxes.get(l.from);
        const t = boxes.get(l.to);
        const p0 = outPoint(s);
        const p3 = inPoint(t);
        const s1 = a1(s.layer);
        if (ar.back.has(l.id)) draw(l, channel(p0, s1, s1 + gap / 2, a0(t.layer) - gap / 2, p3, lanes.bottom()));
        else if (t.layer === s.layer + 1) draw(l, curve(p0, p3, s1));
        else draw(l, channel(p0, s1, s1 + gap / 2, a0(t.layer) - gap / 2, p3, lanes.top()));
      } else if (l.role === "entry") {
        const t = boxes.get(l.to);
        const p0 = [frame.a, frame.b + frame.sb / 2];
        const p3 = inPoint(t);
        if (t.layer === 0) draw(l, curve(p0, p3, p0[0]));
        else draw(l, channel(p0, p0[0], (frame.a + a0(0)) / 2, a0(t.layer) - gap / 2, p3, lanes.top()));
      } else {
        const s = boxes.get(l.from);
        const p0 = outPoint(s);
        const p3 = [frame.a + frame.sa, frame.b + frame.sb / 2];
        const s1 = a1(s.layer);
        if (s.layer === last) draw(l, curve(p0, p3, s1));
        else {
          const g = (a1(last) + p3[0]) / 2;
          const y = lanes.top();
          draw(l, [["M", p0], ["L", [s1, p0[1]]], ["L", [s1 + gap / 2, p0[1]]], ["L", [s1 + gap / 2, y]], ["L", [g, y]], ["L", [g, p3[1]]], ["L", p3]]);
        }
      }
    }
  }
  // tools: straight down from the node above them in their column (the agent, or the tool before)
  for (const [parent, tools] of toolsOf) {
    let above = boxes.get(parent);
    for (const tool of [...tools].sort(byEditorOrder)) {
      const b = boxes.get(tool.id);
      const link = toolLinks.find((l) => l.from === tool.id && l.to === parent);
      if (!above || !b || !link) continue;
      draw(link, [["M", [above.a + above.sa / 2, above.b + above.sb]], ["L", [b.a + b.sa / 2, b.b]]]);
      above = b;
    }
  }

  // ── the picture: orientation, size, and everything in x/y ──
  const sample = (commands) => {
    const points = [];
    let cursor = null;
    for (const [type, ...pts] of commands) {
      if (type === "C") {
        const [c1, c2, end] = pts;
        for (let k = 1; k <= 8; k += 1) {
          const t = k / 8;
          const u = 1 - t;
          points.push([0, 1].map((i) => u ** 3 * cursor[i] + 3 * u * u * t * c1[i] + 3 * u * t * t * c2[i] + t ** 3 * end[i]));
        }
        cursor = end;
      } else {
        cursor = pts[0];
        points.push(cursor);
      }
    }
    return points;
  };
  const drawn = edges.map((e) => ({ ...e, sampled: sample(e.commands) }));
  if (!boxes.size) return { orientation: "horizontal", scale: 1, width: 0, height: 0, node, nodes: [], clusters: [], edges: [] };
  let minA = Infinity;
  let maxA = -Infinity;
  let minB = Infinity;
  let maxB = -Infinity;
  const see = (a, b) => {
    minA = Math.min(minA, a);
    maxA = Math.max(maxA, a);
    minB = Math.min(minB, b);
    maxB = Math.max(maxB, b);
  };
  for (const b of boxes.values()) {
    see(b.a, b.b);
    see(b.a + b.sa, b.b + b.sb);
  }
  for (const e of drawn) for (const [a, b] of e.sampled) see(a, b);
  const lengthA = maxA - minA;
  const lengthB = maxB - minB;
  let orientation = "horizontal";
  let scale = Math.min(1, available / lengthA);
  if (scale < minScale && arrange(null).layers.length > 1) {
    orientation = "vertical";
    scale = Math.min(1, available / lengthB);
  }
  const horizontal = orientation === "horizontal";
  const xy = ([a, b]) => (horizontal ? [a - minA, b - minB] : [b - minB, a - minA]);
  const rect = (b) => {
    const [x, y] = xy([b.a, b.b]);
    return horizontal ? { x, y, width: b.sa, height: b.sb } : { x, y, width: b.sb, height: b.sa };
  };
  const pathOf = (commands) =>
    commands.map(([type, ...pts]) => `${type}${pts.map((p) => xy(p).map((v) => Math.round(v * 10) / 10).join(" ")).join(" ")}`).join(" ");
  return {
    orientation,
    scale,
    width: horizontal ? lengthA : lengthB,
    height: horizontal ? lengthB : lengthA,
    node,
    nodes: scene.nodes.filter((n) => boxes.has(n.id) && !n.cluster).map((n) => ({ ...n, ...rect(boxes.get(n.id)), cluster: containerOf(n) })),
    clusters: scene.nodes.filter((n) => n.cluster && frames.has(n.id)).map((n) => ({ id: n.id, name: n.name, ...rect(frames.get(n.id)) })),
    edges: drawn.map(({ link, commands, sampled }) => ({
      id: link.id,
      from: link.from,
      to: link.to,
      role: link.role,
      d: pathOf(commands),
      points: sampled.map(xy),
      failing: link.failing,
      passing: link.passing,
      tool: link.role === "tool",
    })),
  };
}
