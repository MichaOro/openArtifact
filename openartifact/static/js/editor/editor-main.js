/* Entry point of the graph editor page: loads the node kinds, then the graph. */
import { AlertBar } from "../components/alert-bar.js";
import { GraphEditor } from "./editor.js";
import { loadAgentNames } from "./agent-inspector.js";
import { loadNodeTypes } from "./node-types.js";
import { t } from "../i18n.js";

const root = document.querySelector("[data-graph-id]");
// the names of the agents are for the cards of agent nodes: the editor works without them
Promise.all([loadNodeTypes(), loadAgentNames()])
  .then(() => new GraphEditor(root).load({ fit: true }))
  .catch(() => new AlertBar(root.querySelector("[data-alert]")).show(t("editor.editor_main.editor_could_not_be_loaded")));
