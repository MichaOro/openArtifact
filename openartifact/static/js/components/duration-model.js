/* A length of time as a person writes it: a number and a unit (ms, sec, min), kept as milliseconds. Pure functions, no DOM
 * (tests/js/duration-model.test.mjs). The owner's rule (ADR-074): nobody has to convert 90000 ms into minutes; the form shows the
 * largest unit that divides the value evenly (3467 ms stays 3467 ms, 90000 ms is 90 sec, 120000 ms is 2 min) and the user picks
 * the unit of what they type. */

export const DURATION_UNITS = [
  { unit: "ms", ms: 1 },
  { unit: "sec", ms: 1000 },
  { unit: "min", ms: 60000 },
];

const BY_UNIT = Object.fromEntries(DURATION_UNITS.map((u) => [u.unit, u.ms]));

/** `{value, unit}` for milliseconds: the largest unit that divides evenly; nothing (or a value that is no number) is 0 ms. */
export function splitDuration(milliseconds) {
  const ms = Number(milliseconds);
  if (!Number.isFinite(ms) || ms <= 0) return { value: 0, unit: "ms" };
  for (const { unit, ms: factor } of [...DURATION_UNITS].reverse()) {
    if (ms % factor === 0) return { value: ms / factor, unit };
  }
  return { value: ms, unit: "ms" }; // a fraction of a millisecond is no duration this form keeps
}

/** Milliseconds of a number in a unit (a whole number, rounded); `NaN` for no number or an unknown unit. */
export function toMilliseconds(value, unit) {
  const number = typeof value === "string" ? (value.trim() === "" ? NaN : Number(value)) : Number(value);
  const factor = BY_UNIT[unit];
  if (!Number.isFinite(number) || factor === undefined) return NaN;
  return Math.round(number * factor);
}

/** A duration in words for a message: "90 sec", "2 min", "3467 ms". */
export function describeDuration(milliseconds) {
  const { value, unit } = splitDuration(milliseconds);
  return `${value} ${unit}`;
}
