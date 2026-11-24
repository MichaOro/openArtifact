/* The structure of a node kind's settings window for the arrange view (ADR-063): the kind's two sides with their settings, and
 * the blocks the kind draws itself and that therefore stay where they are. */
import { nodeStructure } from "../components/layout-model.js";
import { t } from "../i18n.js";

/** Keys a kind draws in its own way (not as entries) and the names of those blocks; today the Agent node's choice of agent and inputs. */
const OWN_BLOCKS = {
  agent: { skip: ["agent_id", "inputs"], fixed: () => [t("components.layout.fixed_agent")] },
};

/** @param {object} type the view of a node kind (typeOf(node)) */
export function nodeWindowStructure(type) {
  const own = OWN_BLOCKS[type.kind];
  return nodeStructure(type, {
    titles: { definition: t("editor.node_types.definition"), behaviour: t("editor.settings_layout.behaviour") },
    skip: own?.skip ?? [],
    fixed: own?.fixed() ?? [],
  });
}
