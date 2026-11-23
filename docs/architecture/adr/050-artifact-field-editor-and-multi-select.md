# ADR-050: The artifact field editor in two panes; multi select; renamed options keep their values

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-044](044-artifact-fields.md)  
**Implemented in:** migration 0039 (`artifact_fields.multiple`); `artifact_fields/rules.py` (`multiple`, one option is enough), `artifact_fields/schemas.py` (`FieldBase`, `renamed_options`), `artifact_fields/service.py` (`_carried`); `static/js/artifact-fields/` (`fields-editor.js`, `model.js`), `static/js/components/sortable.js`, `static/js/components/action-menu.js` (inside an open dialog), `static/js/tasks/field-rail.js`, `templates/index.html`, `css/artifact-fields.css`  
**Affected chapters:** guides [concepts](../../guides/concepts.md), [API reference](../../guides/api-reference.md)

## 1. Context

The *Artifact fields* dialog was one long column of field forms; options were a text area with one value per line; the
order was changed with arrow buttons; a choice held one value. The owner asked for the field settings of GitHub Projects.

## 2. Decision

- **Two panes:** the fields as a list on the left (a grip to reorder, a click to choose one, *Add field*), the chosen
  field's settings on the right: name, the reference pipelines read (fixed once saved, so `${card.NAME}` keeps working),
  field type (Text, Number, Yes / no, Single select, Multi select), what the type needs, the default, *Remove field*.
- **Options of a select** are rows: a grip, the text (a click edits it in place: `InlineName`), and a menu with *Rename*
  and *Delete*; *Add option* adds a row to type into. An empty or duplicate option (ignoring case) is refused at the row.
- **Order** of fields and options: drag the grip (the rest of a row stays a click), or focus it and press ArrowUp /
  ArrowDown (`Sortable`, reusable). The list order is what is saved.
- **Multi select:** a choice with `multiple` holds a list of its values (on the card: one box per value; in a run:
  `${card.tags}` is the JSON list). A choice may have one option.
- **Renamed options keep the values:** the editor sends `renamed_options` ({old: new}) with the field; the artifacts'
  values follow. A deleted option's values go (like a removed field's); a single value becomes a list of one when the
  field turns multi, and back when one value is left; anything that does not fit is still refused (409).
- **Saving:** nothing is saved before *Save* (one `PUT` of the whole list). The footer says *Unsaved changes*; *Cancel*,
  Escape or the close button with unsaved changes ask first (*Keep editing* / *Discard*).
- `ActionMenu` opens inside an open dialog, so menus work in dialogs at all.

## 3. Consequences

- A field's reference cannot be renamed in the editor; a new field with the old values moved would be a future feature.
- The card shows a multi select as boxes; long option lists would want a compact picker later.
