# ADR-078: The Build Context node: one package for an agent, within a size limit, that says what it left out

**Status:** Accepted  
**Date:** 2026-11-26  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-054](054-node-kinds-as-yaml-manifests.md) (a new kind and a new setting type, `sources`), [ADR-053](053-canonical-node-configuration.md) (a list setting), [ADR-072](072-result-contract.md) (a node may keep more than 4 KiB of its output in the context)  
**Implemented in:** `engine/context_builder.py` (the rules, the node), `engine/cards_gateway.py` (parent, children, siblings, comment count, earlier executions), `graph/context_sources.py` (the sources as data), `graph/nodes/context.yaml`, `graph/node_types.py` (`sources`), `engine/results.py` (`keep_bytes`), `engine/context.py` (`_cap_output`), `engine/executors.py`, `models/enums.py`, migration `0060`, `static/js/editor/sources-model.js`, `static/js/editor/setting-controls.js` (`SourcesControl`), `static/js/tasks/history-step.js`  
**Affected chapters:** guides [execution nodes](../../guides/execution-nodes.md), [agents](../../guides/agents.md), [ui catalog](../../guides/ui-catalog.md)

## 1. Context

An agent gets the prompts its author wrote and, where a prompt names an input, a part of the card (ADR-064); the rest of what is around the card
(the other comments in full, the parent and the child cards, what earlier nodes and earlier executions gave) reaches it only if the author
builds that by hand, node by node and reference by reference. Card #127 (from the review of #117) asked for a step that assembles a small, fitting
package, with a size limit so nothing overflows. It is plumbing that can lower the token use (only what is relevant, never more than a limit) or
raise it (it adds what the author would not have put in), so it has to be **transparent**: the step must say exactly what went in and what was
left out, and why.

## 2. Decision

- **A node of the kind `context`** (label *Build Context*, German *Kontext bauen*), a normal execution node of an action definition with *On Pass* /
  *On Fail* and *If the node fails*. It only reads. No *Retry on fail*: it is deterministic, a second try gives the same package.
- **Sources are data.** An ordered list, `[{source, count?, detail?, names?}]`, in the setting `sources` (a new setting type). The registry
  `graph/context_sources.py` says which sources exist and which options each takes; the settings API validates with it, the engine builds from
  it and the editor draws from it (`describe` carries the specs). Sources: the card (title and body), its fields, its comments, the parent, the
  children, the siblings, results of earlier nodes of the run (by name) and earlier executions of the card. **Not offered:** *dependencies* (the
  application has no such relation: only a parent and children) and the *output of the Output node* of an earlier execution (an Output node has
  no result of its own; the output of the last step that produced text is used instead, with its node name). A source is there once.
- **A size limit in bytes** (`size_limit`, a `size` setting, 1 KiB to 32 KiB, default 8 KiB; `item_limit`, optional, 256 B to 16 KiB, default 2 KiB).
  Bytes, not characters: the package is stored and limited in UTF-8 bytes like every output, the shared size control takes bytes with a unit, and a
  token count follows the bytes better than the characters; `approx_tokens` is bytes / 4, rounded up, a hint and never a decision.
- **Fixed rules for what does not fit** (documented in the guide, tested):
  1. The card's title and text are **reserved first** and **cut last**; they keep their place in the order. Only they are cut inside an item.
  2. The other sources are weighed **in the user's order**; what does not fit is left out **whole** (never half a comment).
  3. Comments and earlier executions drop the **oldest** first, with a marker line in front (`[... 12 older comments left out]`) and the heading
     `Comments (5 of 30, oldest first)`; fields, related cards and nodes drop the **last** first, with a marker at the end.
  4. An item longer than `item_limit` is cut with the visible mark `…[cut]` before it is weighed; `data` counts those.
  5. The package, headings, markers and separators included, never exceeds the limit.
- **Everything left out is listed.** `data.omitted` has `{source, reason}` for a source that gave nothing or did not fit (and for a named node that has
  not run); `data.included` has, per source, `items`, `available`, `bytes` and `cut`. The step in the History and the flow shows both as readable lists
  (*In the package*, *Left out*) and a line `Package 5.1 KiB of 8.0 KiB (about 1,300 tokens)`.
- **The text is untrusted data.** It is pasted as it is and never read for `${...}`, so `${secret:X}` in a card stays those characters. The headings say
  where a source starts; a card can still forge a heading, so the guide tells an agent author to treat the package as data.
- **A package larger than 4 KiB stays whole in the run context.** The context keeps 4 KiB of a node's output (ADR-033, ADR-072). A package is the
  point of the node, so `NodeResult.keep_bytes` lets a node ask for more: the node asks for its own limit (at most 32 KiB). The whole context stays
  limited (64 KiB); its oldest results lose their output first, as before.
- **A node whose list was never saved builds from the default** (`card`, `comments` 20), the list a new node shows; a saved empty list fails with
  "No source is chosen".
- **Reading goes through a small gateway** (`CardsGateway`, implemented by `SqlCardsGateway` on its own sessions), like the comments gateway of the
  Artifact node, so the engine does not import the artifact service. Archived cards are not used as related cards. A kind needs the migration
  `0060` for the kind check of `graph_nodes`.

## 3. Approaches considered

1. **One setting per source** (a switch and a number each, a fixed order). Simple to draw, but the order is the priority and the user must choose it.
2. **A prompt template with placeholders** (`${context.comments}`). Hidden budgeting, no list of what was left out, and the order lives in prose.
3. **An ordered list of sources with a size limit and fixed rules (chosen).** The order is visible and is the priority; the rules are the same every
   time; the step can say what happened.

## 4. Consequences

- A new kind needs a migration for the kind check (0060) and a new setting type needs an editor control; both follow the earlier kinds
  (ADR-055, ADR-073).
- The editor's lists of kinds (the tests that name them) and the golden files of the node views know the new kind.
- Handover files as JSON with a schema are not part of this: they stay on card #127.
- A later source is one entry in `context_sources.py`, one branch in `read_sources` and its texts.
