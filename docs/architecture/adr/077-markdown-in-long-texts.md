# ADR-077: Markdown in the long texts

**Status:** Accepted  
**Date:** 2026-11-26  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-055](055-comments-on-artifacts.md) (a comment is plain text; it is now Markdown by convention), [ADR-064](064-the-card-is-a-source-of-the-run.md) (the body with its filled in references is drawn as Markdown, the marks and links inside the formatting), [ADR-059](059-one-catalog-of-ui-building-blocks.md) (a new building block, the Markdown bar)  
**Implemented in:** `static/js/components/markdown.js` (parser and renderer), `markdown-edit.js` (what the buttons do), `markdown-bar.js` (the bar), `tasks/references.js` (`renderBody`), `components/clamped-text.js` (`markdown`), `tasks/comments-tab.js`, `tasks/artifact-dialog.js`, `tasks/board.js`, `agents/editor-page.js`; no migration  
**Affected chapters:** guides [concepts](../../guides/concepts.md), [api-reference](../../guides/api-reference.md), [ui-catalog](../../guides/ui-catalog.md)

## 1. Context

The long free-text fields were plain text: the text of a card, a comment, the user and system prompt of an agent. The owner wants to
write **bold**, *italic*, ~~strikethrough~~ and short lists in them, with a small bar under the field as a work ticket system has it.
The texts are also read by other things than people: the API and the MCP server hand them out, a prompt goes to a model, a run reads a
card's text. And the texts that exist (`1.` lists, `#117` references, `${card.x}` placeholders, `snake_case`, `2 * 3 * 4`, a dash in a
sentence) must read as they always did.

## 2. Decision

- **The text is stored as written, and it is Markdown by convention.** The column stays plain text, there is no migration, no second
  field, no format flag. The API, the MCP server, the agents and the model get the Markdown text unchanged; a prompt is sent as typed.
- **A small subset renders; everything else stays literal.** `**bold**`, `*italic*`, `~~strikethrough~~` and bullet lists (`- item`,
  two more spaces for a sub list, three levels below the first). No headings, code, links, images, numbered lists, checklists, underscores,
  escapes or HTML. Because the rest is literal, an old text looks as before; only a `- ` line now shows a bullet.
- **Emphasis follows the usual rules and one more.** A marker opens only when it is not followed by a blank and stands at the start or after a
  character that is no letter, digit or underscore; it closes only when it is not preceded by a blank and is followed by the end or such a
  character; the text between is not empty; it never spans a line. So `a*b*c`, `2*3*4`, `2 * 3 * 4` and `*.txt and *.md` are literal.
  A marker that does not close is literal. The extra rule (no emphasis inside a word) is stricter than CommonMark on purpose: it keeps old texts
  with stars in them as they were.
- **One safe renderer.** `markdown.js` parses a text into blocks and inline nodes (pure, with the position of every piece) and draws them as
  elements and text nodes only (`strong`, `em`, `del`, `ul`, `li`); the text of a person is never markup and no HTML is ever taken from it. It is
  in-house, about 150 lines: the application ships no Markdown library and the subset is too small to justify one. Every place that shows these
  texts uses it; the plain pieces are drawn by a callback, so that `#12` turns into a link and filled in references stay marked **inside** the
  formatting, wherever the text is cut (`renderBody`: the marks of the personal setting *Mark resolved references* are slices of the same text by position).
- **Where it is drawn:** the card dialog's text, a comment, the archive's text, the preview of the editors' bar. On the board the first words of
  a card show bold, italic and strikethrough (the preview is cut after some lines: a `- ` line stays a line there), as before without links unless the
  references are marked. **The prompts are shown and previewed as written**, the way the model gets them (the agent page's panels and the quick test);
  the bar only helps to write them.
- **The bar (`MarkdownBar`) is one component.** Buttons for bold, italic, strikethrough and a bullet list, Ctrl/Cmd+B and Ctrl/Cmd+I, a hint line,
  and a *Preview* switch (off, not remembered) that shows the text as it will read in place of the field. A button wraps the selection, or inserts
  the markers at the caret, or takes them away when the selection is wrapped; the list button puts `- ` before the lines of the selection or
  takes it away. The edit goes in through the browser's own editing (`insertText`), so **undo keeps working**; where the browser refuses, `setRangeText`
  does it. The field keeps its place, id and listeners: the bar sits after it. No attachments, mentions or `#` picker: the `#` reference menu of
  the card's text stays as it is.
- **Where the bar is:** the text of a card (create and edit), a comment (add and edit), the user and the system prompt of an agent. The long
  fields of a node's settings (`multiline` of the editor: scripts, queries, the prompt overrides of an agent node) have no bar: most of them
  are code, and their persistence is the editor's own.

## 3. Approaches

1. **Markdown by convention with a small renderer (chosen).** The stored text stays text for every reader, API and model included; old texts
   keep their look; the bar is a helper to type the markers. Cost: a person who types `*` sees formatting where a literal star was meant (rare, and
   the word rule narrows it).
2. **Rich text (HTML) with an editor.** Shows the formatting while typing, but the application would store HTML: the API, the MCP server and the model
   would get HTML instead of text, it needs sanitising against injected code (ADR-069 forbids markup from text), and old texts would have to be converted.
   More effort and more risk for the same few formats.
3. **A full Markdown library.** More formats than wanted, one more dependency and its sanitiser, and old texts with `1.` lists, `#` lines or `>` would
   change their look. Rejected for the small subset.

## 4. Consequences

- A text with a `- ` line shows a bullet where it showed a dash; a sub item needs two more spaces as before in the text of old cards (they used them already).
- Other readers may show the Markdown as characters; nothing in the text is lost.
- The bar adds a row under the field: the card's body shows five lines instead of six so that the dialog keeps its size when the rail opens (ADR-059's
  sizing of the artifact dialog).
- A field of a node's settings that holds text for a person (the prompt overrides of an agent node) could get the bar later; it needs a flag in the
  manifest of the setting and a change in the editor's persistence, so it is not part of this decision.
