# ADR-063: Rearranging manifest windows: the layout layer

**Status:** Accepted  
**Date:** 2026-11-24  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-062](062-configuration-windows-as-data.md) (a form manifest can be arranged), [ADR-053](053-canonical-node-configuration.md) and [ADR-054](054-node-kinds-as-yaml-manifests.md) (the settings window of a node kind can be arranged)  
**Implemented in:** `ui/layout.py`, `api/ui_layouts.py` (`/api/ui-layouts`, also under `/api/v1`), `api/forms.py` and `api/graphs.py` (the merge into `/api/forms` and `/api/node-types`), `static/js/components/window-layout.js`, `layout-arrange.js`, `layout-model.js`, `static/css/layout.css`, `static/js/editor/node-layout.js`, `settings-plan.js`  
**Affected chapters:** guide [extending](../../guides/extending.md) (*Rearranging a window*), [UI catalog](../../guides/ui-catalog.md), [API reference](../../guides/api-reference.md), [integration](../../guides/integration.md)

## 1. Context

Every window that is described by a YAML manifest (the form of a configuration window, ADR-062; the settings of a node kind,
ADR-053/054) is drawn from data. The owner wants to see at a glance which windows are manifest windows and to **rearrange
what is there** (which section sits in which column, in which order the fields follow) by drag and drop, save it and keep
working. Adding or removing elements, configuring data and a pool of widgets are *not* wanted now; they stay work on the
manifest and the backend.

The shipped manifests live in the image (read-only file system); "save it as the current YAML" cannot mean writing them.

## 2. Decision

- **The layout is a layer in the data store, merged over the shipped manifest.** One JSON document per window, in the
  `app_settings` row `ui.layouts` (like the retention rules, no migration). A window is named `forms/<form>` or
  `nodes/<kind>`. The layout holds order only:
  - a **form**: the sections in order, each with its column (`1`, `2` or `auto`; a `full` section stays full width), the
    keys of its `fields` and of the folded `advanced` ones;
  - a **node kind**: the sides `definition` and `behaviour` left to right, each with the order of its settings; the rows of
    one `group` (a condition of an If node) are one entry `group:<name>` that moves as a whole.
  The merge is one pure function per kind of window (`apply_form_layout`, `apply_node_layout`); `GET /api/forms` and
  `GET /api/node-types` return the merged description with `layout_customised: true` (a node kind also `layout.sections`).
- **Read forgivingly, written strictly.** A key the manifest no longer has is ignored on read; a key it gained since
  appears after the key before it in the manifest (the field keeps its shipped folding), so a manifest update never breaks a
  saved layout. `PUT` refuses an unknown section or field, a field in another section, a duplicate, a column other than
  1, 2 or auto, a `full` section made narrow or the reverse, and a required field folded away (422 with the reason).
- **Per instance.** There is no user management; a layout applies to every window of that kind of this instance.
- **Reset and export instead of writing the YAML.** `DELETE` brings the shipped layout back; `GET .../export` returns the
  layout as YAML (`window:` and `layout:`), which the owner merges into the manifest in the repository to make it the new
  default.
- **The handle.** Every manifest window carries a round handle with a 3x3 grid of dots on the **top edge of its panel, in
  the middle** (`window-layout.js`). It has a colour family of its own (`--layout-accent`, teal, used by nothing else) and
  its menu is a variant of the menu component (`menu--layout`: a coloured top edge and a title), so it cannot be taken for a
  "..." menu. The menu offers *Edit layout*, *Reset to default* (disabled while the layout is the shipped one) and *Export
  as YAML*; while arranging, *Save layout* (disabled until something changed) and *Discard changes*. Only windows
  whose form comes from a manifest have it: today the guard editor and the settings of every node kind.
- **The arrange view.** *Edit layout* swaps the window's content for the structure of the window (`layout-arrange.js`):
  sections as dashed outlines in the same grid, each with a grip, their fields as labelled bars with a grip (a tag names the
  widget, "conditional" marks a field a `visible_when` hides today, so it can be placed too). The real controls are not
  shown: they depend on values and on the node, the structure does not. A banner says that the change applies to every
  window of this kind; the window's own Save is locked while arranging. Drag a grip with the pointer (a line shows the
  landing place, the window scrolls at its edge, Escape cancels the drag), or focus it and press the arrow keys (Up and Down
  in a list, Left and Right between the columns; a node's sections swap sides); the move is announced in a live region. A
  required field is not folded away. Closing the window with an arrangement not saved asks first.
- **What a node's window can and cannot do.** Its sides are its sections, so a section is moved by swapping the sides; a
  setting stays on its side (Definition or Behaviour: that is meaning, not layout), and its level (always shown, optional,
  folded) is the manifest's. The blocks a kind draws itself (the Agent's choice of agent and its inputs) are shown as a
  **fixed** bar and stay at the top of Definition.

## 3. Consequences

A saved layout can be wrong for a window only in taste, never in structure. The handle shows the owner which windows are
already data. The arrange view does not show live controls, which keeps it simple and lets conditional fields be placed.

**Not included yet (extension points):** adding, removing or hiding an element, renaming a label, changing a widget, a pool of
widgets to add from (a hidden `layout` entry that names a widget key would be the place), per-user layouts, windows that are
not manifests (the retention rule, the provider and credential dialogs: they get the handle when they become manifests), and
rearranging the *blocks* a kind draws itself.
