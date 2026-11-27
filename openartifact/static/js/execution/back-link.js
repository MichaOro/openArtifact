/* Where the Back button of the execution page leads (ADR-089): to where the user came from. A link to an execution carries `?from=`, a short
 * whitelisted word, never an address: `board`, `executions`, `card:<number>`, `action:<ref>` or `pipeline:<ref>` (the ref is what the
 * editor's address ends with). Anything else, or nothing, is the board. Pure: tests/js/back-link.test.mjs. */

const FORMS = [
  [/^board$/, () => ({ kind: "board", href: "/" })],
  [/^executions$/, () => ({ kind: "executions", href: "/executions" })],
  [/^card:(\d{1,9})$/, (m) => ({ kind: "card", href: `/?artifact=${m[1]}` })],
  [/^action:([A-Za-z0-9._-]{1,80})$/, (m) => ({ kind: "action", href: `/actions/${m[1]}`, named: true })],
  [/^pipeline:([A-Za-z0-9._-]{1,80})$/, (m) => ({ kind: "pipeline", href: `/pipelines/${m[1]}`, named: true })],
];

/** The kind (which text), the address and whether the text takes a name (an action's or a pipeline's) of the Back button for a `from`
 * value; the board for anything that is not on the list. */
export function backTarget(from) {
  const value = typeof from === "string" ? from : "";
  for (const [pattern, make] of FORMS) {
    const found = pattern.exec(value);
    if (found) return { named: false, ...make(found) };
  }
  return { kind: "board", href: "/", named: false };
}

/** `url` with the origin added: how the code that links to an execution says where the link was followed from. */
export function withOrigin(url, from) {
  return from ? `${url}${url.includes("?") ? "&" : "?"}from=${encodeURIComponent(from)}` : url;
}

/** The `from` word for the editor page the user is on (`/actions/<ref>` or `/pipelines/<ref>`), or null on any other page. */
export function editorOrigin(pathname) {
  const found = /^\/(actions|pipelines)\/([A-Za-z0-9._-]{1,80})\/?$/.exec(pathname);
  return found ? `${found[1] === "actions" ? "action" : "pipeline"}:${found[2]}` : null;
}
