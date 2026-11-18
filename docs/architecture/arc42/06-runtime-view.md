# 6. Runtime View

## 6.1 Key Scenarios

> TBD — Runtime scenarios to be defined alongside implementation in WP-02 through WP-04.

**Planned scenarios:**

1. **Workflow execution** — User requests workflow start → HTTP API → Workflow Engine creates execution → Async tasks execute → Progress streamed via WebSocket → Result stored in Artifact Store
2. **Human intervention** — Workflow pauses → User receives notification → User approves/rejects → Workflow continues

## 6.2 State Behavior

> TBD — State machines and lifecycle definitions deferred to WP-02.

---

*This chapter follows the arc42 template. TBD fields are limited to runtime behaviors introduced in later Work Packages.*
