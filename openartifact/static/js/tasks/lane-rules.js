/* What the board knows about when a lane can be deleted (the server enforces the same rules). */

export const NOT_EMPTY = "A lane can only be deleted when it contains no artifacts.";
export const LAST_LANE = "The last lane cannot be deleted.";

/** Why a lane cannot be deleted, or null when it can. */
export function deleteBlockedReason(artifactCount, laneCount) {
  if (artifactCount > 0) return NOT_EMPTY;
  if (laneCount <= 1) return LAST_LANE;
  return null;
}
