/* A small picture of a pipeline or an action: one coloured symbol for every node, a frame around the actions of each stage, and every
 * connection of the graph (a pass is green, an error red and dashed, a tool dashed grey). The name of a node is its tooltip and its
 * accessible name (the picture is a list of them, not text). The layout comes from the structure of the graph
 * (components/preview-layout.js): layers in a row while that stays legible, one below the other when it does not. The colours are the
 * tokens of the node kinds (the manifests' `ui.color`) and of the lines of the editor.
 *
 *   const preview = new GraphPreview(host, { scene, typeOf });   // scene: sceneOfGraph(detail, isTool); draws at once and again when `host` changes its width
 *   lazyPreview(host, () => loadScene(item));                    // draws only when `host` comes into view (not used since the cards have no picture)
 *
 * It is read-only: a click on it is a click on whatever holds it (the card). */
import { icon } from "./icons.js";
import { layoutScene } from "./preview-layout.js";
import { t } from "../i18n.js";

const SVG = "http://www.w3.org/2000/svg";

function make(tag, className = "") {
  const el = document.createElement(tag);
  if (className) el.className = className;
  return el;
}

/** What a kind of node looks like: its icon, the token of its colour and its name. */
export function lookOf(kind, typeOf) {
  const type = typeOf?.(kind);
  return { icon: type?.constructor?.icon ?? type?.menu_icon ?? "card", color: type?.ui?.color ?? kind, label: type?.label ?? kind };
}

let previews = 0; // the markers of a picture have an id of their own: several pictures can be on a page

export class GraphPreview {
  /**
   * @param {HTMLElement} host the box the picture fills (its width decides the orientation)
   * @param {{scene: {nodes: object[], edges: object[]}, typeOf?: (kind: string) => object|undefined, node?: number}} options
   *   `scene`: from `sceneOfGraph()` (components/preview-layout.js); `node`: the size of a symbol in px
   */
  constructor(host, { scene, typeOf = null, node = 36 }) {
    this.host = host;
    this.scene = scene;
    this.typeOf = typeOf;
    this.node = node;
    this.width = 0;
    this.id = `gp-${(previews += 1)}`;
    host.classList.add("gp");
    this.observer = new ResizeObserver(() => this.#fit());
    this.observer.observe(host);
    this.#fit();
  }

  #fit() {
    const available = this.host.clientWidth;
    if (!available || available === this.width) return;
    this.width = available;
    this.render();
  }

  /** The arrow heads: one per kind of line, filled by a class (the tokens of the lines). */
  #markers() {
    const defs = document.createElementNS(SVG, "defs");
    for (const kind of ["pass", "failing", "plain"]) {
      const marker = document.createElementNS(SVG, "marker");
      marker.setAttribute("id", `${this.id}-${kind}`);
      marker.setAttribute("viewBox", "0 0 6 6");
      marker.setAttribute("refX", "5");
      marker.setAttribute("refY", "3");
      marker.setAttribute("markerWidth", "6");
      marker.setAttribute("markerHeight", "6");
      marker.setAttribute("markerUnits", "userSpaceOnUse");
      marker.setAttribute("orient", "auto");
      const head = document.createElementNS(SVG, "path");
      head.setAttribute("d", "M0 0 L6 3 L0 6 z");
      head.setAttribute("class", `gp__arrow gp__arrow--${kind}`);
      marker.append(head);
      defs.append(marker);
    }
    return defs;
  }

  render() {
    const picture = layoutScene(this.scene, { available: this.width || 280, node: this.node });
    const stage = make("div", "gp__stage");
    stage.dataset.orientation = picture.orientation;
    stage.style.width = `${picture.width}px`;
    stage.style.height = `${picture.height}px`;
    stage.style.transform = `scale(${picture.scale})`;
    // the frames of the stages first: behind the lines and the symbols
    for (const c of picture.clusters) {
      const frame = make("div", "gp-cluster");
      frame.dataset.clusterId = c.id;
      frame.style.cssText = `left:${c.x}px;top:${c.y}px;width:${c.width}px;height:${c.height}px`;
      frame.title = c.name;
      frame.append(icon("layers"));
      stage.append(frame);
    }
    const links = document.createElementNS(SVG, "svg");
    links.setAttribute("class", "gp__links");
    links.setAttribute("viewBox", `0 0 ${picture.width} ${picture.height}`);
    links.setAttribute("aria-hidden", "true");
    links.append(this.#markers());
    for (const edge of picture.edges) {
      const kind = edge.failing ? "failing" : edge.passing ? "pass" : "plain";
      const path = document.createElementNS(SVG, "path");
      path.setAttribute("d", edge.d);
      path.setAttribute("class", `gp__link${edge.tool ? " is-tool" : ""}${edge.failing ? " is-failing" : ""}${edge.passing ? " is-passing" : ""}`);
      path.dataset.edge = edge.id;
      path.dataset.role = edge.role;
      path.dataset.from = edge.from;
      path.dataset.to = edge.to;
      if (!edge.tool) path.setAttribute("marker-end", `url(#${this.id}-${kind})`);
      links.append(path);
    }
    stage.append(links);
    const names = new Map(); // the stage frames hold their actions' names in the description
    for (const n of picture.nodes) {
      const look = lookOf(n.kind, this.typeOf);
      const symbol = make("span", `gp-node${n.tool ? " is-tool" : ""}`);
      symbol.style.left = `${n.x}px`;
      symbol.style.top = `${n.y}px`;
      symbol.style.width = symbol.style.height = `${picture.node}px`;
      symbol.style.setProperty("--node-color", `var(--node-${look.color})`);
      symbol.dataset.nodeId = n.id;
      if (n.cluster) symbol.dataset.cluster = n.cluster;
      const name = n.name || look.label;
      symbol.title = name;
      symbol.append(icon(look.icon));
      stage.append(symbol);
      const key = n.cluster ?? "";
      names.set(key, [...(names.get(key) ?? []), name]);
    }
    const parts = [...(names.get("") ?? [])];
    for (const c of picture.clusters) parts.push(`${c.name} (${(names.get(c.id) ?? []).join(", ")})`);
    // the picture is one image with the names as its description; the symbols' tooltips are for the pointer
    this.host.setAttribute("role", "img");
    this.host.setAttribute("aria-label", `${t("components.graph_preview.graph")}: ${parts.join(", ")}`);
    this.host.style.height = `${Math.ceil(picture.height * picture.scale)}px`;
    stage.style.left = `${Math.max(0, (this.width - picture.width * picture.scale) / 2)}px`;
    this.host.replaceChildren(stage);
  }

  destroy() {
    this.observer.disconnect();
  }
}

/** Draws the picture of `host` when it comes into view: `load()` resolves to a scene (or null: nothing to draw). */
export function lazyPreview(host, load, options = {}) {
  let started = false;
  const start = async () => {
    if (started) return;
    started = true;
    try {
      const scene = await load();
      if (scene) host.preview = new GraphPreview(host, { scene, ...options });
    } catch {
      host.classList.add("is-failed");
    }
  };
  if (typeof IntersectionObserver === "undefined") {
    start();
    return;
  }
  const observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        observer.disconnect();
        start();
      }
    },
    { rootMargin: "120px" },
  );
  observer.observe(host);
}
