/* Entry point of the graph editor page: loads the node kinds, then the graph. */
import { AlertBar } from "../components/alert-bar.js";
import { GraphEditor } from "./editor.js";
import { loadNodeTypes } from "./node-types.js";

const root = document.querySelector("[data-graph-id]");
loadNodeTypes()
  .then(() => new GraphEditor(root).load({ fit: true }))
  .catch(() => new AlertBar(root.querySelector("[data-alert]")).show("The editor could not be loaded."));
