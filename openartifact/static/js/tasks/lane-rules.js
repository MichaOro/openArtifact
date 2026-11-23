/* What the board knows about when a lane can be deleted (the server enforces the same rules). */

import { t } from "../i18n.js";
export const NOT_EMPTY = t("tasks.lane_rules.lane_can_only_be_deleted");
export const LAST_LANE = t("tasks.lane_rules.last_lane_cannot_be_deleted");

/** Why a lane cannot be deleted, or null when it can. */
export function deleteBlockedReason(artifactCount, laneCount) {
  if (artifactCount > 0) return NOT_EMPTY;
  if (laneCount <= 1) return LAST_LANE;
  return null;
}
