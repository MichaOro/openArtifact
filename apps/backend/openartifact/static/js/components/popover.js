/* Placement of a popover next to its anchor: clamped to the window, flipped upwards when there is
 * no room below. Shared by the pickers. */

const MARGIN = 8;

/**
 * @param {HTMLElement} el the visible popover
 * @param {(size: {width: number, height: number}) => {left: number, top: number, flipTop: number}} anchor
 *   where it would like to be, and where to go instead if it does not fit below
 */
export function placePopover(el, anchor) {
  const size = el.getBoundingClientRect();
  const { left, top, flipTop } = anchor(size);
  const y = top + size.height > window.innerHeight - MARGIN ? Math.max(MARGIN, flipTop) : top;
  const x = Math.min(Math.max(MARGIN, left), window.innerWidth - size.width - MARGIN);
  el.style.left = `${x}px`;
  el.style.top = `${y}px`;
}
