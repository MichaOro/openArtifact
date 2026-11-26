# ADR-074: The setting row, and durations as a number with a unit

**Status:** Accepted  
**Date:** 2026-11-26  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-053](053-canonical-node-configuration.md) (the row of an optional setting), [ADR-059](059-one-catalog-of-ui-building-blocks.md) (a new component, `DurationInput`)  
**Implemented in:** `static/js/editor/field.js` (`end`, `labelFor`), `static/js/editor/settings-layout.js` (`makeBin`, `optionalRow`), `static/css/editor.css` (`.field__line`), `static/js/components/duration-input.js`, `static/js/components/duration-model.js`, `tests/e2e/test_retry_setting.py`, `tests/js/duration-model.test.mjs`  
**Affected chapters:** [UI catalog](../../guides/ui-catalog.md#the-setting-row)

## 1. Context

When the owner added *If the node fails* to a node, the bin that takes the setting away lay over the right end of the select: the bin was
positioned absolutely over a control that was as wide as the row. The same owner drew the row for *Retry on fail* (label, switch, bin on
one line; numbers below; the wait with a choice of ms, sec and min "so nobody has to work out what 3467 ms is in seconds") and asked for
one rule for people, and for later agents, that follows from both.

## 2. Decision

**The anatomy of a setting row** (every removable setting of every node window; one definition, not one per kind):

1. **Label** (with the (i) for its help), above its control, or on the line of the control for a switch.
2. **Control**, in a column that gives way (`min-width: 0`, it takes what is left).
3. **End action** in a column of its own, fixed width, after the control: the bin of a removable setting (*Remove* for an added one, *Use the
   default again* for a stored one). It sits on the line of the control, never over it: the control does not know about it, the row
   (`field(..., {end})` → `.field__line`) gives it its place. A label above the control stays above it.
4. **Messages** (the error, the saved note) under the row, never inside it.

**Rules that follow:**

- **No overlap, by construction:** nothing in a row is positioned absolutely over another thing; a test measures that the bin starts after the
  control ends and lies on its line (`test_the_bin_of_a_setting_never_lies_over_its_control`).
- **A switch is on the line of its label,** and what depends on it (the numbers of *Retry on fail*) shows below it only while it is on;
  Off keeps the values.
- **A time is a number and a unit** (`DurationInput`): ms, sec, min, kept as milliseconds. The form shows the largest unit that divides the
  value evenly (3467 ms stays, 90000 ms is 90 sec, 120000 ms is 2 min); the user picks the unit of what they type. Nobody converts.
- **Defaults are shown, not guessed:** an added setting starts with its default and says it; one whose value would matter at once
  (a retry that starts On) is stored at once, so the row never shows what is not kept.
- **Bounds are the server's, said in plain words by both sides:** the range and the reason ("a whole number from 2 to 10", "wait 45
  minutes in all, more than the 30 allowed: use fewer tries or a shorter wait"), under the field, nothing sent while it is wrong.
- **Taking a setting away is one click on its bin** and also takes away a value that was saved while the row was still "just added".

## 3. Consequences

- A kind that adds a removable setting gets the row for free; a control only has to accept `end`.
- The agent editor's own settings group and the override rows (ADR-053) have their own markup; they were not changed and are the next candidates
  for the same row.
