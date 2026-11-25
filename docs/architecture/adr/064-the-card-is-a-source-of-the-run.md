# ADR-064: The card is a source of the run

**Status:** Accepted  
**Date:** 2026-11-24  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-044](044-artifact-fields.md) (custom field names), [ADR-045](045-agent-editor-progressive-disclosure.md) (inputs have a source: a value or the artifact; the prompt rule stays)  
**Implemented in:** `engine/context.py` (`BUILT_IN_CARD`, `check_card`, `card_problems`, `preview_references`), `artifact_fields/service.py` (`card_of`), `api/previews.py` (`POST /api/previews/references`, also under `/api/v1`), `agents/schemas.py` (type `artifact`), migration `0051`, editor: `reference-completion.js`, `reference-preview*.js`, `agent-inspector.js`  
**Affected chapters:** guides [execution nodes](../../guides/execution-nodes.md), [agents](../../guides/agents.md), [concepts](../../guides/concepts.md), [API reference](../../guides/api-reference.md); arc42 [building blocks](../arc42/05-building-block-view/05.04-frontend-components.md)

## 1. Context

A run knew only the custom artifact fields as `${card.NAME}`, not the title or the body. An agent that was given nothing
mapped ran with empty inputs and the model answered that "the text is empty". Prompts accept only `${input.NAME}`
(ADR-045); that rule stays.

## 2. Decision

- **Built-in references.** `${card.id}`, `number`, `title`, `body` and `text` always exist next to the custom fields.
  `text` is derived (`#<number> <title>` and the body) and not stored. They are a **copy** taken when the run starts,
  like the fields. They are also in `card` of a Code node's `context.json`. An unknown name is refused and lists the
  names that exist.
- **Reserved names.** A custom field cannot be named like a built-in (422). Migration `0051` renames existing clashes
  (suffix `_field`) in `artifact_fields`, in the keys of `tasks.field_values` and in `${card.old}` of node settings.
- **Every defined field is a key.** A field nobody filled is an empty text (`""`) when it is referenced in text, not
  `null`; a name that is not defined at all is refused (warning when saved, error in the run).
- **A card too large is refused, never cut.** The card as a whole is limited to 40 KiB at run start (422).
- **Every input of an agent has a source (revised 2026-11-24).** `source` is `value` (with a `type`: `string`,
  `number` or `boolean`; mapped in the action's node, required or optional, with a default) or `artifact` (with a `part`
  of the artifact the run belongs to: `title`, `body`, `title_body` = `#<number> <title>`, a blank line, the body,
  `number`, or `comments`). An artifact input is **fixed by the definition**: it has no mapping field in the agent node,
  no required flag and no default, and the API refuses (422) a node that maps it ("input 'x' comes from the artifact
  and cannot be mapped in the action"). A line left in a node for an input that became an artifact input is **ignored**
  by a run and shown in the dialog as stale with a *Remove* button. `comments` is all comments of the artifact, oldest
  first, read when the node runs, each as "<author> (<kind>), <date time>: <text>"; one input is limited to 64 KiB and a
  larger value fails the node with a clear message, it is never cut. A run without an artifact fails the node
  ("this agent needs an artifact, but the run has none"). The old shape (`type: artifact`, no `source`) reads as the
  source `artifact`, part `title_body` (migration 0052 writes it down and takes the now-ignored lines out of the nodes).
  There is no pre-fill of the node, no `${card.text}` copy and no `artifact` type choice any more.
- **The card is a source, never an implicit part of the request; the prompt decides.** Nothing about the card is added
  to the model's request on the side. The card text reaches the model only where the author wrote `${input.x}` in a
  prompt and `x` takes the card (an artifact input, or a value mapped to a card reference); an input no prompt uses is
  not sent. The node dialog says so calmly (a warning, not an error): "Input epic comes from the artifact but no prompt
  uses it: the agent does not receive it".
- **No resolved preview.** `POST /api/previews/references`, the "Preview with card" choice and the resolved line under
  fields were removed again (the owner's decision); the editors show general examples instead (the Quick test of an agent
  uses a fixed sample per part: title "Example artifact", an example body, number 1, two example comments).
- **Typos.** A `${card.x}` that names nothing is a warning when the node is saved (also in the agent dialog) and a clear
  error in the run; it is not refused when saved, like the other reference hints.

- **The body with its references filled in (2026-11-25).** A body may hold `${card.title}`, `${card.number}`,
  `${card.id}` and `${card.<field>}`; only the original is stored. One pure function
  (`artifact_fields/body.py`, `resolve_body(body, card, max_words=None)`) fills them in: `${card.body}` and
  `${card.text}` (a body cannot contain itself), `node`/`var`/`secret` references and names the artifact does not
  have stay as written, one level only, an empty field is empty text, numbers and booleans render as compact JSON.
  Where it is used: the single read (`GET /api/tasks/{id}`, `/api/v1/artifacts/{ref}`, MCP `get_artifact`) returns
  `body` (original), `fields` and `body_resolved` (`null` when nothing was filled in); the list returns `preview`
  (the first `PREVIEW_WORDS = 60` words, filled in, `null` when the body has no reference, then the client cuts the
  original as before). The preview reads the text token by token and stops when the budget is spent, so a body of ten
  thousand words costs what a short one does, and a body without `${card.` is not scanned. The budget is 60 words, not
  25: the board never cut by words (CSS clamps at six lines), 60 keeps the look. Saving a body with a reference that
  names nothing answers with `warnings` (never a refusal; not part of the events). The events carry `body_resolved`
  and `preview`. The card a run starts with holds the RESOLVED body, so `${card.body}`, `${card.text}` and the
  agent's artifact inputs read the finished text; titles are never filled in. The artifact dialog shows the finished
  text with the marker "References resolved" and the toggle "Show as written"; Edit shows the original; an open
  dialog and the board refresh when the fields change. No migration.

- **`${card.NAME}` in every prompt (2026-11-25, replaces "a prompt takes only `${input.NAME}`").** The fields of the card
  are there for every agent, so a user prompt and a system prompt, in the agent and in a node's override, may read
  `${card.title}`, `${card.body}`, `${card.number}`, `${card.id}`, `${card.text}` and any custom field without an input
  being declared: the value is the one the card of the run has when the node runs (two cards, two values). `node`, `var`
  and `secret` references stay refused in a prompt. `fill()` (`agents/render.py`) replaces `${input.x}` and
  `${card.x}` in one pass (a value that looks like a placeholder stays text); a field the card does not have fails the
  run with the names it has, and a run without a card names that. The Quick test takes example values of card fields
  (`card` in the preview request); without them a `${card.x}` stays as written. Setting a system prompt of its own in
  a node switches it on (`resolve.py`): the node has no "Use system prompt" switch, the agent's editor keeps it. The
  version of the agent a node runs is a `vN` badge next to the close button of the node dialog (published time on hover,
  a click asks before it opens the agent).

## 3. Consequences

- A run's inputs no longer depend on the author having defined a field for title and body.
- `${card.title}` in an old node that meant a custom field called `title` was migrated; the downgrade reverses it.
- Date fields do not exist (kinds: text, number, yes/no, choice); a date is a text field and stays as typed.
