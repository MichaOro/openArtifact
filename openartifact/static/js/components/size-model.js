/* A size in bytes as a person writes it: a number and a unit (B, KiB, MiB), kept as bytes. Pure functions, no DOM
 * (tests/js/size-model.test.mjs). The same rule as the durations (duration-model.js, ADR-074): nobody converts 65536 bytes by hand;
 * the form shows the largest unit that divides the value evenly (1500 B stays 1500 B, 65536 B is 64 KiB, 1048576 B is 1 MiB) and
 * the user picks the unit of what they type. */

export const SIZE_UNITS = [
  { unit: "B", bytes: 1 },
  { unit: "KiB", bytes: 1024 },
  { unit: "MiB", bytes: 1024 * 1024 },
];

const BY_UNIT = Object.fromEntries(SIZE_UNITS.map((u) => [u.unit, u.bytes]));

/** `{value, unit}` for bytes: the largest unit that divides evenly; nothing (or a value that is no number) is 0 B. */
export function splitSize(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return { value: 0, unit: "B" };
  for (const { unit, bytes: factor } of [...SIZE_UNITS].reverse()) {
    if (n % factor === 0) return { value: n / factor, unit };
  }
  return { value: n, unit: "B" };
}

/** Bytes of a number in a unit (a whole number, rounded); `NaN` for no number or an unknown unit. */
export function toBytes(value, unit) {
  const number = typeof value === "string" ? (value.trim() === "" ? NaN : Number(value)) : Number(value);
  const factor = BY_UNIT[unit];
  if (!Number.isFinite(number) || factor === undefined) return NaN;
  return Math.round(number * factor);
}

/** A size in words for a message: "64 KiB", "1 MiB", "1500 B". */
export function describeSize(bytes) {
  const { value, unit } = splitSize(bytes);
  return `${value} ${unit}`;
}
