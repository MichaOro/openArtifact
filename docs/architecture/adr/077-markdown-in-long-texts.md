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

## Addendum 1: the common Markdown

The owner tried the small subset, wrote `## Hello` and saw the characters: the common Markdown is wanted, not only bold, italic, strikethrough
and bullets. This addendum widens section 2; everything not named here stays as decided there (stored as written, no migration, the prompts
shown as written, `#12` links, the marks of filled in references inside the formatting).

- **What renders now** (`markdown.js`): headings `#` to `######` (a blank after the hashes: `##Hello` and `#117` stay text), bold with `**` and `__`,
  italic with `*` and `_`, `~~strikethrough~~`, `` `inline code` ``, fenced code blocks with an optional language shown as a small caption (the content
  is text and is never read), quotes with `>` (two levels), bullet lists with `-`, `*` and `+` and numbered lists with `1.` (the indent of the sub item decides
  the level: two, three or four spaces; three levels below the first), a rule (`---`, `***`, `___`), paragraphs, GFM tables (header row, delimiter row, alignment
  colons, `\|` for a pipe in a cell, formatting inside the cells; a wide table scrolls inside the text), links `[text](https://address)` and bare `https://`
  addresses. A line break inside a paragraph stays a visible line break (as before); a blank line starts a new paragraph.
- **What stays text on purpose:** images (`![alt](address)` is shown as typed and nothing is fetched or linked), raw HTML, reference style links,
  footnotes, task lists, backslash escapes (but `\|` in a table cell) and setext headings (a line of dashes under a text is a rule). The underscore rule is the
  word rule of the stars: `_a_` is italic, `snake_case` and `2_3` are not.
- **Old texts:** a line `1. one` is now a numbered list, a line that starts with `# ` is a heading, `* x` and `+ x` are bullets, `__init__` is bold: the owner
  accepted this by asking for the common Markdown. The rest of the old kinds (`${card.x}`, `#117`, `snake_case`, `2 * 3 * 4`, a dash in a sentence, `<b>x</b>`) reads as before; tests keep them.
- **Safe by construction, as before, and a little more.** Elements and text nodes only, never `innerHTML`. A link goes to `http`, `https` or `mailto` only:
  `javascript:`, `data:`, `file:` and a bare `www.x.de` stay text. It opens in a new tab with `rel="noopener noreferrer nofollow"`, and its address is its `title`, so a
  link whose words say something else shows where it goes. The words of a link and code are text: `#12` is no link there, but the marks of filled in references are
  drawn there too. Limits keep a hostile text cheap: a text is read as Markdown up to 100,000 characters (the rest is a plain paragraph), a line up to 1,500 characters
  (a longer one is plain text), emphasis and links nest four deep, a quote two, a table 20 columns and 300 rows. The scanners have no backtracking pattern; a test feeds
  long runs of markers, deep nesting, many cells and a huge text and bounds the time.
- **The first words of a card on the board stay plain lines:** no block is drawn and no link; the block marks (`#`, `>`, bullets, fences, the pipes of a table, the address of
  a link) are not shown, the words are; bold, italic, strikethrough and code stay. A table row reads as its cells with ` · ` between them.
- **A text with blocks in a panel** (`ClampedText` with `markdown`) is cut by the height of its lines (`max-height` of the lines times the line height), not by
  `-webkit-line-clamp`, which does not count the lines of blocks reliably; a heading counts as taller than a line of text.
- **The bar** has ten buttons: heading (one click goes `#`, `##`, `###`, none), bold, italic, strikethrough, bullet list, numbered list, quote, code, code block and link, and
  the Preview switch; Ctrl/Cmd+B, +I and +K. A block button works on the lines of the selection and takes its mark away when every line has it; an inline button wraps the
  selection or sets the caret between the marks. The buttons are 28 px so that the bar stays two lines high in the form column (it must not change the height of the dialog when the rail
  opens). **No table button and no image button:** there is no good standard for a table and a table is written by hand; the table is drawn.
- **The link popup** opens under the Link button (above it where there is no room) with two lines, *Text* (the selection is prefilled) and *Address*. Enter inserts, Escape
  closes it and the window around stays open, the focus returns to the field. The address is checked: only `http`, `https` and `mailto`; a bare `www.x.de` or `x.de/path` becomes `https://…`,
  `a@b.de` becomes `mailto:…`; a wrong or empty one shows its reason in the popup and nothing is inserted. With the caret in an existing link the popup opens prefilled to change it. The
  window of a dialog blurs its backdrop and so frames everything `position: fixed` inside it: the popup works its place out from where its own origin lies on the screen.
- **Why not a library:** the renderer is about 500 lines and safe by construction; a library would bring its own sanitiser or a rule for what is HTML, more than the owner wants (no
  images, no HTML) and a dependency to keep up. Rejected again for the wider set.
