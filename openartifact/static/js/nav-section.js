/* Runs while the sidebar is parsed, before first paint: the nav group opens with an animation only
 * when the user arrives from outside it. A classic script so that it needs no inline code. */
(function () {
  "use strict";
  var section = document.querySelector(".sidebar .nav-section");
  try {
    var key = window.OpenArtifact.keys.navSection;
    var was = sessionStorage.getItem(key) === "1";
    if (section && !was) section.classList.add("is-entering");
    sessionStorage.setItem(key, section ? "1" : "0");
  } catch { /* storage unavailable: no animation */ }
})();
