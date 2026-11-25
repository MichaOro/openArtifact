/* A small picture of a pipeline or an action: one coloured symbol for every node, the links between them, nothing else. The name of a
 * node is its tooltip and its accessible name (the picture is a list of them, not text). The layout comes from the structure of the
 * graph (components/preview-layout.js): a row while it stays legible, a column when it does not, tools below their agent with a
 * dashed line. The colours are the tokens of the node kinds (the manifests' `ui.color`), like the canvas of the editor.
 *
 *   const preview = new GraphPreview(host, { structure, typeOf });   // draws at once and again when `host` changes its width
 *   lazyPreview(host, () => loadStructure(item));                    // draws only when `host` comes into view (cards of a long list)
 *
 * It is read-only: a click on it is a click on whatever holds it (the card). */
import { icon } from "./icons.js";
import { layoutPreview } from "./preview-layout.js";
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

export class GraphPreview {
  /**
   * @param {HTMLElement} host the box the picture fills (its width decides the orientation)
   * @param {{structure: {columns: object[][], links: object[]}, typeOf?: (kind: string) => object|undefined, node?: number}} options
   *   `node`: the size of a symbol in px
   */
  constructor(host, { structure, typeOf = null, node = 36 }) {
    this.host = host;
    this.structure = structure;
    this.typeOf = typeOf;
    this.node = node;
    this.width = 0;
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

  render() {
    const picture = layoutPreview(this.structure, { available: this.width || 280, node: this.node });
    const stage = make("div", "gp__stage");
    stage.dataset.orientation = picture.orientation;
    stage.style.width = `${picture.width}px`;
    stage.style.height = `${picture.height}px`;
    stage.style.transform = `scale(${picture.scale})`;
    const byId = new Map(picture.nodes.map((n) => [n.id, n]));
    const links = document.createElementNS(SVG, "svg");
    links.setAttribute("class", "gp__links");
    links.setAttribute("viewBox", `0 0 ${picture.width} ${picture.height}`);
    links.setAttribute("aria-hidden", "true");
    const half = picture.node / 2;
    for (const link of picture.links) {
      const a = byId.get(link.from);
      const b = byId.get(link.to);
      if (!a || !b) continue;
      const horizontal = picture.orientation === "horizontal" && !link.dashed;
      const [x1, y1, x2, y2] = horizontal ? [a.x + picture.node, a.y + half, b.x, b.y + half] : [a.x + half, a.y + picture.node, b.x + half, b.y];
      const path = document.createElementNS(SVG, "path");
      const mid = horizontal ? (x1 + x2) / 2 : null;
      path.setAttribute("d", horizontal ? `M${x1} ${y1} C${mid} ${y1} ${mid} ${y2} ${x2} ${y2}` : `M${x1} ${y1} L${x2} ${y2}`);
      path.setAttribute("class", `gp__link${link.dashed ? " is-tool" : ""}${link.failing ? " is-failing" : ""}`);
      links.append(path);
    }
    stage.append(links);
    const names = [];
    for (const n of picture.nodes) {
      const look = lookOf(n.kind, this.typeOf);
      const symbol = make("span", `gp-node${n.tool ? " is-tool" : ""}`);
      symbol.style.left = `${n.x}px`;
      symbol.style.top = `${n.y}px`;
      symbol.style.width = symbol.style.height = `${picture.node}px`;
      symbol.style.setProperty("--node-color", `var(--node-${look.color})`);
      symbol.title = n.name || look.label;
      symbol.append(icon(look.icon));
      stage.append(symbol);
      names.push(n.name || look.label);
    }
    // the picture is one image with the names as its description; the symbols' tooltips are for the pointer
    this.host.setAttribute("role", "img");
    this.host.setAttribute("aria-label", `${t("components.graph_preview.graph")}: ${names.join(", ")}`);
    this.host.style.height = `${Math.ceil(picture.height * picture.scale)}px`;
    stage.style.left = `${Math.max(0, (this.width - picture.width * picture.scale) / 2)}px`;
    this.host.replaceChildren(stage);
  }

  destroy() {
    this.observer.disconnect();
  }
}

/** Draws the picture of `host` when it comes into view: `load()` resolves to a structure (or null: nothing to draw). */
export function lazyPreview(host, load, options = {}) {
  let started = false;
  const start = async () => {
    if (started) return;
    started = true;
    try {
      const structure = await load();
      if (structure) host.preview = new GraphPreview(host, { structure, ...options });
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
