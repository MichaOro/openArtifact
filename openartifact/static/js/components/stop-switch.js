/* The STOP switch of the Executions page (ADR-076): the label "STOP" and an on/off switch in the red of the trash button
 * (the specialisation of `switch.js`: `.ge-switch--danger`). Turning it on asks first, naming how many executions run and
 * will be aborted; turning it off does not ask. It shows only while the feature is offered (or while STOP is on, so a stop is
 * never stuck behind a hidden switch). The state is stop-state.js, the question is the page's shared confirm dialog. */
import { plural, t } from "../i18n.js";
import { createSwitch, Switch } from "./switch.js";
import { loadStop, setStop, subscribeStop } from "./stop-state.js";

export class StopSwitch {
  /**
   * @param {HTMLElement} root the element that holds the switch (`[data-stop-switch]`)
   * @param {import("./confirm-dialog.js").ConfirmDialog} confirm the page's confirm dialog
   * @param {{onChanged?: (state: object) => void, onError?: (message: string) => void}} [options]
   */
  constructor(root, confirm, { onChanged, onError } = {}) {
    this.root = root;
    this.confirm = confirm;
    this.onChanged = onChanged;
    this.onError = onError;
    const label = document.createElement("span");
    label.className = "stop-switch__label";
    label.id = `${root.id || "stop-switch"}-label`;
    label.textContent = t("stop.label");
    this.button = createSwitch(label.id);
    this.button.classList.add("ge-switch--danger");
    this.button.title = t("stop.switch_title");
    root.replaceChildren(label, this.button);
    this.switch = new Switch(this.button, { onChange: (on) => this.#changed(on) });
    this.unsubscribe = subscribeStop((state) => this.#show(state));
  }

  #show(state) {
    this.switch.on = state.active;
    this.root.hidden = !(state.available || state.active);
  }

  /** The user flipped the switch: the visible state is the server's until the answer says otherwise. */
  async #changed(on) {
    const before = this.switch.on;
    this.switch.on = !on; // not yet: on needs the answer to the question, off the answer of the server
    if (on) {
      await this.#askThenSwitchOn();
    } else {
      try {
        const state = await setStop(false);
        this.onChanged?.(state);
      } catch (error) {
        this.switch.on = before;
        this.onError?.(error.message || t("stop.could_not_change"));
      }
    }
  }

  async #askThenSwitchOn() {
    let running = 0;
    try {
      running = (await loadStop()).running; // a fresh count: the question says what really happens
    } catch {
      /* the question is asked without the number */
    }
    this.confirm.open({
      title: t("stop.confirm_title"),
      message: running ? plural("stop.confirm_running", running) : t("stop.confirm_idle"),
      note: t("stop.confirm_note"),
      confirmLabel: t("stop.confirm_label"),
      onConfirm: async () => {
        const state = await setStop(true);
        this.onChanged?.(state);
      },
      onClose: () => this.button.focus(),
    });
  }

  dispose() {
    this.unsubscribe();
  }
}
