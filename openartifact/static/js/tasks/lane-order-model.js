/* The pure part of reordering the lanes (ADR-092): where a list of lane statuses goes when one lane moves. */

/** `order` with the entry at `from` moved to `to` (clamped to the list); the same list when nothing moves. */
export function moveLane(order, from, to) {
  if (from < 0 || from >= order.length) return [...order];
  const target = clamp(to, 0, order.length - 1);
  if (target === from) return [...order];
  const next = [...order];
  const [lane] = next.splice(from, 1);
  next.splice(target, 0, lane);
  return next;
}

export function clamp(value, low, high) {
  return Math.min(Math.max(value, low), high);
}

/** Whether two orders differ (a drop that put the lane back where it was saves nothing). */
export function orderChanged(before, after) {
  return before.length !== after.length || before.some((status, i) => status !== after[i]);
}
