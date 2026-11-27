/* What shows a mock outside its tab (ADR-087): the pin on the card of a node whose mock is switched on, and the pencil beside the close button of the
 * node's window that opens the Mock tab. Both are made here once and only toggled afterwards. */
import { icon } from "../components/icons.js";
import { CARD_ORDER, cardIcon, placeCardIcon, removeCardIcon } from "../components/card-icons.js";
import { t } from "../i18n.js";

/** The pin on a card: in the card's icon list while the node's mock is switched on (left of the guard's shield); it opens the window at the Mock tab. */
export function drawPin(el, active, onOpen) {
  if (!active) {
    removeCardIcon(el, "mock");
    return;
  }
  if (cardIcon(el, "mock")) return;
  const pin = document.createElement("button");
  pin.type = "button";
  pin.className = "icon-button icon-button--quiet icon-button--xs ge-node__pin"; // the look and the hover of the guard's shield
  pin.dataset.mockPin = "";
  pin.title = t("editor.mock.pin_tooltip");
  pin.setAttribute("aria-label", t("editor.mock.pin_tooltip"));
  pin.append(icon("pin"));
  pin.addEventListener("pointerdown", (event) => event.stopPropagation()); // a click on the pin does not start a drag of the card
  pin.addEventListener("dblclick", (event) => event.stopPropagation());
  pin.addEventListener("click", (event) => {
    event.stopPropagation();
    onOpen();
  });
  placeCardIcon(el, "mock", CARD_ORDER.mock, pin);
}

/** The pencil beside the close button of the window: shown for a node that takes a mock; `onOpen` opens the Mock tab. */
export function drawPencil(dialog, visible, onOpen) {
  let pencil = dialog.querySelector("[data-mock-pencil]");
  if (!pencil) {
    const close = dialog.querySelector(".modal__header [data-modal-close]");
    if (!close) return;
    pencil = document.createElement("button");
    pencil.type = "button";
    pencil.className = "icon-button icon-button--sm";
    pencil.dataset.mockPencil = "";
    pencil.title = t("editor.mock.open_tooltip");
    pencil.setAttribute("aria-label", t("editor.mock.open_tooltip"));
    pencil.append(icon("pencil"));
    close.before(pencil);
  }
  pencil.onclick = onOpen;
  pencil.hidden = !visible;
}
