/* UI wiring: binds toggles to the central state manager and keeps ARIA in sync. */
(function () {
  "use strict";
  var OA = window.OpenArtifact;
  if (!OA) return;

  var themeBtn = document.querySelector("[data-theme-toggle]");
  var sidebarBtn = document.querySelector("[data-sidebar-toggle]");

  function syncTheme() {
    if (!themeBtn) return;
    var dark = OA.Theme.current() === "dark";
    themeBtn.setAttribute("aria-pressed", String(dark));
    themeBtn.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
  }
  function syncSidebar() {
    if (!sidebarBtn) return;
    var expanded = OA.Sidebar.current() !== "collapsed";
    sidebarBtn.setAttribute("aria-expanded", String(expanded));
    sidebarBtn.setAttribute("aria-label", expanded ? "Collapse sidebar" : "Expand sidebar");
  }

  if (themeBtn) themeBtn.addEventListener("click", OA.Theme.toggle);
  if (sidebarBtn) sidebarBtn.addEventListener("click", OA.Sidebar.toggle);
  document.addEventListener("themechange", syncTheme);
  document.addEventListener("sidebarchange", syncSidebar);
  syncTheme();
  syncSidebar();
})();
