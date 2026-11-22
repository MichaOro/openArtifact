/* Adding, renaming, restyling and deleting lanes: the "Add lane" dialog, each lane's menu (Rename,
 * Settings, Delete) and the API calls. Renaming by clicking a lane's name is done by the board
 * (InlineName); both end up in the same request. Only titles and styles change, never the status key
 * artifacts carry. */
import { ActionMenu } from "../components/action-menu.js";
import { request } from "../http.js";
import { deleteBlockedReason } from "./lane-rules.js";

const lanePath = (status) => `/api/lanes/${encodeURIComponent(status)}`;
const send = (url, method, body) => request(url, { method, body: body === undefined ? undefined : JSON.stringify(body) });

export const listLanes = () => request("/api/lanes");
export const addLane = (title) => send("/api/lanes", "POST", { title });
/** Change a lane's title and/or style ({title, style}); resolves to the lanes. */
export const updateLane = (status, changes) => send(lanePath(status), "PUT", changes);
export const renameLane = (status, title) => updateLane(status, { title });
export const deleteLane = (status) => send(lanePath(status), "DELETE");

export class LaneControls {
  /**
   * @param {object} options
   * @param {import("./board.js").Board} options.board
   * @param {import("../components/form-dialog.js").FormDialog} options.addDialog one field: the title
   * @param {import("../components/confirm-dialog.js").ConfirmDialog} options.confirm
   * @param {import("./lane-settings.js").LaneSettingsDialog} options.settings
   * @param {(lanes: object[]) => void} options.onLanes shows the lanes the server answered with
   */
  constructor({ board, addDialog, confirm, settings, onLanes }) {
    Object.assign(this, { board, addDialog, confirm, settings, onLanes });
    this.menu = new ActionMenu();
    board.element.addEventListener("click", (event) => {
      const button = event.target.closest("[data-lane-menu]");
      if (button) this.#openMenu(button);
    });
    board.element.addEventListener("keydown", (event) => {
      const button = event.target.closest?.("[data-lane-menu]");
      if (button && event.key === "ArrowDown" && !this.menu.isOpen) {
        event.preventDefault();
        this.#openMenu(button);
      }
    });
    document.querySelector("[data-add-lane]")?.addEventListener("click", () => this.#openAdd());
  }

  /** Save a title typed into a lane's name (rejects with the server's message). */
  async rename(status, title) {
    this.onLanes(await renameLane(status, title));
    this.board.announce(`Lane renamed to ${title}`);
  }

  #openMenu(button) {
    const { status } = button.closest("[data-lane]").dataset;
    const title = this.board.laneTitle(status);
    const disabledReason = deleteBlockedReason(this.board.laneCount(status), this.board.statuses.length);
    this.menu.toggle(
      button,
      [
        { label: "Rename", icon: "pencil", onSelect: () => this.board.editLaneName(status) },
        { label: "Settings", icon: "settings", onSelect: () => this.#openSettings(status) },
        { label: "Delete", icon: "trash", danger: true, disabledReason, onSelect: () => this.#confirmDelete(status, title) },
      ],
      `Lane ${title}`,
    );
  }

  #openSettings(status) {
    this.settings.open({
      title: this.board.laneTitle(status),
      hue: this.board.laneHue(status),
      style: this.board.laneStyle(status),
      onSave: async (style) => {
        this.onLanes(await updateLane(status, { style }));
        this.board.announce(`Settings of lane ${this.board.laneTitle(status)} saved`);
      },
    });
  }

  #openAdd() {
    this.addDialog.open({
      title: "Add lane",
      submitLabel: "Add lane",
      onSubmit: async ({ title }) => {
        const lanes = await addLane(title);
        this.onLanes(lanes);
        this.board.announce(`Lane ${title} added`);
        const added = lanes.at(-1).status;
        // the dialog gives focus back to the button when it has closed; the new lane takes it afterwards
        this.addDialog.modal.dialog.addEventListener("close", () => this.board.lanes.get(added)?.name.element.focus(), { once: true });
      },
    });
  }

  #confirmDelete(status, title) {
    this.confirm.open({
      message: "Delete lane {subject}?",
      subject: title,
      onConfirm: async () => {
        let lanes;
        try {
          lanes = await deleteLane(status);
        } catch (error) {
          if (error.status !== 404) throw error;
          lanes = await listLanes(); // already gone elsewhere: the outcome the user wanted
        }
        this.onLanes(lanes);
        this.board.announce(`Lane ${title} deleted`);
      },
    });
  }
}
