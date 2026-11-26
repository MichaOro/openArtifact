/* What the two widgets of a limit (`limit`, `optional-number`, components/form-widgets.js) show and what they store (ADR-084, addendum).
 * Storage keeps `null` for "the user has not set it": the engine then uses its own value (the operator's number of executions, today's
 * limits) or the limit is off. The page shows that value instead of an empty field, and stores `null` again when the user types the
 * default back, so a later change of the default still applies. Pure functions, unit-tested (tests/js/limit-model.test.mjs). */

/** The number a field shows: what is stored, else the default. */
export function shown(stored, fallback) {
  return stored === null || stored === undefined ? fallback : stored;
}

/** What to store for a number the user typed: `null` when it is the default, `null` when the field is empty, else the number. */
export function toStored(typed, fallback) {
  if (typed === null || typed === undefined || Number.isNaN(typed)) return null;
  return typed === fallback ? null : typed;
}

/** Whether "Reset to default" is offered: a number is stored and it is not the default. */
export function canReset(stored, fallback) {
  return stored !== null && stored !== undefined && stored !== fallback;
}

/** An optional limit is on while a number is stored. */
export function isOn(stored) {
  return stored !== null && stored !== undefined;
}

/** What the switch stores: the number it gives when switched on (the one stored earlier is gone with `null`), `null` when off. */
export function switched(on, onValue) {
  return on ? onValue : null;
}

/** The default of a field: the page's own number (`context.defaults`, what the engine does), else the manifest's `default_value`. */
export function defaultOf(field, context) {
  const own = context?.defaults?.[field.key];
  return Number.isFinite(own) ? own : (field.config?.default_value ?? null);
}

/** The number a switched-on limit starts with: the page's number (`context.on_values`), else the manifest's `on_value`. */
export function onValueOf(field, context) {
  const own = context?.on_values?.[field.key];
  return Number.isFinite(own) ? own : (field.config?.on_value ?? field.min ?? 1);
}
