/* The pure parts of the Comments tab (ADR-055): how a comment is labelled, whether it was edited, where a run comment
 * links to, and the texts of the tab. No document access: tests/js/comment-format.test.mjs. */

import { t } from "../i18n.js";
/** What a comment's author kind is called and drawn with (an icon from icons.html). */
export const KINDS = {
  user: { label: t("common.user"), icon: "user" },
  api: { label: "API", icon: "plug" },
  mcp: { label: "MCP", icon: "agent" },
  run: { label: t("tasks.comment_format.run"), icon: "play" },
  system: { label: t("common.system"), icon: "settings" },
};

/** The kind of a comment; an unknown one is shown by its own name with the neutral icon. */
export function kindOf(comment) {
  return KINDS[comment.author_kind] ?? { label: String(comment.author_kind ?? ""), icon: "message" };
}

/** Whether the text was changed after it was written (the server sets updated_at then). */
export function isEdited(comment) {
  return new Date(comment.updated_at).getTime() > new Date(comment.created_at).getTime();
}

/** The page of the execution a run comment came from, or null (any other comment, or an execution of no artifact). */
export function runLink(comment, number) {
  if (comment.author_kind !== "run" || !comment.execution_id || number == null) return null;
  return `/artifacts/${encodeURIComponent(number)}/executions/${encodeURIComponent(comment.execution_id)}?from=card:${encodeURIComponent(number)}`;
}

/** "1 comment", "3 comments". */
export function countText(count) {
  return `${count} comment${count === 1 ? "" : "s"}`;
}

/** Comments in the order they are shown: oldest first, newest last; a stable order for equal times. */
export function inOrder(comments) {
  return [...comments].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));
}

/** The comments with this one added or replaced (by id); the order of the list is kept by `inOrder`. */
export function withComment(comments, comment) {
  return inOrder([...comments.filter((c) => c.id !== comment.id), comment]);
}

/** Whether the text typed can be sent: not only white space. */
export function canSend(text) {
  return text.trim().length > 0;
}
