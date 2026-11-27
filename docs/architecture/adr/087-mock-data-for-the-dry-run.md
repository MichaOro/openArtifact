# ADR-087: Mock data: a node of the draft hands over a stored result in a dry run

**Status:** Accepted  
**Date:** 2026-11-27  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-086](086-dry-run.md) (a skipped node can have a mock instead of no result), [ADR-070](070-versions-of-actions-and-pipelines.md) (the draft holds what a version never does)  
**Amended by:** —  
**Implemented in:** `graph/mock.py` (the rules of a mock and of test cases), `graph/content.py` (`graph_of(mocks=True)`), `graph/publishing.py` (`graph_for_run`), `graph/repository.py` (`update_node`: `mock`, `cases`), `graph/schemas.py` (`NodeUpdate`, `NodeRead`, `LastResult`), `graph/preflight.py` (the finding `mocks_not_published`), `api/graphs.py` (`.../nodes/{id}/last-result`), `engine/dry_run.py` (`mocked`), `engine/runner.py` (the choice between run, skip and mock), `static/js/editor/mock-model.js`, `mock-panel.js`, `mock-chrome.js`, `inspector.js` (`mockTabs`), `dry-run-panel.js` (test cases), `static/js/tasks/history-step.js` (*Keep as mock*)  
**Affected chapters:** guides [execution nodes](../../guides/execution-nodes.md), [concepts](../../guides/concepts.md), [api reference](../../guides/api-reference.md), [ui catalog](../../guides/ui-catalog.md)

## 1. Context

A dry run skips what writes and leaves no result for it (ADR-086): a later node that needs the comment number a skipped node would have made fails and says "use mock
data". A path that depends on such a result could not be tried at all. Authors need to say what a node would have answered, and to try the same pipeline with different
inputs without typing them again.

## 2. Decision

- **A mock is a complete result of a node:** `outcome` (`pass` or `fail`), `output` (text), `data` (a JSON object) and `reason`, with the switch `enabled`. It is
  taken from real data: *Use the result of the last run* (the newest stored step of that node in a **real** run, `GET .../nodes/{id}/last-result`) and *Keep as mock* on a
  step in the history or on the flow page (it sets the result of that step as the mock of the node in the **current draft** of its action). It can also be typed.
- **Only a dry run uses a mock, and the node is not run:** no call, no tokens, no write, no model call. The step stores the mock as the node's result with `data.mock =
  true` and is flagged *Mock* like a dry run. A mock that fails leaves by *On Fail* (or the node's *If the node fails* mode) as a failed node does. A node that is **not**
  switched on behaves as ADR-086 says (a writing node is skipped). A mock takes precedence over the skip of a writing node. A node that decides or waits (If, Switch, Timer)
  takes none; neither do Trigger, Output, Complete, Stage, Action and Pipeline.
- **A mock lives in the draft only.** It is kept in the node's JSON config under `_mock` (and the test cases under `_cases`), like the placement number: **no migration**. `graph_of`
  leaves both out unless asked (`mocks=True`), so they are in no published version, no fingerprint (setting a mock does not make the draft "changed"), and no snapshot of a
  real run. A dry run of the **published** version has no mocks; a dry run of the draft (the editor's default) has them. Discarding the draft rebuilds the nodes from the
  published version and drops the mocks.
- **No secrets, no evaluation, a size limit.** A mock is stored in plain text: `${secret:...}` and the value of any stored secret are refused (422 with the reason). The text
  is never read for `${...}` (it is data, as the inputs of a dry run are). Output, reason and data together may hold 64 KiB. Unknown fields, a non-object `data` and
  an outcome other than `pass`/`fail` are 422. The API takes the mock as `mock` on `PATCH .../nodes/{id}` (`null` removes it); it is returned as `mock` on the node.
- **Test cases** are named sets of values for the inputs of a Trigger (at most 20, names up to 60 characters, values are text, no secrets), kept on the Trigger in the draft
  (`cases` on the node, `null` removes them), and offered in the *Dry run* tab of the Trigger window: choosing one fills the inputs, *Save as test case* stores the inputs as typed.
- **The check before publishing says it:** a warning `mocks_not_published` ("N mock(s) are set in this draft; they are not published ...") once per graph. It does not
  block: the confirmation of the publish check applies as for any warning.
- **The editor:** the window of every node that leaves a result has the tabs *Settings* and *Mock*; a pencil beside the close button opens the Mock tab; a pin on the card
  (tooltip *Mock active: the dry run uses a stored result*) shows an active mock and opens the tab. Every change is saved at once; a data text that is not a JSON object is
  told in a plain line and nothing is sent.

## 3. Consequences

- A dry run can follow a path that needs the result of a write: the missing-result rule of ADR-086 stays for the nodes that have no mock.
- Two copies of the node's result can differ over time (the mock is a snapshot of a run); *Use the result of the last run* refreshes it.
- A mock follows the node (its id), so it survives renames and moves, and is gone when the node is deleted.
- Not decided here: operating modes of a pipeline (card #142).
