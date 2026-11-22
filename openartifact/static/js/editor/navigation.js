/* How the editor relates to the pages around it: the way back to the pipeline a definition was
 * opened from, and the memory of the last pipeline for the sidebar (read by main.js). */
import { KEYS, writeJson } from "../storage.js";
import { listGraphs } from "./api.js";

/** Offer "Back to <pipeline>" when an action definition was opened from a node of that pipeline. */
export async function setupBack(link, pipelinesPath, slug, nodeId) {
  if (!slug) return;
  link.href = `${pipelinesPath}/${encodeURIComponent(slug)}${nodeId ? `?select=${encodeURIComponent(nodeId)}` : ""}`;
  try {
    const pipeline = (await listGraphs("pipeline")).find((p) => p.slug === slug);
    link.textContent = pipeline ? `Back to ${pipeline.name}` : "Back to pipeline";
  } catch {
    link.textContent = "Back to pipeline";
  }
  link.hidden = false;
}

/** The sidebar's "Pipeline" reopens this pipeline with its action selected. */
export function rememberPipeline(slug, nodeId) {
  writeJson(KEYS.lastPipeline, { slug, node: nodeId });
}
