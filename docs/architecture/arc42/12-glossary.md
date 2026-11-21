# 12. Glossary

## Terms

| Term | Definition |
|------|------------|
| Artifact | Structured unit of work within OpenArtifact; a card on the board. **UI wording:** the interface always says "artifact" (never task, issue or work package). In code, API and database the same thing is still named `task` (`/api/tasks`, table `tasks`); that is an implementation name, not product language. Every artifact has a permanent number (`#12`) that is never reused and can be referenced as `#12` in other artifacts' bodies. |
| Lane | A column of the board. Defined in `BOARD_LANES` (`openartifact/tasks/lanes.py`); lane N always has colour N of the lane palette. |
| Orchestration | TBD — Coordination of workflows and agents. |
| Agent | TBD — Autonomous or semi-autonomous execution entity. |
| Workflow | TBD — Defined sequence of actions within OpenArtifact. |

---

*This chapter follows the arc42 template. All TBD fields are pending definition.*
