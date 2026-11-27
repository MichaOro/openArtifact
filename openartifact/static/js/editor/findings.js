/* The question before a draft is published with findings (ADR-082): what the confirmation window says. Pure data, so a test can read it. */
import { t } from "../i18n.js";

/** Errors first, each by the place it is about. */
export function findingItems(findings) {
  const order = { error: 0, warning: 1 };
  return [...findings]
    .sort((a, b) => order[a.level] - order[b.level] || a.node_name.localeCompare(b.node_name))
    .map((f) => ({
      level: f.level,
      mark: f.level === "error" ? t("graph_versions.finding_error") : t("graph_versions.finding_warning"),
      label: f.node_name,
      text: f.message,
    }));
}

/**
 * The options of the confirmation window for these findings. A publish over errors is asked in red (the owner knows what he does:
 * the window only makes sure he has seen them); one over warnings only is the accent colour.
 * @param {{level: string, node_name: string, message: string}[]} findings
 */
export function findingsConfirm(findings) {
  const errors = findings.filter((f) => f.level === "error").length;
  const warnings = findings.length - errors;
  return {
    title: t("graph_versions.findings_title"),
    message: t("graph_versions.findings_message", { errors, warnings }),
    items: findingItems(findings),
    confirmLabel: t("graph_versions.publish_anyway"),
    tone: errors ? "danger" : "primary",
  };
}
