/* A line released on the empty canvas opens the "+" menu at the pointer (the same component, add-menu.js, in its anchored
 * mode) with the kinds that can connect to the dragged port. This file is the glue: it asks connect-plan.js what fits,
 * opens the menu and hands the choice to the editor, which makes the node and the connection. */
import { addableIn, typeOf } from "./node-types.js";
import { displayName } from "./geometry.js";
import { candidates, kindsFor } from "./connect-plan.js";
import { t } from "../i18n.js";

export class ConnectMenu {
  /**
   * @param {object} options
   * @param {{openFrom: Function}} options.addMenu the editor's "+" menu (add-menu.js)
   * @param {"pipeline"|"action"} options.scope
   * @param {Map<string, object>} options.nodes
   * @param {(choice: {origin: object, kind: string, stage: object|null}) => void} options.onChoose
   */
  constructor({ addMenu, scope, nodes, onChoose, purpose = () => null }) {
    this.purpose = purpose;
    this.addMenu = addMenu;
    this.scope = scope;
    this.nodes = nodes;
    this.onChoose = onChoose;
  }

  /** @param {{node: object, port: string, direction: string, slot: number, point: {x: number, y: number}, world: {x: number, y: number}, stageId: string|null}} origin */
  open(origin) {
    const stage = origin.stageId ? this.nodes.get(origin.stageId) ?? null : null;
    const offered = candidates(origin, kindsFor(this.scope, stage, addableIn(this.scope, this.purpose())), stage);
    const port = typeOf(origin.node).portLabel(origin.port, origin.node);
    this.addMenu.openFrom(origin.point, {
      types: offered,
      header: t("editor.connect_menu.connects_from", { node: displayName(origin.node), port }),
      emptyText: t("editor.connect_menu.nothing_fits"),
      onPick: (kind) => this.onChoose({ origin, kind, stage }),
    });
  }
}
