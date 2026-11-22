# 8. Cross-cutting Concepts

Concepts that apply to several building blocks.

| Section | Content |
|---------|---------|
| [8.1 Security concepts](08.01-security.md) | Threat model, layers, access token, sessions, request hardening, credentials, container, execution nodes |
| [8.2 Error handling](08.02-error-handling.md) | Response shapes, `ArtifactError`, handlers, node failures, persistence rule, fail-fast |
| [8.3 Logging and observability](08.03-logging-observability.md) | Logging, masking of tokens and credential values, health check |
| [8.4 Board concepts](08.04-board-concepts.md) | State ownership, ordering, integrity, tokens, a11y |
| [8.5 Execution nodes and their safety](08.05-execution-nodes-safety.md) | Code node limits and gaps, HTTP node SSRF guard, open-mode refusal |
| [8.6 Credential store](08.06-credential-store.md) | Encryption, key, access paths, limits, no rotation |
| [8.7 History and retention](08.07-history-and-retention.md) | Run vs execution, retention policy, growth, events |
| [8.8 Accessibility scope](08.08-accessibility-scope.md) | What works by keyboard and screen reader, what does not |
