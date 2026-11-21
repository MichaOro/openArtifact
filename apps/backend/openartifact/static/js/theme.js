/* Central theme + sidebar state manager.
 * Loaded synchronously in <head> so the correct state is applied before first paint. */
(function () {
  "use strict";

  var root = document.documentElement;
  var THEME_KEY = "openartifact-theme";
  var SIDEBAR_KEY = "openartifact-sidebar";
  var media = window.matchMedia("(prefers-color-scheme: dark)");
  var narrowQuery = window.matchMedia("(max-width: 640px), (max-height: 500px) and (max-width: 960px)");

  function read(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function write(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* storage unavailable */ }
  }

  var Theme = {
    stored: function () {
      var v = read(THEME_KEY);
      return v === "light" || v === "dark" ? v : null;
    },
    current: function () { return root.getAttribute("data-theme"); },
    apply: function (theme) {
      root.setAttribute("data-theme", theme);
      document.dispatchEvent(new CustomEvent("themechange", { detail: { theme: theme } }));
    },
    set: function (theme) {
      write(THEME_KEY, theme);
      // Enables the token transition (see tokens.css) only around a user-triggered switch.
      root.classList.add("theme-animating");
      Theme.apply(theme);
      window.clearTimeout(Theme._timer);
      Theme._timer = window.setTimeout(function () { root.classList.remove("theme-animating"); }, 320);
    },
    toggle: function () { Theme.set(Theme.current() === "dark" ? "light" : "dark"); },
    init: function () {
      Theme.apply(Theme.stored() || (media.matches ? "dark" : "light"));
      // Follow OS changes only while the user has not made an explicit choice.
      var onChange = function (e) { if (!Theme.stored()) Theme.apply(e.matches ? "dark" : "light"); };
      if (media.addEventListener) media.addEventListener("change", onChange);
    }
  };

  var Sidebar = {
    stored: function () {
      var v = read(SIDEBAR_KEY);
      return v === "collapsed" || v === "expanded" ? v : null;
    },
    current: function () { return root.getAttribute("data-sidebar"); },
    apply: function (state) {
      root.setAttribute("data-sidebar", state);
      document.dispatchEvent(new CustomEvent("sidebarchange", { detail: { state: state } }));
    },
    /* Narrow = portrait phones and phones on their side. Keep in sync with the CSS media
       query that turns the expanded sidebar into an overlay (components.css). */
    isNarrow: function () { return narrowQuery.matches; },
    /* On narrow screens the sidebar is only ever expanded temporarily (it overlays the board),
       so that state is NOT stored and the desktop preference survives. */
    toggle: function () {
      var next = Sidebar.current() === "collapsed" ? "expanded" : "collapsed";
      if (!Sidebar.isNarrow()) write(SIDEBAR_KEY, next);
      Sidebar.apply(next);
    },
    collapseIfNarrow: function () {
      if (Sidebar.isNarrow() && Sidebar.current() !== "collapsed") Sidebar.apply("collapsed");
    },
    desktopState: function () { return Sidebar.stored() || "expanded"; },
    init: function () {
      Sidebar.apply(Sidebar.isNarrow() ? "collapsed" : Sidebar.desktopState());
      // Entering a narrow layout always collapses; leaving it restores the desktop preference.
      var onChange = function (e) { Sidebar.apply(e.matches ? "collapsed" : Sidebar.desktopState()); };
      if (narrowQuery.addEventListener) narrowQuery.addEventListener("change", onChange);
    }
  };

  Theme.init();
  Sidebar.init();
  window.OpenArtifact = { Theme: Theme, Sidebar: Sidebar };
})();
