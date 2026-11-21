# 12. Glossary

## Terms

| Term | Definition |
|------|------------|
| Artifact | Structured unit of work within OpenArtifact; a card on the board. **UI wording:** the interface always says "artifact" (never task, issue or work package). In code, API and database the same thing is still named `task` (`/api/tasks`, table `tasks`); that is an implementation name, not product language. Every artifact has a permanent number (`#12`) that is never reused and can be referenced as `#12` in other artifacts' bodies. |
| Lane | A column of the board. Defined in `BOARD_LANES` (`openartifact/tasks/lanes.py`); lane N always has colour N of the lane palette. |
| Orchestration | TBD — Coordination of workflows and agents. |
| Agent | TBD — Autonomous or semi-autonomous execution entity. |
| Workflow | A definition of how artifacts are processed: a graph of a trigger, stages and complete nodes (ADR-012). Designed visually; not executable yet. |
| Trigger | The start node of a workflow (placeholder for manual, webhook or event starts). |
| Stage | A container inside a workflow that holds actions and connects to other stages. |
| Action | A node inside a stage that stands for one business execution; has an input, *On Pass* and *On Error*. What it does is defined in a later step. |

---

*This chapter follows the arc42 template. All TBD fields are pending definition.*
