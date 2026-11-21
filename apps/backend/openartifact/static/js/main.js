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
  // Narrow: the expanded sidebar is an overlay, so tapping outside it (or Escape) closes it.
  document.addEventListener("pointerdown", function (e) {
    if (OA.Sidebar.isNarrow() && !e.target.closest("#sidebar")) OA.Sidebar.collapseIfNarrow();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") OA.Sidebar.collapseIfNarrow();
  });
  // "Stages" reopens the stage (and the action) the user was last working on; editor.js writes this.
  try {
    var last = JSON.parse(localStorage.getItem("oa-last-stage"));
    if (last && last.workflow && window.location.pathname !== "/workflows") {
      var href = "/workflows/" + encodeURIComponent(last.workflow) + (last.node ? "?select=" + encodeURIComponent(last.node) : "");
      document.querySelectorAll('.sidebar a[href="/workflows"]').forEach(function (a) { a.setAttribute("href", href); });
    }
  } catch (e) { /* no memory: the link shows the list */ }
  document.addEventListener("themechange", syncTheme);
  document.addEventListener("sidebarchange", syncSidebar);
  syncTheme();
  syncSidebar();
})();
