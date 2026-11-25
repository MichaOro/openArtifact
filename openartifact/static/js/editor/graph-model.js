/* The graph being edited: its nodes and edges (the Maps the canvas draws), and the calls that save
 * a change. It knows nothing about the page; the editor shows what goes wrong. */
import * as api from "./api.js";
import { typeOf } from "./node-types.js";

export class GraphModel {
  /** @param {"pipeline"|"action"} kind @param {string} id */
  constructor(kind, id) {
    this.kind = kind;
    this.id = id;
    this.graph = null;
    this.nodes = new Map();
    this.edges = new Map();
    /** Called after every change the server accepted (a node or a connection came, changed or went): the editor then asks where the
     * draft stands against the published version. */
    this.onChange = null;
  }

  #saved = async (call) => {
    const result = await call;
    this.onChange?.();
    return result;
  };

  /** An action definition: its trigger and output are fixed. */
  get isAction() {
    return this.kind === "action";
  }

  /** Replace everything with what the server has. */
  async load() {
    const loaded = await api.loadGraph(this.kind, this.id);
    this.graph = loaded.graph;
    this.nodes.clear();
    this.edges.clear();
    for (const node of loaded.nodes) this.nodes.set(node.id, node);
    for (const edge of loaded.edges) this.edges.set(edge.id, edge);
  }

  count(kind) {
    return [...this.nodes.values()].filter((n) => n.kind === kind).length;
  }

  /** Fixed kinds (trigger, complete, output) come with the graph; the last one of each stays. */
  isFixed(node) {
    return typeOf(node).fixed && this.count(node.kind) <= 1;
  }

  /** Forget the connections at ports the node no longer shows (e.g. no On Fail). */
  dropHiddenEdges(node) {
    const type = typeOf(node);
    for (const [id, edge] of this.edges) {
      const port = edge.source_id === node.id ? edge.source_port : edge.target_id === node.id ? edge.target_port : null;
      if (port && !type.isVisible(node, port)) this.edges.delete(id);
    }
  }

  /** The connection that leaves this port, if there is one (a port has at most one). */
  edgeFrom(nodeId, port) {
    return [...this.edges.values()].find((e) => e.source_id === nodeId && e.source_port === port);
  }

  // ── saving ──────────────────────────────────────────────────────

  rename = (name) => api.renameGraph(this.kind, this.id, name);
  addNode = (fields) => this.#saved(api.addNode(this.kind, this.id, fields));
  updateNode = (nodeId, fields) => this.#saved(api.updateNode(this.kind, this.id, nodeId, fields));
  deleteNode = (nodeId) => this.#saved(api.deleteNode(this.kind, this.id, nodeId));
  connect = (edge) => this.#saved(api.connect(this.kind, this.id, edge));
  restyle = (edgeId, style) => api.restyleEdge(this.kind, this.id, edgeId, style);
  disconnect = (edgeId) => this.#saved(api.disconnect(this.kind, this.id, edgeId));
}
