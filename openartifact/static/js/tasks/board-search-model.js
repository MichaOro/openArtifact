/* The pure part of the board search (ADR-091): which cards a typed query keeps. The title and the number only, never the body.
 *
 *   ""            everything
 *   "#154"        the card with exactly that number
 *   "154"         the card with that number AND the cards whose title contains the digits as text
 *   "sum feed"    every word must be in the title, case and accents ignored (ä is ae, ö oe, ü ue, ß ss; é is e)
 */

/** Text as it is compared: lower case, umlauts spelt out, other accents dropped. */
export function fold(text) {
  return String(text ?? "")
    .toLowerCase()
    .replace(/ä/g, "ae")
    .replace(/ö/g, "oe")
    .replace(/ü/g, "ue")
    .replace(/ß/g, "ss")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");
}

/** A typed query as a plan: `{kind: "all"}`, `{kind: "number", number}`, `{kind: "digits", number, text}` or `{kind: "words", words}`. */
export function parseQuery(query) {
  const typed = String(query ?? "").trim();
  if (!typed) return { kind: "all" };
  const hashed = /^#(\d+)$/.exec(typed);
  if (hashed) return { kind: "number", number: Number(hashed[1]) };
  if (/^\d+$/.test(typed)) return { kind: "digits", number: Number(typed), text: typed };
  return { kind: "words", words: fold(typed).split(/\s+/).filter(Boolean) };
}

/** Whether a card (`{number, title}`) stays for a plan from `parseQuery`. */
export function matches(card, plan) {
  if (plan.kind === "all") return true;
  if (plan.kind === "number") return card.number === plan.number;
  const title = fold(card.title);
  if (plan.kind === "digits") return card.number === plan.number || title.includes(plan.text);
  return plan.words.every((word) => title.includes(word));
}

/** How many of `cards` stay: `{shown, total}`. */
export function tally(cards, plan) {
  let shown = 0;
  for (const card of cards) if (matches(card, plan)) shown += 1;
  return { shown, total: cards.length };
}
