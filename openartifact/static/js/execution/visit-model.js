/* What a flow response says, as questions the viewer asks: which visit is shown, what was walked in
 * it and how, which visits lie below a node, which other passes there are, where it sits in the
 * chain of visits. Pure logic over the plain response (no DOM), so the view and the panel only draw.
 *
 * A "visit" is one pass of the execution through a graph (a pipeline or an action definition); a
 * visit is entered from a node of its parent visit's graph. Node states: pass, fail, running,
 * stopped (the execution was stopped there), skipped (in front of where it started) or not-run. */

/** What a node is called (a linked node carries the name of what it links to, as in the editor). */
export const nameOf = (node) => node.definition_name ?? node.name;

const FINISHED = { pass: "pass", fail: "fail", running: "running" };
const outcomeState = (outcome) => FINISHED[outcome] ?? "stopped";

export class FlowModel {
  /** @param {object} flow the response of GET .../executions/{id}/flow */
  constructor(flow) {
    this.flow = flow;
    this.visits = flow.visits;
    this.root = flow.visits[0] ?? null;
    this.steps = flow.steps;
  }

  get execution() {
    return this.flow.execution;
  }

  visit(index) {
    return this.visits.find((v) => v.index === index) ?? null;
  }

  graph(visit) {
    return this.flow.graphs[visit.graph_id];
  }

  /** The visits entered from this visit, in the order they began. */
  children(visit) {
    return this.visits.filter((v) => v.parent === visit.index);
  }

  /** The visits entered from one node of this visit (more than one when the node ran again). */
  childrenVia(visit, nodeId) {
    return this.children(visit).filter((v) => v.entered_via?.node_id === nodeId);
  }

  /** Every pass through the same node of the same parent visit (this one included), the way a
   * loop or a retry runs an action again. One element: it ran once. */
  passes(visit) {
    if (visit.parent === null) return [visit];
    return this.visits.filter((v) => v.parent === visit.parent && v.graph_id === visit.graph_id && v.entered_via?.node_id === visit.entered_via?.node_id);
  }

  /** The visits from the root down to this one. */
  chain(visit) {
    const path = [];
    for (let at = visit; at; at = at.parent === null ? null : this.visit(at.parent)) path.unshift(at);
    return path;
  }

  /** The node of the parent graph this visit was entered from. */
  enteredFrom(visit) {
    if (!visit.entered_via) return null;
    const parent = this.visit(visit.parent);
    return parent ? this.graph(parent).nodes.find((n) => n.id === visit.entered_via.node_id) ?? null : null;
  }

  /** The stage of the entry node, e.g. "Stage 1" for an action of it (null for a called pipeline). */
  stageOf(node, graph) {
    return node?.stage_id ? graph.nodes.find((n) => n.id === node.stage_id) ?? null : null;
  }

  /** The steps recorded inside an action visit, in order (a pipeline visit has none of its own). */
  stepsOf(visit) {
    if (visit.first_seq === null || this.graph(visit).kind !== "action") return [];
    const ids = new Set(this.graph(visit).nodes.map((n) => n.id));
    return this.steps.filter((s) => s.seq >= visit.first_seq && s.seq <= visit.last_seq && ids.has(s.node_id));
  }

  /**
   * What was walked in a visit: `entries` (the nodes in the order reached, each with its step or its
   * child visits), `states` (node id -> state, for every node of the graph) and `edgeOrder`
   * (edge id -> 1, 2, ... in the order gone along).
   */
  describe(visit) {
    const graph = this.graph(visit);
    const byId = new Map(graph.nodes.map((n) => [n.id, n]));
    const steps = [...this.stepsOf(visit)];
    const last = visit.nodes.length - 1;
    const unfinished = visit.outcome !== "pass" ? outcomeState(visit.outcome) : null;
    const tail = byId.get(visit.nodes[last]);
    const tailStage = tail?.kind === "stage" ? tail.id : tail?.stage_id ?? null;

    const entries = visit.nodes.map((id, position) => {
      const node = byId.get(id);
      const takes = steps.findIndex((s) => s.node_id === id);
      const step = takes >= 0 ? steps.splice(takes, 1)[0] : null;
      const children = this.childrenVia(visit, id);
      let state = "pass";
      if (step) state = step.outcome;
      else if (children.length) state = outcomeState(children[children.length - 1].outcome);
      else if (unfinished && position === last) state = unfinished;
      else if (unfinished && node?.kind === "stage" && id === tailStage) state = unfinished; // the stage holding where it ended
      return { position, id, node, step, children, state };
    });
    const states = new Map();
    const skipped = new Set(visit.skipped_nodes);
    for (const node of graph.nodes) states.set(node.id, { state: skipped.has(node.id) ? "skipped" : "not-run", passes: 0 });
    for (const entry of entries) {
      const known = states.get(entry.id);
      states.set(entry.id, { state: entry.state, passes: Math.max(known?.passes ?? 0, entry.children.length), step: entry.step ?? known?.step ?? null });
    }
    const edgeOrder = new Map(visit.edges.map((e, i) => [e.id, i + 1]));
    return { entries, states, edgeOrder };
  }

  /** A short description of what the visit is: its graph's name and, for an action, where it sits. */
  titleOf(visit) {
    const graph = this.graph(visit);
    const node = this.enteredFrom(visit);
    const stage = node ? this.stageOf(node, this.graph(this.visit(visit.parent))) : null;
    return { name: node ? nameOf(node) : graph.name, stage: stage ? nameOf(stage) : null, graph };
  }
}
