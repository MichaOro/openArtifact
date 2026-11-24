/* PARKED, not in use (quarantine.json, since 2026-11-24): the "Can watch" chips (Pipeline, Stage, Action) of the guard
 * editor. The owner hid them: every guard may watch every scope for now, and a new definition has all three. The data
 * (`scope_types`), the API and the checks stay as they are; this is only the control that edited them, kept so that it
 * can come back in a day or two. Call it with the editor's state to get the chips. Remove it with its quarantine entry
 * when the owner decides to drop it for good. */
import { widgetFor } from "../components/form-widgets.js";
import { t } from "../i18n.js";
import * as model from "./model.js";

/** The chips of the scopes a definition can watch; changes are written into `state.scope_types`. */
export function scopeChips(state, onChange = () => {}) {
  const built = widgetFor("chips")({
    field: { key: "scope_types", label: t("guards.can_watch") },
    value: state.scope_types,
    options: model.SCOPES.map((scope) => ({ value: scope, label: t(`guards.scope.${scope}`) })),
    set: (chosen) => {
      state.scope_types = model.SCOPES.filter((scope) => chosen.includes(scope));
      onChange();
    },
    id: "gd-scopes",
  });
  built.el.dataset.guardScopes = "";
  return built.el;
}
