# ADR-014: Building blocks and extension points

> **Status:** **Accepted**

## 1. Title

The system is built from reusable building blocks (kinds of nodes, inspector blocks, navigation
entries) registered in registries, so that it can later take third-party extensions without forks.

## 2. Context

The editor and the navigation had grown case by case: each kind of node had its own inspector
buttons, the routing select appeared on some kinds and not on others, and the rules of a kind lived
in three places (server rules, a mirror in the browser, the inspector). The sidebar and the rail of
the artifact dialog were written separately although they are the same thing. The long-term goal is
community extensions (nodes, actions, navigation entries, pages such as dashboards) that plug in
instead of patching this repository.

## 3. Decision

### 3.1 Kinds of nodes are classes

- **Server** (`graph/node_types.py`): a base class `NodeType` with the common behaviour and one
  flat subclass per kind (`TriggerType`, `StageType`, `ActionType`, `PipelineNodeType`,
  `CompleteType`, `TimerType`, `OutputType`). A kind declares where it may be used (`scopes`),
  whether it is `fixed` or `addable`, whether it is a step (`chain`) or the end (`ending`) of the
  main line, its `inputs` / `outputs`, its `settings` (a number, a switch) and what it `links_to`.
  `connect_error` holds its connection rules; the base has the rule shared by the steps of the main
  line, a kind overrides it only where it differs (stage start, action). `register()` adds a kind.
  The repository, the rules and the engine read the registry; nothing lists kinds by hand any more.
  `GET /api/node-types` publishes the descriptions.
- **Browser** (`js/editor/node-types.js`): a base class `NodeView` and a flat subclass per kind,
  paired with the server's description (`loadNodeTypes`). A view says how the kind looks (size,
  caption, extra markup such as the stage container), where its ports sit (`portLocal`; the default
  spreads the shown ports down each side, so an action without On Fail has its Pass in the middle by
  itself), which ports a node shows (`isVisible`), mirrors the rules (`canFeed`) and lists its
  inspector blocks (`sections`). `registerView()` adds a view; a kind without one uses `NodeView`.
- The "+" menu lists every `addable` kind of the scope; fixed kinds come with the graph.

### 3.2 One set of inspector blocks

`js/editor/inspector.js` builds the inspector from blocks that look and behave the same for every
kind: the title renamed in place (or not, for a node named after what it links to), the kind's
settings (generated from its description), the choice of what it links to, and **one action row
New · Edit · Delete**, always in this order, with what does not apply greyed out. A pipeline node
and an action therefore offer the same row: New creates a pipeline or an action definition (a small
window asks for the title), Edit opens it with the way back, Delete removes the node.

### 3.3 Navigation entries are classes

`web/navigation.py` has `NavItem` and its kinds `NavLink` (a page; with `children` a section),
`NavField` (a value of the open artifact chosen from a list), `NavAction` (a command) and
`NavDivider`. A `Navigation` is an ordered list of entries in groups. The sidebar (`SIDEBAR`) and
the rail of the artifact dialog (`ARTIFACT_RAIL`) are two `Navigation`s rendered by the same
template building block (`components/nav.html`); a new entry or sub-entry is one more object and
gets the same alignment, icon column and label behaviour.

### 3.4 Structure: as simple as possible, as rich as useful

The default is a thin base class with flat subclasses and blocks put together, because deep
hierarchies are hard to follow for whoever extends the system. This is a default, not a limit:
deeper hierarchies, intermediate base classes or nested blocks are explicitly welcome where they
make the code easier to maintain, more modular or closer to the building-block idea, as long as they
do not complicate the system for nothing or produce boilerplate.

### 3.5 Extension points, not yet extensions

The registries (`register` for node kinds, `registerView` for their views, `Navigation.add` for
entries) are the extension points; the built-in parts use them exactly as an extension would. Loading
third-party extensions is **not built**. When it is, the plan is:

- an extension is a package with a manifest (name, version, the contract version it targets) that
  registers node kinds, views, navigation entries and pages through these functions;
- a contract version, so the application can refuse an extension written for another one;
- pages (for example a dashboard over the application's data) as a further registry next to the
  navigation, reading the data through the API;
- a trust model first: a server extension runs with the application's full rights, so extensions
  must be installed deliberately and are not sandboxed; browser parts are ES modules served from the
  extension.

### 3.6 Quarantine of unused code

Code that falls out of use is not deleted at once. It stays where it is and gets an entry in
`quarantine.json` (what, where, since when, a regular expression for its calls).
`tools/check_quarantine.py`, run weekly by `.github/workflows/quarantine.yml`, fails once an entry
has had no calls for 14 days, as the reminder to remove the code and the entry; if calls show up
again, it says to drop the entry. The first entry is the routing select of the inspector, removed
from the UI because connections are made by dragging.

## 4. Consequences

- A new kind of node is a server class and, if it looks special, a view class; a new navigation
  entry is one object. The rules exist once on the server and once, as a mirror, in the view.
- The editor needs the descriptions before it draws (one request when it opens).
- Connecting by keyboard is no longer possible (the routing select is gone); dragging is the way.
