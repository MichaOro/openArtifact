/* The page size of a management page (ADR-069, addendum "the page size follows the room"): pure functions, no DOM.
 *
 * A card has a fixed size, so what fits the visible area of the list is exact maths: whole columns times whole rows. That number is the BASE
 * (never less than 12). The "Per page" choices are steps of it: the base, twice and four times the base. What the browser remembers is the step
 * (1, 2 or 4), not a number, so a choice still fits after a screen change. A server answers at most 500 entries per request: the steps never
 * go over it. */

/** The smallest base: a phone shows one column and still loads this many (the page scrolls). */
export const MINIMUM = 12;
/** No step is larger than this (the most the server gives in one request). */
export const MAXIMUM = 500;
/** The multiples of the base the "Per page" choice offers. */
export const STEPS = [1, 2, 4];

/** How many items of `size` fit into `extent` pixels when `gap` pixels lie between two of them; whole items only (0 when not even one). */
export function fit(extent, size, gap) {
  if (!(extent > 0) || !(size > 0)) return 0;
  return Math.max(0, Math.floor((extent + gap) / (size + gap)));
}

/** The base: columns times rows that fit, at least `MINIMUM`, at most `MAXIMUM`. An area that could not be measured (no columns or no rows) gives the minimum. */
export function baseOf(columns, rows) {
  const n = columns > 0 && rows > 0 ? columns * rows : 0;
  return Math.min(MAXIMUM, Math.max(MINIMUM, n));
}

/** The page size of a step: the base times the step, never over `MAXIMUM`. An unknown step counts as the first. */
export function sizeOf(base, step) {
  const times = STEPS.includes(step) ? step : 1;
  return Math.min(MAXIMUM, base * times);
}

/** The choices of the "Per page" select: `{step, size}` for each step, the sizes strictly rising (a base that already is the maximum has one choice). */
export function choices(base) {
  const seen = new Set();
  const out = [];
  for (const step of STEPS) {
    const size = sizeOf(base, step);
    if (seen.has(size)) continue;
    seen.add(size);
    out.push({ step, size });
  }
  return out;
}

/** The step the browser had stored (1, 2 or 4, also as text); anything else, and the old absolute sizes, is the first step. */
export function stepOf(stored) {
  const n = Number(stored);
  return STEPS.includes(n) ? n : 1;
}

/** The step a choice belongs to when the stored step has no choice any more (a base at the maximum): the largest step that still has one. */
export function usableStep(base, step) {
  const wanted = sizeOf(base, step);
  const match = choices(base).find((c) => c.size === wanted);
  return match ? match.step : choices(base).at(-1).step;
}

/** The page that holds the item at index `first`, for pages of `size`: keeps the first visible item on the page when the size changes. */
export function pageOf(first, size) {
  return size > 0 ? Math.max(0, Math.floor(first / size)) : 0;
}

/** The index of the first item of `page`. */
export function firstOf(page, size) {
  return Math.max(0, page) * size;
}
