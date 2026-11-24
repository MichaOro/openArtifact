# ADR-064: The card is a source of the run

**Status:** Accepted  
**Date:** 2026-11-24  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-044](044-artifact-fields.md) (custom field names), [ADR-045](045-agent-inputs-and-prompts.md) (a new input type; the prompt rule stays)  
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
- **Agent input type `artifact`.** The agent node fills such an input with `${card.text}` once, stored explicitly in
  the node's `inputs`; an entry the user cleared or changed is never added again. No default and no "Get artifact"
  operation.
- **The card is a source, never an implicit part of the request; the prompt decides.** Nothing about the card is added
  to the model's request on the side. The card text reaches the model only where the author wrote `${input.x}` in a
  prompt and mapped `x` to a card reference; an input no prompt uses is not sent. The node dialog says so calmly
  (a warning, not an error): "Input epic is mapped but no prompt uses it: the agent does not receive it". The
  pre-fill of an `artifact` input is skipped when another input of the node already holds a `${card...}` reference, so
  the agent never receives the same text twice because of us.
- **A resolved preview.** `POST /api/previews/references` (`{text, card}`) resolves only `${card...}`; nodes and
  variables stay placeholders, secrets are never shown or resolved, the result is cut at 2000 characters, the call
  changes nothing. The editor shows it under reference fields for the card chosen in "Preview with card"
  (browser storage, `?card=` in the address).
- **Typos.** A `${card.x}` that names nothing is a warning when the node is saved (also in the agent dialog) and a clear
  error in the run; it is not refused when saved, like the other reference hints.

## 3. Consequences

- A run's inputs no longer depend on the author having defined a field for title and body.
- `${card.title}` in an old node that meant a custom field called `title` was migrated; the downgrade reverses it.
- Date fields do not exist (kinds: text, number, yes/no, choice); a date is a text field and stays as typed.
