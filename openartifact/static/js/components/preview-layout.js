/* The layout of a graph preview (components/graph-preview.js), without a DOM: where each node of a small picture of a pipeline or an
 * action sits. It is derived from the STRUCTURE of the graph (what follows what), not from the coordinates of the editor, so it
 * can be drawn in a card as wide as it is and turned when it does not fit: a row of columns (horizontal) while that stays legible,
 * otherwise a column of rows (vertical). Tools that hang below an agent sit in the agent's column, linked by a dashed line.
 *
 *   const structure = structureOfGraph(detail, (kind) => isTool(kind));   // an action or a pipeline as the editor stores it
 *   const structure = structureOfChain(chain);                           // a pipeline from GET /api/pipelines/{id}/stages
 *   const picture = layoutPreview(structure, { available: 280 });        // {orientation, scale, width, height, nodes, links}
 */

const FAILING_PORTS = ["error", "fail", "else"]; // their connections are drawn as failures, like the canvas does

/** @typedef {{id: string, kind: string, name: string, tool?: boolean}} PreviewNode */

/**
 * @param {{nodes: {id: string, kind: string, name: string, y?: number}[], edges: {source_id: string, source_port: string, target_id: string, target_port: string}[]}} detail
 * @param {(kind: string) => boolean} isTool whether a kind of node is a tool (hangs below an agent)
 * @returns {{columns: PreviewNode[][], links: {from: string, to: string, dashed?: boolean, failing?: boolean}[]}}
 */
export function structureOfGraph(detail, isTool) {
  const nodes = detail.nodes ?? [];
  const edges = detail.edges ?? [];
  const tools = new Map(); // tool node id -> the node it hangs below
  const flow = [];
  for (const edge of edges) {
    const source = nodes.find((n) => n.id === edge.source_id);
    if (source && isTool(source.kind)) tools.set(source.id, edge.target_id);
    else flow.push(edge);
  }
  const mains = nodes.filter((n) => !isTool(n.kind));
  // the column of a node: the longest way to it from a node nothing leads to (a cycle is cut after as many steps as there are nodes)
  const layer = new Map(mains.map((n) => [n.id, 0]));
  for (let pass = 0; pass < mains.length; pass += 1) {
    let changed = false;
    for (const edge of flow) {
      if (!layer.has(edge.source_id) || !layer.has(edge.target_id)) continue;
      const wanted = layer.get(edge.source_id) + 1;
      if (wanted > layer.get(edge.target_id) && wanted < mains.length) {
        layer.set(edge.target_id, wanted);
        changed = true;
      }
    }
    if (!changed) break;
  }
  const count = Math.max(0, ...layer.values()) + 1;
  const columns = Array.from({ length: mains.length ? count : 0 }, () => []);
  for (const node of [...mains].sort((a, b) => (a.y ?? 0) - (b.y ?? 0))) columns[layer.get(node.id)].push({ id: node.id, kind: node.kind, name: node.name });
  for (const [id, parent] of tools) {
    const node = nodes.find((n) => n.id === id);
    const at = layer.get(parent);
    if (node && at !== undefined) columns[at].push({ id, kind: node.kind, name: node.name, tool: true });
  }
  const links = flow
    .filter((e) => layer.has(e.source_id) && layer.has(e.target_id))
    .map((e) => ({ from: e.source_id, to: e.target_id, failing: FAILING_PORTS.includes(e.source_port) }));
  for (const [id, parent] of tools) if (layer.has(parent)) links.push({ from: parent, to: id, dashed: true });
  return { columns: columns.filter((c) => c.length), links };
}

/**
 * A pipeline from its chain: the trigger, one column for every stage with its actions (or one node for a called pipeline), the end.
 * @param {{kind: string, name: string, id: string, actions?: {id: string, name: string}[]}[]} chain
 */
export function structureOfChain(chain) {
  const columns = [[{ id: "trigger", kind: "trigger", name: "Trigger" }]];
  for (const entry of chain) {
    if (entry.kind === "pipeline") columns.push([{ id: entry.id, kind: "pipeline", name: entry.name }]);
    else columns.push((entry.actions?.length ? entry.actions : [{ id: entry.id, name: entry.name }]).map((a) => ({ id: a.id, kind: "action", name: `${entry.name}: ${a.name}` })));
  }
  columns.push([{ id: "complete", kind: "complete", name: "Complete" }]);
  // a column leads to the next one: from its middle node to the next one's middle node
  const middle = (c) => c[Math.floor((c.length - 1) / 2)].id;
  const links = columns.slice(0, -1).map((c, i) => ({ from: middle(c), to: middle(columns[i + 1]) }));
  return { columns, links };
}

/**
 * @param {{columns: PreviewNode[][], links: object[]}} structure
 * @param {{available: number, node?: number, gap?: number, minScale?: number}} options `available`: the width the picture may take
 *   (px); `node`, `gap`: the size of a node and the space between two; `minScale`: how far a horizontal picture may shrink before
 *   it is turned
 * @returns {{orientation: "horizontal"|"vertical", scale: number, width: number, height: number, nodes: (PreviewNode & {x: number, y: number})[], links: object[]}}
 */
export function layoutPreview(structure, { available, node = 36, gap = 20, minScale = 0.6 } = {}) {
  const step = node + gap;
  const layers = structure.columns.length;
  const rows = Math.max(1, ...structure.columns.map((c) => c.length));
  const along = Math.max(0, layers * step - gap);
  const across = Math.max(0, rows * step - gap);
  let orientation = "horizontal";
  let scale = along > 0 ? Math.min(1, available / along) : 1;
  if (scale < minScale && layers > 1) {
    // too long for a row: stand the columns up, the first one on top (a picture that is still too wide is shrunk)
    orientation = "vertical";
    scale = across > 0 ? Math.min(1, available / across) : 1;
  }
  const placed = [];
  structure.columns.forEach((column, i) => {
    // a column with fewer nodes than the widest is centred on it
    const offset = ((rows - column.length) * step) / 2;
    column.forEach((n, j) => {
      const a = i * step;
      const b = offset + j * step;
      placed.push(orientation === "horizontal" ? { ...n, x: a, y: b } : { ...n, x: b, y: a });
    });
  });
  const width = orientation === "horizontal" ? along : across;
  const height = orientation === "horizontal" ? across : along;
  return { orientation, scale, width, height, nodes: placed, links: structure.links, node };
}
