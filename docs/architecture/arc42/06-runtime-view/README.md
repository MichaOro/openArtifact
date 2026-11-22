# 6. Runtime View

Key runtime scenarios, one file each.

| Section | Content |
|---------|---------|
| [6.1 Container startup](06.01-container-startup.md) | Entrypoint, migrations, start checks, lifespan, shutdown |
| [6.2 Moving a card](06.02-moving-a-card.md) | Optimistic update, SSE fan-out, resync |
| [6.3 State behavior](06.03-state-behavior.md) | Run, stage and execution states, SQLite WAL behaviour |
| [6.4 Processing an artifact](06.04-processing-an-artifact.md) | Start (user, api, mcp), run, stop, lock, SSE |
| [6.5 A request and signing in](06.05-request-and-sign-in.md) | Middleware chain, access gate, session |
| [6.6 Starting an execution](06.06-start-of-an-execution.md) | Claim, run cap, one transaction, events after commit |
| [6.7 Executing a Code node](06.07-code-node-execution.md) | Wrapper, limits, process group, registry, cleanup |
| [6.8 Resolving credentials and masking](06.08-credential-resolution.md) | Reference, resolve, substitute, mask |
| [6.9 History, retention and flow](06.09-history-retention-and-flow.md) | Recording, pruning, replay, keyset paging |
