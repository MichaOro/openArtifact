# Optional condition of a card rule (design)

**Date:** 2026-11-26 · **Status:** approved by the owner · **Amends:** [ADR-071](../../architecture/adr/071-card-rules.md)

## Intent

A rule of a lane or of the board says *if conditions hold, then something happens to the card*. The owner wants to define a state
without a condition: "as long as a card is in this lane, it is done" (lane *Done*, action *Set card as done*), and when the card leaves
the lane the state is gone. The editor showed *If all of these* with *No conditions yet* under it, which reads like an unfinished rule.

## What already holds

- A card rule without a condition holds for every card of its place (`card_rules.holds`, ADR-071).
- The state is **derived** at every read of a card, never stored. A card that leaves the lane loses the state at once, with no timer.

So nothing changes in the data or the server. The gap is how the editor says it.

## Goals / non-goals

- Goal: the editor says plainly that a rule can be *always*, and that this is a normal rule, for lanes and for the board.
- Goal: no change for the retention rules (ADR-052) and the guards (ADR-060), where a rule without a condition does nothing.
- Non-goal: *always false*. A rule that never holds is a rule that is switched off; the switch exists.
- Non-goal: any binding to time. Always means "while the card is where the rule is".
- Anti-goal: a new stored shape or a migration.

## Approaches

1. **A condition `true` / `false` in the tree** (a boolean condition next to *and*/*or*). Familiar to programmers, but it adds a new
   condition kind to the model, the catalog, the validators and the SQL/in-memory evaluators, and it makes *always false* possible,
   which the switch already covers.
2. **Hide the *If* block** when it is empty. Simple, but then there is no way to see or say that a rule is *always*; "empty" would
   have to be told apart from "not yet filled in".
3. **A choice above the conditions: *Always* / *Only when…*** (chosen). It is the pattern of automation tools (always, or with
   conditions). It keeps the stored shape: an empty condition group means always.

## Decision

- Card rules get the choice *Always (every card in this lane / on the board)* / *Only when…* above *If*. *Always* hides the tree;
  *Only when…* shows it as before. A new rule starts as *Always*; switching back to *Always* clears the tree.
- The choice is an opt-in of the shared rule editor (`schema.always`, set for the lane and board schemas only).
- **Stored as today:** an empty `when` group is *always*. The choice itself is a flag of the open dialog (`rule.conditional`) and is not
  saved; a rule with conditions is *only when* when it is loaded.
- *Only when…* without a condition cannot be saved (it would silently become *always*): Save stays off with a hint.
- A rule that deletes needs a condition: *Always* is disabled for it and choosing the action switches to *Only when…*.
- The rule list reads *Always: Set card as done* for a rule without a condition.

## Left to the builder

The exact words and German texts, the small CSS for the choice, and the tests (unit tests of the summary and the schema, one browser
test of the choice).
