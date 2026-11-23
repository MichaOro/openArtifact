/* UI wiring of the shell: binds the toggles to the theme and sidebar state (theme.js) and keeps
 * their ARIA in sync. */
import { KEYS, readJson } from "./storage.js";
import { t } from "./i18n.js";

const { Theme, Sidebar } = window.OpenArtifact;
const themeButton = document.querySelector("[data-theme-toggle]");
const sidebarButton = document.querySelector("[data-sidebar-toggle]");

function syncTheme() {
  if (!themeButton) return;
  const dark = Theme.current() === "dark";
  themeButton.setAttribute("aria-pressed", String(dark));
  themeButton.setAttribute("aria-label", dark ? t("main.switch_light_mode") : t("main.switch_dark_mode"));
}

function syncSidebar() {
  if (!sidebarButton) return;
  const expanded = Sidebar.current() !== "collapsed";
  sidebarButton.setAttribute("aria-expanded", String(expanded));
  sidebarButton.setAttribute("aria-label", expanded ? t("sidebar.collapse_sidebar") : t("main.expand_sidebar"));
}

themeButton?.addEventListener("click", Theme.toggle);
sidebarButton?.addEventListener("click", Sidebar.toggle);
// Narrow: the expanded sidebar is an overlay, so tapping outside it (or Escape) closes it.
document.addEventListener("pointerdown", (event) => {
  if (Sidebar.isNarrow() && !event.target.closest("#sidebar")) Sidebar.collapseIfNarrow();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") Sidebar.collapseIfNarrow();
});

// "Pipeline" reopens the pipeline (and the action) the user was last working on; the editor writes this.
const last = readJson(KEYS.lastPipeline);
if (last?.slug && window.location.pathname !== "/pipelines") {
  const href = `/pipelines/${encodeURIComponent(last.slug)}${last.node ? `?select=${encodeURIComponent(last.node)}` : ""}`;
  document.querySelectorAll('.sidebar a[href="/pipelines"]').forEach((a) => a.setAttribute("href", href));
}
document.addEventListener("themechange", syncTheme);
document.addEventListener("sidebarchange", syncSidebar);
syncTheme();
syncSidebar();
