import { WorkflowEditor } from "./editor.js";
import { loadNodeTypes } from "./node-types.js";

const root = document.querySelector("[data-workflow-id]");
loadNodeTypes()
  .then(() => new WorkflowEditor(root).load({ fit: true }))
  .catch(() => {
    const alert = root.querySelector("[data-editor-error]");
    alert.querySelector("[data-editor-error-text]").textContent = "The editor could not be loaded.";
    alert.hidden = false;
  });
