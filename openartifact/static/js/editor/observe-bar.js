/* The entries of the observe mode in the status bar of a pipeline's canvas (ADR-088): the open eye while the pipeline is observed (a click:
 * the facts, "Stop observing" (a change of the draft, applied by a publication) and "Open settings"), and the stop sign while the
 * observation has ended and starts are refused (a click: the reason and the two decisions that act at once, "Release" and "Observe again").
 * An entry that is not active is not there; there is no closed eye. */
import { t } from "../i18n.js";
import { barVisibility, facts, settingOf } from "./observe-model.js";

export class ObserveBar {
  /**
   * @param {{bar: import("../components/status-bar.js").StatusBar, popup: import("../components/status-popup.js").StatusPopup,
   *   store: import("./observe-store.js").ObserveStore, openSettings: () => void, draftChanged: () => void}} parts
   */
  constructor({ bar, popup, store, openSettings, draftChanged }) {
    this.bar = bar;
    this.popup = popup;
    this.store = store;
    this.openSettings = openSettings;
    this.draftChanged = draftChanged;
    this.eye = bar.add({ key: "observe", order: 10, icon: "eye", label: t("editor.observe.eye_label"), onClick: (button) => this.#eye(button) });
    this.stop = bar.add({ key: "ended", order: 5, icon: "hand", label: t("editor.observe.ended_label"), onClick: (button) => this.#ended(button) });
    store.subscribe((read) => this.#follow(read));
  }

  #follow(read) {
    const shown = barVisibility(read);
    this.bar.set("observe", shown.observe);
    this.bar.set("ended", shown.ended);
    if (this.popup.isOpen && this.popup.trigger === this.eye) shown.observe ? this.popup.update(this.#eyeContent(read)) : this.popup.close({ restoreFocus: false });
    if (this.popup.isOpen && this.popup.trigger === this.stop) shown.ended ? this.popup.update(this.#endedContent(read)) : this.popup.close({ restoreFocus: false });
  }

  #lines(read) {
    return facts(read).map(([key, params]) => t(`editor.observe.fact_${key}`, params));
  }

  #eye(button) {
    this.popup.toggle(button, this.#eyeContent(this.store.read));
  }

  #eyeContent(read, { asking = false } = {}) {
    const switchedOff = read?.draft && !read.draft.enabled; // already switched off in the draft: it waits for the publication
    const base = { title: t("editor.observe.popup_title"), lines: this.#lines(read), error: "" };
    if (switchedOff) {
      return { ...base, note: t("editor.observe.switched_off_waiting"), actions: [{ label: t("editor.observe.settings"), onClick: () => this.#settings() }] };
    }
    if (asking) {
      return {
        ...base,
        note: t("editor.observe.stop_confirm"),
        actions: [
          { label: t("editor.observe.stop"), primary: true, onClick: () => this.#stopObserving() },
          { label: t("common.cancel"), onClick: () => this.popup.update(this.#eyeContent(this.store.read)) },
        ],
      };
    }
    return {
      ...base,
      note: t("editor.observe.popup_note"),
      actions: [
        { label: t("editor.observe.stop"), onClick: () => this.popup.update(this.#eyeContent(this.store.read, { asking: true })) },
        { label: t("editor.observe.settings"), onClick: () => this.#settings() },
      ],
    };
  }

  #settings() {
    this.popup.close({ restoreFocus: false });
    this.openSettings();
  }

  async #stopObserving() {
    try {
      await this.store.setDraft(settingOf({ enabled: false }));
      this.draftChanged();
      this.popup.update(this.#eyeContent(this.store.read));
    } catch (error) {
      this.popup.update({ error: error.detail ?? error.message });
    }
  }

  #ended(button) {
    this.popup.toggle(button, this.#endedContent(this.store.read));
  }

  #endedContent(read) {
    return {
      title: t("editor.observe.ended_title"),
      lines: [read?.state?.reason ?? ""].filter(Boolean),
      note: t("editor.observe.ended_note"),
      error: "",
      actions: [
        { label: t("editor.observe.release"), primary: true, onClick: () => this.#decide(() => this.store.release()) },
        { label: t("editor.observe.again"), onClick: () => this.#decide(() => this.store.again()) },
      ],
    };
  }

  async #decide(call) {
    try {
      await call();
      this.popup.close({ restoreFocus: false });
    } catch (error) {
      this.popup.update({ error: error.detail ?? error.message });
    }
  }
}
