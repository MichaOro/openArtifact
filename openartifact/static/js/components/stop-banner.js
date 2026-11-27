/* The banner at the top centre of every page while STOP is on (ADR-076): "Pipeline processing is stopped", a second line, and
 * a button that switches STOP off when the switch is offered. The markup is in templates/base.html; the state comes from
 * stop-state.js (read on load, then the event stream). */
import { t } from "../i18n.js";
import { followStop, setStop, subscribeStop } from "./stop-state.js";

/** @param {HTMLElement} root the `[data-stop-banner]` element */
export function mountStopBanner(root) {
  const off = root.querySelector("[data-stop-off]");
  const problem = root.querySelector("[data-stop-problem]");
  off.addEventListener("click", async () => {
    off.setAttribute("aria-busy", "true");
    problem.hidden = true;
    try {
      await setStop(false);
    } catch (error) {
      problem.textContent = error.message || t("stop.could_not_change");
      problem.hidden = false;
    } finally {
      off.removeAttribute("aria-busy");
    }
  });
  subscribeStop((state) => {
    root.hidden = !state.active;
    off.hidden = !state.available;
    if (!state.active) problem.hidden = true;
    document.documentElement.toggleAttribute("data-stopped", state.active);
  });
  followStop();
}

const root = typeof document === "undefined" ? null : document.querySelector("[data-stop-banner]");
if (root) mountStopBanner(root);
