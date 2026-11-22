/* The breadcrumb of the flow page: the chain of visits from the pipeline down to the one shown,
 * e.g. "Echo flow > Stage 1 > Do code". The last item is the current place; the others go up to it. */

export class Breadcrumb {
  /**
   * @param {HTMLElement} root a <nav> with an <ol>
   * @param {(visit: object) => void} onGo
   */
  constructor(root, onGo) {
    this.list = root.querySelector("ol");
    this.onGo = onGo;
  }

  /** @param {{visit: object, href: string, name: string, stage: string|null, pass: string|null}[]} items root first */
  render(items) {
    this.list.replaceChildren(
      ...items.map((item, i) => {
        const li = document.createElement("li");
        li.className = "ef-crumb";
        const label = document.createElement("span");
        label.className = "ef-crumb__label";
        if (item.stage) {
          const stage = document.createElement("span");
          stage.className = "ef-crumb__stage";
          stage.textContent = `${item.stage} › `;
          label.append(stage);
        }
        label.append(item.name);
        if (item.pass) label.append(` (${item.pass})`);
        if (i === items.length - 1) {
          li.setAttribute("aria-current", "location");
          li.append(label);
        } else {
          const link = document.createElement("a");
          link.href = item.href;
          link.className = "ef-crumb__link";
          link.append(label);
          link.addEventListener("click", (event) => {
            if (event.ctrlKey || event.metaKey || event.shiftKey) return;
            event.preventDefault();
            this.onGo(item.visit);
          });
          li.append(link);
        }
        return li;
      }),
    );
  }
}
