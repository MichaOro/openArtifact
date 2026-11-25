# ADR-067: Pipeline actions and guard actions

**Status:** Accepted  
**Date:** 2026-11-25  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-060](060-guards.md) (the guard's own action), [ADR-054](054-node-kinds-as-yaml-manifests.md) (a kind says where it may be used)  
**Implemented in:** migration `0054`, `models/graphs.py` (`purpose`), `graph/repository.py`, `api/graphs.py`, `guards/service.py`, `graph/nodes/*.yaml` (`purposes`, `requires`), `ui/forms/action.yaml`, `static/js/components/manifest-dialog.js`, `static/js/editor/list.js`, `tests/test_action_purpose.py`  
**Affected chapters:** guides [guards](../../guides/guards.md), [extending](../../guides/extending.md)

## 1. Context

A guard can run an action of its own (*Run the guard's action*, ADR-060). That action was an ordinary action definition, the same
thing a stage of a pipeline runs. A guard that judges whether a run is healthy needs nodes that read internal data (the SQLite
node, card #102); such a node must never be offered in an action of a pipeline, where an agent with an HTTP tool could carry what it
read to the outside. The two kinds of action also differ for the person: one belongs to the flow of an artifact, the other to the
watching of it. The owner's decision (2026-11-25): the type is chosen when an action is made, the two are exclusive, and a node kind
can be for one of them or for both.

## 2. Decision

- **An action definition has a purpose:** `pipeline` (used by the stages of a pipeline) or `guard` (run only by guards). It is a
  column of the graph (`graphs.purpose`), not a new kind of graph. Every pipeline is `pipeline`. The API default is `pipeline`, so
  an existing client keeps working.
- **The two never mix, and the server keeps it:** a stage takes only a pipeline action (`422` otherwise), a guard's action must be a
  guard action (`422` when the guard is saved), and the action a guard makes for itself is made as a guard action. Importing goes
  through the same checks, since it uses the same repository.
- **The purpose is chosen when the action is made** (the window of the Actions page is a form manifest, `ui/forms/action.yaml`,
  ADR-065) and **can be changed** in the same window, with protection: an action that a stage uses cannot become a guard action,
  one that a guard runs cannot become a pipeline action, and one that holds a node of a kind that is not for the new purpose cannot
  change either. The `409` answer names the pipelines, the guards or the node kinds, and the window shows it.
- **A kind of node says where it may be used** (`purposes: [pipeline, guard]` in its manifest, both by default; `[guard]` for a kind
  that only guards may use). The "+" menu of an action offers only the kinds for its purpose, and the server refuses another when a
  node is added. An optional `requires: <right>` is a hook for the permissions of card #99 (user, developer, admin): nothing
  evaluates it yet, so later permissions need no change of the manifests.
- **The Actions page keeps them apart:** two tabs, *Pipeline actions* and *Guard actions*; a guard action shows a *Guard* chip next
  to *Draft*. `GET /api/actions?purpose=guard|pipeline` narrows the list; the stage's choice of an action and the guard editor use it.
- **Existing data (migration `0054`):** an action that a guard runs becomes a guard action. One that a stage of a pipeline uses too
  stays a pipeline action and keeps working; the guard editor then asks for a guard action the next time that guard is saved.

## 3. Consequences

- A node with access to internal data can be limited to guard actions by one line in its manifest, enforced by the server, not by
  the menu alone.
- Third parties declare `purposes` in their kinds; a kind that says nothing is usable everywhere, as before.
- An action is either for pipelines or for guards. Wanting both is two actions; sharing the steps is the job of an action called
  from another (not built).
