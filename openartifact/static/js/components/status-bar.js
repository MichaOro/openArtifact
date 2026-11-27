/* The status bar in the corner of the editor's canvas: ONE small list of entries (the eye of the observe mode, the hand of an ended observation,
 * the shield of the guards, the "+" menu). A variant of the flexible icon list (icon-list.js): the entries stay in the page and are hidden while
 * inactive, the "+" is always the last, at the right edge. More entries are one line of `add` (and its key in `STATUS_BAR`). */
import { IconList } from "./icon-list.js";
import { LAST, defineVariant } from "./icon-list-model.js";

/** What the canvas corner allows and where each entry stands, left to right. */
export const STATUS_BAR = defineVariant({
  name: "status bar",
  allow: ["ended", "observe", "guard", "add"],
  order: { ended: 5, observe: 10, guard: 20, add: LAST },
  inactive: "hide",
  attrs: { key: "statusEntry" },
  cssOrder: true,
  buttonClass: "icon-button status-bar__entry",
});

export class StatusBar extends IconList {
  /** @param {HTMLElement} row the element holding the entries */
  constructor(row) {
    super(row, STATUS_BAR);
  }
}
