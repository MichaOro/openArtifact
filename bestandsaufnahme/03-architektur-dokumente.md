# 3. Architektur-Dokumente und die beiden Generationen der Automatisierung

[Zurück zur Übersicht](../BESTANDSAUFNAHME.md)

*Gegenstand der Analyse:* Owner's own architecture documents in /home/orologas/docs (automation-architecture-activity-audit.md, epic-architecture-feasibility-assessment.md, goal-oriented-orchestration-reuse-assessment.md, github-project-ai-automation.md, github-project-ai-automation-audit.md, opencode-run-profiles.md; home-cleanup-report-2026.md and deep-storage-audit-2026.md skimmed for ops lessons) plus /home/orologas/docs/rollback (9 JSON evidence files, sampled). Read-only; no secrets read; n8n DB not opened (not needed for this slice).

## Überblick

The documents describe TWO generations of automation around the same GitHub Project 5 (owner MichaOro; repos Netrats [a writing/novel-outline project], telemetry, vCardOrologas [coding]).

(1) "github-project-ai" (2026-10-25): a Python poller on a systemd timer (60 s) with SQLite state (meta, item_state, jobs). It watches the Project status field via GraphQL, enqueues a job only on an observed transition to the exact option "Ready for AI", clones the repo in isolation, runs a Copilot CLI starter, validates (structured result, git diff --check, secret scan), commits, optionally pushes/opens a PR, comments, sets "In Review" (never "Done"). Dry-run/baseline/enable flags guard activation. Audit (2026-11-19) finds it NEVER completed a job (2 failed jobs, both on Netrats#4: "needs_human_clarification" and "Agent reported success but the isolated branch has no commit"), timer disabled, last log 2026-10-26. Its only parts judged reusable: secret scan, lock pattern, idempotent transition ledger design.

(2) "AI-Forge" (first script 2026-11-01, active; 295 n8n executions on 2026-11-19, 99.3% success): n8n workflows (GitHub.Agentic.Writing = trigger/queue/launch, GitHub.Agentic.Events = session events/recovery/queue wake, Copilot.ToolGuard = loop guard) + PostgreSQL schema github_automation.* (22 tables: issues, queue, sessions, routing_rules [31 active rules, 8 stages], work_packages, epic_delta, scheduler_setting, triage_decision, session_watch, copilot_events 26k, tool_calls 28k, metric_history/autonomous_loop empty) + ~28 deterministic aiforge-* helper scripts + Codeman (tmux shell sessions) launching `opencode-aiforge --deepseek|--nemotron` (also copilot-squad and claude-opus as fallback) in git worktrees (epic/N, wp/N-issue-M, ai/issue-N). Results: 18 epics, 91 WPs, 84 implemented. Model: Epic -> gap analysis/resolution -> slicing into Work Packages -> WP build/refinement (review/apply cycles) -> WP implement -> code review -> epic finalise -> epic documentation (PR text) -> epic merge check -> PR (never auto-merged). Every stage is a routing rule (stage, action, agent_key, gate, handover_command, branch_mode, depends_mode) evaluated by aiforge-triage. Agents never decide quality: deterministic gate scripts and goal-gate/health-gate steps do. Communication with the human happens through machine-readable GitHub comments with HTML-comment markers (aiforge:progress/question/error/breather/gatecheck/epic-document/merge-needs-human) and issue labels (ai:ready, ai:go, ai:processing, ai:queued, ai:failed, ai:gate-missing, human:review) plus assignee switching (aiForgeAgent <-> MichaOro) as the hand-over protocol.

The owner's two assessment docs (feasibility vs reuse) disagree: the feasibility doc proposed building epic/WP/dependency/phase/iteration tables and a scheduler into the SQLite runner (READY_WITH_WARNINGS); the reuse doc, written same day, finds those already exist in the PostgreSQL pipeline and recommends only a bridge (Option A: epic-labelled items forward to the pipeline queue, others stay single-issue). The audit then concludes the old runner is a dead relic and AI-Forge is the real system. For openArtifact the consolidated reading: the product must reproduce Pipeline B's functions (stage routing table, queue with per-launcher slots, session supervision/recovery, deterministic gates, epic/WP hierarchy, comment contract, handover, epic branch + PR, worktree isolation, telemetry), plus the best ideas of Pipeline A (transition-based idempotent triggers, dry-run/baseline activation, allowlist, secret scan, never-auto-Done) and the owner's unmet requirements (dependency model, epic discovery, operator feedback/progress view, conflict UX, phase/iteration scheduling).

## Fähigkeiten

Verzeichnis: Board-status transition trigger (idempotent, baseline, allowlist); Label/command-based start shortcuts and two-key start; Run profile selection and model/launcher mapping with fallback pairing; Interactive CLI session launch in terminal multiplexer (Codeman/tmux); Isolated execution environment per run (config isolation, identity, permissions); Git isolation: per-run worktree/clone, branch topology, wrapper origin check; Stage/action routing table (pipeline definition as data); Epic / Work Package hierarchy and decomposition; Dependency, phase and iteration scheduling; Execution queue with launcher slots and wake-up; Live session event telemetry and loop guard; Model-error recovery ladder, give-up and context 'breather'; Session supervision: unexpected end, SIGTERM vs stop, resume isolation, model pinning; Deterministic quality gates (gate-check, impl-check, wp-lint, epic-check, merge-check, goal gate, health gate); Structured comment contract and human question/answer loop; Hand-over protocol (assignee + labels as state machine) and work-state labels; Epic finalisation, documentation, PR creation and merge check; Single-issue executor result validation and publishing (Pipeline A); Idempotent per-item state, single-instance locking; Bridge / front-door routing (epic vs single issue); Epic refinement with LLM review and operator notification; Operational hygiene: workflow versioning, rollback, quarantine, log rotation; Operator feedback, status view and metrics (requirement not yet met)

### Board-status transition trigger (idempotent, baseline, allowlist)

- **Was sie tut:** Polls the GitHub Project every 60 s via GraphQL, keeps last-seen status per item, and creates a job only when an item is OBSERVED moving from another option to the exact configured 'Ready for AI' option. First poll only records a baseline (already-ready items do not fire). Rejects unknown repos (allowlist), draft items, PRs, closed issues. Event key is unique per item + status update, so duplicates cannot enqueue twice.
- **Auslöser und Eingaben:** Timer tick; Project status field + option IDs resolved once via read-only GraphQL; config with allowlist and enabled/dry_run flags.
- **Ergebnis und Zustand:** SQLite item_state (last status), jobs (event_key, status pending/running/retry/failed/completed, attempts, error, branch). Log lines state=rejected/running/failed/completed.
- **Fehlerbehandlung:** Rejections logged; non-overlap via process-wide flock; interrupted 'running' jobs reset to 'retry' on next tick; retry with backoff up to max_attempts (3); then error and optional 'Blocked' status. Install is gated: any failing precheck leaves timer disabled; activation failure reverts config to enabled=false, dry_run=true.
- **Externe Systeme:** GitHub Projects v2 GraphQL (webhooks only exist for org projects, so polling chosen for personal project); systemd timer.
- **Abstraktion für das Produkt:** Event/trigger node on a card lane transition (from-any -> specific lane), edge-triggered not level-triggered, with dedupe key (card + transition id), baseline-on-first-run, per-board repository/source allowlist, dry-run mode and safe-activation checklist.
- **Beleg:** github-project-ai-automation.md (Runtime behavior, Host activation sequence); github-project-ai-automation-audit.md Phase B; epic-architecture-feasibility-assessment.md 2.3-2.5; automation-architecture-activity-audit.md E.1

### Label/command-based start shortcuts and two-key start

- **Was sie tut:** Issue start in the live pipeline is label driven: ai:ready alone = 'reserved' (two-key start: needs assignee aiForgeAgent AND ai:ready); label ai:go resets the issue to a clean start state (assignee only the agent, state labels only ai:ready, other labels kept) but only if sender is the owner and issue is open; if already ai:processing only ai:go is removed. Terminal command aiforge-start <nr> [owner/repo] does the same. Restart of a run = assign to agent + ai:ready.
- **Auslöser und Eingaben:** GitHub label event / CLI call; issue ref.
- **Ergebnis und Zustand:** Labels and assignee on the issue; queue row (pending).
- **Fehlerbehandlung:** Idempotent on running issues; sender check prevents foreign triggers.
- **Externe Systeme:** GitHub webhooks into n8n GitHub.Agentic.Writing (nodes 'If: ai:go Labeled?', 'Code: ai:go Issue Ref', 'If: Issue Processing?', 'GitHub: Reset Issue For Run (ai:go)'); aiforge-start script.
- **Abstraktion für das Produkt:** Manual 'Run/Restart' action on a card (button, API, CLI, MCP) with permission check, reset-to-clean-state semantics, idempotent while running; separate 'reserve' vs 'go' states so humans can queue cards without starting them.
- **Beleg:** opencode-run-profiles.md sections 'Start-Abkuerzung', 'Neustart eines Laufs'

### Run profile selection and model/launcher mapping with fallback pairing

- **Was sie tut:** A single-select 'Run Profile' field on the card (e.g. OpenCode:Nemotron, OpenCode:Deepseek, Copilot profiles, Claude) maps to a launcher command plus model endpoint (Code node 'Map Profile to Model Endpoint'). Fallback pairing: Deepseek <-> Nemotron. Different CLI families (copilot / claude / opencode) have family-specific launch, prompt-sending and resume rules. Open question: whether different WPs of one epic may use different models.
- **Auslöser und Eingaben:** Project field value; routing rule agent_key.
- **Ergebnis und Zustand:** queue.launcher, sessions.launcher/model.
- **Fehlerbehandlung:** Fallback launcher chain on model errors (see recovery capability).
- **Externe Systeme:** n8n GitHub.Agentic.Writing nodes 'Code: Map Profile to Model Endpoint', 'Codeman: Launch Copilot Session', 'Codeman: Send Prompt'; LiteLLM (ai-hub) and OpenRouter as providers.
- **Abstraktion für das Produkt:** Executor profiles (CLI + model + provider + context limits + permissions) selectable per pipeline action or card, with declared fallback chain.
- **Beleg:** opencode-run-profiles.md Ablauf, n8n-Aenderungen, Bekannte Grenzen (context windows DeepSeek 70k, Nemotron 425k)

### Interactive CLI session launch in terminal multiplexer (Codeman/tmux)

- **Was sie tut:** n8n starts a Codeman shell session in tmux, runs the launcher (opencode-aiforge) with a pre-chosen session id (AIFORGE_SESSION_ID = copilot_session_id), then sends the one-line prompt, Enter separated. Resume = AIFORGE_RESUME=1 --continue. Codeman web runs on 127.0.0.1:3001 to avoid Grafana's 3000.
- **Auslöser und Eingaben:** Queue claim; worktree path; prompt text; session id.
- **Ergebnis und Zustand:** sessions row (workdir, launcher, model, status active/closed/failed); Codeman session id per attempt.
- **Fehlerbehandlung:** See session supervision. Launcher traps SIGTERM and detaches a watcher so sessionEnd is reported even after SIGKILL.
- **Externe Systeme:** Codeman (tmux), opencode, claude, copilot CLIs.
- **Abstraktion für das Produkt:** Pluggable executor runtime that starts an external agent CLI in a supervised, attachable terminal session with a pre-assigned session id, prompt injection and resume, plus live view for the human.
- **Beleg:** opencode-run-profiles.md Ablauf; github-project-ai-automation-audit.md Phase A; automation-architecture-activity-audit.md D

### Isolated execution environment per run (config isolation, identity, permissions)

- **Was sie tut:** Launcher gives every run its own XDG_CONFIG_HOME-isolated agent config (providers, MCP servers, skills path, permissions), never touching global config. Agent acts under a dedicated bot identity (aiForgeAgent, never the owner): GitHub MCP header, gh token, git author/committer. Token is read at launch and not copied. Autonomous permission set: routine read/edit/bash allowed, small deny-set (sudo, rm -rf, force-push, dd, mkfs, curl|sh, /etc, ~/.ssh, ~/.config, ~/.copilot etc.); denial is an error to the model, never a prompt; last matching rule wins.
- **Auslöser und Eingaben:** Launch.
- **Ergebnis und Zustand:** Config dir aiforge-opencode/xdg; commits/comments authored by bot.
- **Fehlerbehandlung:** Deny = tool error (nothing hangs on a prompt). doom_loop disabled in favour of external loop guard.
- **Externe Systeme:** GitHub identity; opencode.jsonc.
- **Abstraktion für das Produkt:** Per-run sandbox profile: isolated config, scoped credentials/identity, allow/deny tool policy with no interactive prompts, secrets never persisted in run artifacts.
- **Beleg:** opencode-run-profiles.md Identitaet, Autonomer Modus; github-project-ai-automation.md (inherited GITHUB_TOKEN stripped from child processes)

### Git isolation: per-run worktree/clone, branch topology, wrapper origin check

- **Was sie tut:** Pipeline A: isolated clone per issue, deterministic branch ai/project-N-issue-M-<key>, user's dirty worktrees never touched; wrapper scripts refuse a worktree whose origin does not exactly match the repo (exit 2). Pipeline B: git worktrees under ~/worktrees/{repo}/issue-N-<queueid>, branches epic/N (shared by all WPs in epic), wp/N-issue-M, ai/issue-N; epic branch pushed to origin before PR. Feasibility doc explains git rule: one branch per worktree; recommends unique branch per WP, squash-merge WP into epic, serialized merges via per-epic lock, pre-merge dry-run, worktree prune/sweep.
- **Auslöser und Eingaben:** Run start; branch_mode in routing rule (epic-branch for implement/finalise/document/merge stages).
- **Ergebnis und Zustand:** sessions.workdir; branches; aiforge-worktree-sweep cleanup.
- **Fehlerbehandlung:** Orphaned worktrees found 2026-11-19 (143 MB, not in git worktree list); risk R2 orphan worktrees, R3 concurrent epic writes, R10 disk exhaustion; mitigation: prune, verify on startup, per-WP timeout.
- **Externe Systeme:** git, gh.
- **Abstraktion für das Produkt:** Workspace manager: provisions isolated workspace per card/run from a base ref, hierarchical branches (epic base, child branches), integration policy (squash), lock per integration target, cleanup/sweep of orphans, repo identity check.
- **Beleg:** epic-architecture-feasibility-assessment.md 4.1, 6 (risk register), 7.2; goal-oriented-orchestration-reuse-assessment.md 5.1-5.3; deep-storage-audit-2026.md 4.1; github-project-ai-automation.md

### Stage/action routing table (pipeline definition as data)

- **Was sie tut:** 31 active routing_rules in 8 stages define the whole lifecycle as data: epic-refinement (gap-analysis -> gate -> gap-resolution -> gate -> readiness-gate), epic-slicing (wp-slicing -> gate), wp-refinement (review -> gate -> apply -> gate -> readiness -> health; cycle_start flag allows review/apply cycles), wp-building (build -> gate -> health), wp-implementation (implement -> gate -> health -> code-review -> gate; epic-branch), epic-finalisation, epic-documentation, epic-merge (merge-resolve -> goal-gate -> health-gate). Rule columns: use_case, artefact_type (epic vs work_package, detected by label/field), stage, action, agent_key, branch_mode, depends_mode (e.g. position-chain for sequential WPs), handover_command, gate. aiforge-triage evaluates rules and sets next_action; triage_mode 2 = active, triage_llm 0 = deterministic only.
- **Auslöser und Eingaben:** Issue/queue state, stages_done, labels, last result.
- **Ergebnis und Zustand:** issues.stages_done/current_action/lane, triage_decision rows (about 20), queue rows.
- **Fehlerbehandlung:** Defensive-by-default; goal gate routes defects back (e.g. to wp-code-review); scheduler_setting switches (triage_mode, merge_agent_mode, session_watchdog_mode) allow observe-only vs active.
- **Externe Systeme:** PostgreSQL; n8n 'Resolve Action' chain.
- **Abstraktion für das Produkt:** Pipeline = ordered stages of actions per card type, each action bound to an agent role, branch mode, dependency mode, gate and handover command; editable without code; loops/cycles supported; per-stage observe vs enforce mode.
- **Beleg:** automation-architecture-activity-audit.md E.2 routing_rules table and D; goal-oriented-orchestration-reuse-assessment.md 3, 6.3; scheduler_setting table in audit E.2

### Epic / Work Package hierarchy and decomposition

- **Was sie tut:** An Epic is a GitHub issue (label EPIC or 'Artefakt type' field) with child Work Packages (parent_issue_number, work_packages table with status, implemented_at, skeleton JSONB acceptance criteria). aiforge-epic-check validates; aiforge-wp-slicing turns epic into WPs plus skeletons; aiforge-wp-manifest and aiforge-wp-lint prepare/validate WP refinement; aiforge-epic-context supplies epic context. 18 epics, 1-8 WPs each, 91 WPs, 84 implemented. Owner's feasibility doc: GitHub has no native parent/dependency fields; proposes labels epic:N, depends-on:N, blocks:N.
- **Auslöser und Eingaben:** Epic issue in lane agentic-coding; slicing action.
- **Ergebnis und Zustand:** work_packages, epic_delta, issues.parent_issue_number; WP skeleton JSON.
- **Fehlerbehandlung:** WP lint/manifest gates before building; epic with circular deps to be rejected (risk R5, not yet implemented).
- **Externe Systeme:** GitHub issues (parent_issue_added timeline event used), PostgreSQL.
- **Abstraktion für das Produkt:** Two-level card hierarchy (goal card with child cards), generated by an AI 'slice' action, with structured acceptance-criteria skeleton per child and automatic parent/child linking.
- **Beleg:** goal-oriented-orchestration-reuse-assessment.md 2.3, 3, 6.2, 6.4; epic-architecture-feasibility-assessment.md 5.1-5.3; audit E.2 epic table

### Dependency, phase and iteration scheduling

- **Was sie tut:** Owner-specified target: WPs carry dependencies; phase(WP)=max(phase(dep))+1 via topological sort; phases run sequentially, WPs inside a phase parallel; phases with more WPs than max_concurrent split into iterations (3+3+3+1); phase completes when all WPs completed, halts (not fails) if blocked on human, fails if retries exhausted. Existing partial implementation: queue.depends_on JSONB and routing_rules.depends_mode (position-chain => sequential). No cycle validation yet. Dependency format and epic discovery explicitly unspecified (open question).
- **Auslöser und Eingaben:** WP graph per epic; max_concurrent; per-launcher limits.
- **Ergebnis und Zustand:** queue.depends_on, phase/iteration (proposed columns), dependencies table (proposed).
- **Fehlerbehandlung:** Failed WP does not halt other WPs in phase; per-WP retry from last state; DAG validation before scheduling; recommended first prototype = standalone phase scheduler with 8 synthetic WPs.
- **Externe Systeme:** none beyond DB.
- **Abstraktion für das Produkt:** Dependency-aware scheduler for child cards: DAG with cycle detection, auto phase assignment, capacity-bounded iterations, per-card status, partial-failure semantics.
- **Beleg:** epic-architecture-feasibility-assessment.md 4.3, 5.3-5.5, 7.2 Change 5, 10; goal-oriented-orchestration-reuse-assessment.md 3, 4.5

### Execution queue with launcher slots and wake-up

- **Was sie tut:** Queue states pending -> claimed (profile checked, slot taken or parked) -> processing; waiting items get label ai:queued. Rule: at most ONE run per launcher (tool+model) at a time across use cases (two sessions with the same model caused chaos, different models do not); claude-* unlimited; any number may be enqueued. Slot taken atomically via acquire_launcher_slot(queue_id, launcher) with advisory lock; launcher_busy counts open claimed/processing rows; slot kept through retries, moves with fallback launcher, released at handover (done/failed/give-up/session lost). Order: recovery/gatecheck/integrate before new items, then FIFO (queue_order). When a run ends, Events workflow node 'Code: Wake Queue (Run Ended)' calls webhook agenticWritingWake to claim the next waiting item; 'Wake Queue (Slot Released)' wakes old launcher on switch. Safety net: open row with no heartbeat/hook event for 3 h no longer counts as busy. scheduler_setting max_active_runs=2, run_stall_minutes=30, health_check_every=5.
- **Auslöser und Eingaben:** Webhooks from Writing workflow, run-end events.
- **Ergebnis und Zustand:** queue (status, launcher, wp_id, depends_on, use_case, n8n_execution_id), unique constraint (repository, issue, wp_id) for open statuses.
- **Fehlerbehandlung:** Stale-slot timeout; give-up sets issue and queue rows failed but keeps session for next comment; rollback = restore_workflow_version of Writing 9d0ff90e / Events 511ad726; DB extension additive.
- **Externe Systeme:** PostgreSQL advisory locks; n8n.
- **Abstraktion für das Produkt:** Work queue with concurrency pools per executor profile, priorities (recovery before new), atomic slot reservation, wake-on-release, stale-lease expiry, visible 'queued/waiting' state on the card.
- **Beleg:** opencode-run-profiles.md 'Queue-Steuerung: ein Run pro Launcher'; audit E.2 scheduler_setting; goal-oriented ... 2.3

### Live session event telemetry and loop guard

- **Was sie tut:** Agent plugin (aiforge-hooks.js) sends events to n8n with one contract for Copilot/Claude/OpenCode: sessionStart(source new/resume), userPromptSubmitted, agentStop/subagentStop, errorOccurred then stopFailure, preCompact, subagentStart, heartbeat (max 1/min, not reset of error streak), sessionEnd (by launcher). Every tool call passes Copilot.ToolGuard (loop guard): deny blocks the call; read/todowrite exempt; a file edit resets the identical-call counter (false positive fixed Netrats#38). Events land in copilot_events (26k) and tool_calls (28.5k); session_watch (45) tracks stalls; aiforge-session-watch, aiforge-runlog, aiforge-sync-runs, aiforge-host-sample exist (host sampling added 2026-11-18). metric_history table exists but is empty.
- **Auslöser und Eingaben:** Plugin hooks.
- **Ergebnis und Zustand:** copilot_events, tool_calls, sessions, session_watch.
- **Fehlerbehandlung:** Events workflow decides recovery; heartbeat prevents stall false-positives; SIGTERM grace (see below).
- **Externe Systeme:** n8n webhooks GitHub.Agentic.Events and Copilot.ToolGuard; PostgreSQL; Grafana (dashboards inferred from Docker grafana + otel-collector + litellm in cleanup report; dashboards themselves not described in this slice).
- **Abstraktion für das Produkt:** Run event stream per execution (start/prompt/turn end/error/compaction/subagent/heartbeat/tool call/end), tool-call policy hook (loop/risk guard), persisted for audit, metrics and live status on the card.
- **Beleg:** opencode-run-profiles.md Events an n8n, n8n-Aenderungen; automation-architecture-activity-audit.md E.2; home-cleanup-report-2026.md 7 (grafana, otel-collector, litellm containers)

### Model-error recovery ladder, give-up and context 'breather'

- **Was sie tut:** Visible ladder seen in rollback evidence: 'neuer Versuch auf derselben Route 1/2' (same launcher/model, same conversation, after short pause) -> 'automatische Wiederherstellung 1/2, 2/2' (switch to paired launcher e.g. deepseek <-> nemotron, same conversation) -> 'Rueckfallebene Claude' (claude-opus, new conversation, reconstructs state from issue, comments and repo). Each step posts an aiforge:error comment with the raw error JSON, copilot and codeman session ids. Typical provider errors: litellm APIConnectionError / TransferEncodingError mid-stream, 504 upstream idle timeout, after 5 agent-internal retries. Separate 'Verschnaufpause n/3' (aiforge:breather): session compacted 10 times without any subagent finishing = context full/circling; session ended and a fresh conversation continues, not counted as an error. Give-up after errors marks issue and queue rows failed but keeps the session.
- **Auslöser und Eingaben:** errorOccurred/stopFailure series, compaction counter.
- **Ergebnis und Zustand:** Comments, labels (ai:failed), assignee back to owner, queue/issue status failed.
- **Fehlerbehandlung:** Bounded counters 1/2, 2/2, 1/3..3/3; same-launcher retry first, then other launcher, then Claude as last resort.
- **Externe Systeme:** LiteLLM AI Hub, OpenRouter, GitHub comments.
- **Abstraktion für das Produkt:** Configurable failure policy per action: retry-same, switch-executor, fall back to premium executor, context-reset (fresh session continuing from durable state), bounded counters, human-readable status on the card with error payload.
- **Beleg:** rollback/issue-39-comments-before-stop-2026-11-02.json (31 comments), rollback/issue-40-comments-before-rollback-2026-11-02.json (11); opencode-run-profiles.md n8n-Aenderungen

### Session supervision: unexpected end, SIGTERM vs stop, resume isolation, model pinning

- **Was sie tut:** (a) 'Session unerwartet beendet' (aiforge:error): session ended while agent was working (crash, Codeman restart, model stopped) with no final report -> issue marked failed, assigned back to owner. (b) External SIGTERM (Codeman/n8n stop) made OpenCode emit session.idle, which the plugin turned into agentStop and n8n started gate check/follow-up for a run someone just stopped; fix: plugin delays agentStop by AIFORGE_STOP_GRACE_MS (2.5 s), then only sessionEnd arrives; a signal handler in plugin is impossible (not main thread). (c) opencode --continue picked the globally latest session, so parallel runs received other issues' prompts (Netrats#39/#40/#50, 2026-11-02); launcher now resolves --session <id> of latest session whose directory = worktree (read-only SQLite lookup). (d) TUI --continue kept the old model; fix: AIFORGE_MODEL set on each user message in chat.message. (e) aiforge-resume-check and aiforge-opencode-recycle exist for resume/recycle; sessionEnd sent exactly once via marker file claim.
- **Auslöser und Eingaben:** Process signals, session events.
- **Ergebnis und Zustand:** sessions status closed/failed; 19 sessions on 2026-11-19, 3 failed; contaminated session evidence rollback/opencode-session-issue-40-contaminated-2026-11-02.json (93 messages, 2.46M input tokens).
- **Fehlerbehandlung:** Rollback of issue #40 and cleanup of #39 on 2026-11-02 (state captured as before-rollback/before-cleanup snapshots: assignee, labels, state, comments, timeline).
- **Externe Systeme:** opencode SQLite data dir, Codeman, n8n Events workflow.
- **Abstraktion für das Produkt:** Execution sessions bound strictly to a card/workspace (never 'latest global'), exactly-once end event, distinguish operator stop from crash, pin model per run, session resume by explicit id, supervised timeouts/stall detection (run_stall_minutes 30).
- **Beleg:** opencode-run-profiles.md sections Fortsetzung, Modellwahl, Abbruch von aussen (SIGTERM); rollback folder; automation-architecture-activity-audit.md E.2 sessions

### Deterministic quality gates (gate-check, impl-check, wp-lint, epic-check, merge-check, goal gate, health gate)

- **Was sie tut:** Helper scripts produce machine-readable JSON verdicts, no LLM: aiforge-wp-lint (WP quality), aiforge-impl-check (post-implementation validation incl. same SECRET_PATTERNS as the old runner), aiforge-epic-check (finalisation validation, 27 KB), aiforge-merge-check (5 checks: no open MERGE_HEAD; base is ancestor of HEAD; no conflict markers; clean tree and HEAD==origin/branch; PR mergeable via REST with 60 s wait; exit 0 ok / 1 defects / 2 call error / 3 agent-aborted; prints 'AIFORGE merge-check {json}'). Live gate check on the writing use-case: required gates by numbered rules, e.g. rule 16 'final report, question or marked answer must exist', rule 17 'Quality Auditor must run after last result of an author agent'; on miss: 'Gate-Pruefung: Pflicht-Gates fehlen - automatischer Nachlauf 1/2, 2/2' (coordinator runs only missing gates and republishes final report), then label ai:gate-missing and hand-over to human (restart with ai:ready). implementation_ready_threshold = 95 (readiness %). Without the Squad framework (OpenCode profile) the gate only demands the marked final comment.
- **Auslöser und Eingaben:** Run end (agentStop), handover_command in routing rule.
- **Ergebnis und Zustand:** Gate comments, labels, stages_done.
- **Fehlerbehandlung:** Max 2 automatic follow-ups, then human; defects route back to code-review; defensive default (uncertain = fail).
- **Externe Systeme:** git, GitHub REST, PostgreSQL.
- **Abstraktion für das Produkt:** Gate step type: deterministic validator with structured verdict (pass/defects/error/aborted), bounded auto-retry of missing gates, escalation to human, readiness score threshold; both code-quality and content-quality (writing) variants.
- **Beleg:** goal-oriented-orchestration-reuse-assessment.md 4.1-4.5; audit D and E.2; rollback issue-39/40 comments (aiforge:gatecheck, label ai:gate-missing in issue-39-state-before-cleanup-2026-11-02.json); opencode-run-profiles.md Bekannte Grenzen

### Structured comment contract and human question/answer loop

- **Was sie tut:** All agent output is typed GitHub comments with HTML-comment markers: aiforge:progress (e.g. 'Atom A1 abgeschlossen' with changed files and commit), aiforge:question (numbered questions F1..Fn with checkbox options A-D and a marked recommendation, plus a proposal body), aiforge:error, aiforge:breather, aiforge:gatecheck, aiforge:epic-document (PR title/description), aiforge:epic-merge-resolve, aiforge:merge-needs-human. Human answers by ticking boxes or posting a decision document; next run reads all comments (plugin raises comment page size to 100 and warns on full pages after Netrats#38 where page-2 decisions were missed). Scripts aiforge-comment and aiforge-comment-contract.mjs (16 KB) validate the contract. Work is split into small 'atoms' (A1..A5), each committed and pushed with progress comment.
- **Auslöser und Eingaben:** Agent output; human comment.
- **Ergebnis und Zustand:** Comment thread is the durable conversation; also handover-sync (aiforge-handover-sync) and aiforge-issue.
- **Fehlerbehandlung:** Pagination fix; assignee/label hand-over after each run.
- **Externe Systeme:** GitHub issue comments API/MCP.
- **Abstraktion für das Produkt:** Typed card activity feed (progress, question with options and recommendation, error, gate result, document) with schema validation, answer widgets, paging-safe retrieval, per-atom progress entries.
- **Beleg:** rollback/issue-39-comments-before-stop-2026-11-02.json, issue-40-comments-before-rollback-2026-11-02.json; opencode-run-profiles.md Kommentar-Pagination; automation-architecture-activity-audit.md E.2 (aiforge-comment-contract.mjs)

### Hand-over protocol (assignee + labels as state machine) and work-state labels

- **Was sie tut:** Run ownership is signalled by assignee (aiForgeAgent while running, MichaOro after hand-over) and state labels ai:ready, ai:queued, ai:processing, ai:failed, ai:gate-missing, human:review, ai:go. After hand-over the issue is assigned to the owner; restart needs agent assignment plus ai:ready. Project status options: Backlog, Ready for AI, In progress, In review, Done; Done is never set automatically.
- **Auslöser und Eingaben:** Run end/give-up/session lost.
- **Ergebnis und Zustand:** Labels, assignee, Project status; timeline events project_v2_item_status_changed, assigned/unassigned, labeled/unlabeled (issue #39 timeline: 11 status changes, 18 label changes, 10 assignments, 30 comments).
- **Fehlerbehandlung:** State snapshots saved before manual rollback to restore labels/assignee exactly.
- **Externe Systeme:** GitHub issues/projects.
- **Abstraktion für das Produkt:** Explicit run-state and ownership model on the card (agent-owned vs human-owned), human-in-the-loop hand-over, no auto-Done (human acceptance).
- **Beleg:** opencode-run-profiles.md; rollback/*state-before*.json; github-project-ai-automation.md

### Epic finalisation, documentation, PR creation and merge check

- **Was sie tut:** After all WPs are implemented: epic-finalise (validation via aiforge-epic-check), epic-document (documenter writes PR title and description in an aiforge:epic-document comment), document gate, aiforge-epic-pr creates PR epic/N -> default branch (idempotent, does not overwrite existing PR, bot as author, owner as assignee/reviewer, never merges), epic-merge stage runs merge-check and posts aiforge:epic-merge-resolve table. aiforge-epic-delta persists the residual 'delta' (offen/abweichend/seiteneffekt, status offen/info-epic/akzeptiert/erledigt) so deviations are tracked; goal completion = all WPs implemented_at set plus epic_delta resolved. Final merge to main is manual by design.
- **Auslöser und Eingaben:** Epic stage completion.
- **Ergebnis und Zustand:** PR, epic_delta rows (<10), comments.
- **Fehlerbehandlung:** Merge-needs-human comment if merge aborted; known gap: cross-WP conflict resolution not handled by resolver; push-to-origin timing undocumented.
- **Externe Systeme:** GitHub REST/gh.
- **Abstraktion für das Produkt:** Goal completion workflow: aggregate children, validate, generate release/PR description, create review request, track residual deltas, human merge approval.
- **Beleg:** goal-oriented-orchestration-reuse-assessment.md 4, 5, 6.2; automation-architecture-activity-audit.md B/E.2

### Single-issue executor result validation and publishing (Pipeline A)

- **Was sie tut:** Agent told not to commit/push/deploy; must return a structured AUTOMATION_RESULT_JSON with success/tests; runner then checks, git diff --check, regex secret scan (6 patterns), commits in isolated clone, optionally pushes and opens a PR, posts result comment, sets 'In Review'; 'Blocked' after retry limit; 'Done' never.
- **Auslöser und Eingaben:** Agent result.
- **Ergebnis und Zustand:** jobs row, PR, comment.
- **Fehlerbehandlung:** Failure seen live: 'Agent reported success but the isolated branch has no commit' (3 attempts) and 'needs_human_clarification' - never succeeded in 2 jobs.
- **Externe Systeme:** Copilot CLI starters (copilot-litellm for Netrats/telemetry, copilot-openrouter for vCard), gh.
- **Abstraktion für das Produkt:** Executor contract: agent returns structured result; platform (not agent) verifies diff, scans for secrets, commits, publishes; detects 'claimed success but no change'.
- **Beleg:** github-project-ai-automation.md; automation-architecture-activity-audit.md E.1, F.7; goal-oriented-orchestration-reuse-assessment.md 2.2

### Idempotent per-item state, single-instance locking

- **Was sie tut:** Pipeline A: SQLite ledger with unique event key and process-wide flock (non-blocking). Pipeline B: unique constraint on (repository, issue_number, wp_id) for open queue statuses, advisory locks for slot acquisition, per-epic merge lock proposed.
- **Auslöser und Eingaben:** -
- **Ergebnis und Zustand:** unique keys, lock files.
- **Fehlerbehandlung:** Locks prevent overlap; recover running->retry.
- **Externe Systeme:** SQLite/PostgreSQL.
- **Abstraktion für das Produkt:** Exactly-once enqueue per (card, transition), per-resource mutex, crash-safe recovery of in-flight jobs.
- **Beleg:** github-project-ai-automation.md; epic-architecture-feasibility-assessment.md R3/R7; goal-oriented ... R7

### Bridge / front-door routing (epic vs single issue)

- **Was sie tut:** Recommended Option A: keep the board poller as the 'front door'; if the item has label epic (or Artefakt type = EPIC) forward it as a queue row (use_case agentic-coding, first action epic-refinement) into the pipeline DB, otherwise run as single issue; fallback to single-issue if DB down; epic takes precedence over other labels. Rejected: separate orchestration layer (Option B) and replacing the poller (Option C). In the end the audit found the poller dead and the n8n pipeline the real entry.
- **Auslöser und Eingaben:** Ready transition + label/field.
- **Ergebnis und Zustand:** queue row, issues row (open question whether bridge writes the issues ledger).
- **Fehlerbehandlung:** Bridge failure logged, item stays 'Ready for AI' and is retried next poll.
- **Externe Systeme:** PostgreSQL, n8n.
- **Abstraktion für das Produkt:** Single intake that classifies a card (type) and routes it to the appropriate pipeline definition; single-card flow and goal flow are the same engine with different pipelines.
- **Beleg:** goal-oriented-orchestration-reuse-assessment.md 8, 9, 10, 11

### Epic refinement with LLM review and operator notification

- **Was sie tut:** n8n workflow llm-epic-review (TS source, plus minimal variant) lets an LLM review epics for unresolved questions and notifies the operator via Telegram. Routing stage epic-refinement does gap analysis, gap resolution and readiness gate (threshold 95%).
- **Auslöser und Eingaben:** Epic issue.
- **Ergebnis und Zustand:** Gap comments, readiness.
- **Fehlerbehandlung:** Not documented here.
- **Externe Systeme:** Telegram, LLM via n8n.
- **Abstraktion für das Produkt:** Pre-execution readiness review of a goal card with open-question extraction, readiness score, and notification channel to the owner.
- **Beleg:** goal-oriented-orchestration-reuse-assessment.md 2.4, 3; epic-architecture-feasibility-assessment.md 8 (Telegram + GitHub comments as operator feedback)

### Operational hygiene: workflow versioning, rollback, quarantine, log rotation

- **Was sie tut:** n8n workflow changes are tracked by version ids with documented 'davor' versions; rollback via restore_workflow_version then publish_workflow; update_workflow only saves a draft (pitfall). Before risky project changes the owner backs up all field values and verifies afterwards unchanged. Manual rollback of runs captured issue comments, timeline and state JSON, plus the contaminated opencode session. Cleanup used move-to-quarantine (30 days review) instead of delete, protected-list (n8n, repos, secrets), validation of services after. Open items: n8n SQLite 462-482 MB (VACUUM script bin/n8n-shrink-db), event logs 40 MB / 148k lines unrotated, orphaned worktrees 143 MB, opencode package cache 2.4 GB, duplicate node_modules, root filesystem 70%, credentials left in plain text (.bashrc token removed 2026-10-25; backup/secret files noted).
- **Auslöser und Eingaben:** manual
- **Ergebnis und Zustand:** rollback JSONs dated 2026-11-02; quarantine dir 2026-11-19.
- **Fehlerbehandlung:** -
- **Externe Systeme:** n8n, docker (litellm, grafana, otel-collector, openrouter-normalizer), systemd units (n8n, codeman-web, opencode-adapter, openrouter-discovery-worker).
- **Abstraktion für das Produkt:** Versioned pipeline definitions with draft/publish and one-click restore; run snapshot/undo (restore card state); retention/rotation policy for run logs and workspaces; secret hygiene.
- **Beleg:** opencode-run-profiles.md n8n-Aenderungen, GitHub-Projekt; rollback folder file names; home-cleanup-report-2026.md; deep-storage-audit-2026.md 5, 4.1

### Operator feedback, status view and metrics (requirement not yet met)

- **Was sie tut:** Owner's open question: how does the operator see phase progress, merge conflicts and WP statuses (Telegram / GitHub comments / web UI)? Today: GitHub comments, Telegram for epic review, queue/session tables, Grafana (dashboards AI Usage and AI Pipeline Control Center referenced by the task but NOT described in this slice). Tables metric_history and autonomous_loop exist but are empty; session_watch and aiforge-host-sample collect host load.
- **Auslöser und Eingaben:** -
- **Ergebnis und Zustand:** copilot_events, tool_calls, sessions, scheduler_setting.
- **Fehlerbehandlung:** -
- **Externe Systeme:** Grafana, Telegram, otel-collector, LiteLLM usage.
- **Abstraktion für das Produkt:** Built-in run/epic dashboard: stage progress, queue/slot occupancy, per-model usage/cost, error ladders, stalls, conflict list; notification channels.
- **Beleg:** epic-architecture-feasibility-assessment.md 8 Q5; automation-architecture-activity-audit.md E.2, G; home-cleanup-report-2026.md 7

## Schmerzpunkte und Lehren

- Pipeline A was built and then never produced a completed job: 2 failed jobs, both Netrats#4 ('needs_human_clarification'; 'Agent reported success but the isolated branch has no commit' x3). Lesson: trust platform-side verification of the diff, not agent claims, and prove one end-to-end run before enabling a timer (audit E.1, F.2).
- Two independent systems (SQLite poller vs n8n+PostgreSQL pipeline) served the same Project and repos with no shared state, scripts or trigger; duplicated concepts and a dead relic left loaded/disabled. The two same-day assessments contradict each other (feasibility says epics/phases do not exist; reuse says they fully exist in Postgres). Lesson: one engine, one data model; keep docs current; ask 'what already exists' first (audit D/E.3; reuse assessment 1).
- Activation of the first system was blocked by environment problems: invalid GITHUB_TOKEN exported in .bashrc (removed), sandbox could not reach api.github.com or user systemd bus; Codeman port clashed with Grafana (3000 vs 3001 fix). Lesson: credentials hygiene, preflight checks, explicit port management, safe-by-default config (enabled=false, dry_run=true) (github-project-ai-automation-audit.md).
- GitHub limitations drive workarounds: projects_v2_item webhooks only for org projects (hence polling); no native parent/dependency fields (labels or DB needed); MCP comments paginated 30/page oldest-first so models missed decisions on page 2 (Netrats#38). Lesson: first-class dependencies and a paging-safe activity feed in the product.
- Parallel runs contaminated each other: opencode --continue resumed the globally last session, so prompts of #39 and #50 landed in #40's session (2026-11-02, evidence file opencode-session-issue-40-contaminated). Also, two sessions on the same model caused 'chaos' -> one-run-per-launcher slot rule. Lesson: strict session-to-workspace binding and per-executor concurrency limits.
- Model drift: --continue kept the previous model so a profile switch silently ran the old model (Netrats#38 runs 210/211 labelled DeepSeek but ran Nemotron). Lesson: record and enforce the actual model per run and show it.
- Stop vs crash ambiguity: SIGTERM-ed runs emitted session.idle -> agentStop, which triggered gate checks and follow-ups for a run the operator had just stopped; then sessionEnd mid-turn was interpreted as 'session lost' (issue failed, assigned to owner). Fix was a 2.5 s grace delay. Not end-to-end tested: loop-guard block, compaction on long runs, recovery after stopFailure.
- Provider instability is the dominant failure: AI Hub/LiteLLM streams cut mid-response (TransferEncodingError, 504 idle timeout) even after 5 internal retries; on issues #39/#40 the ladder (same route x2 -> other model x2 -> Claude) ran repeatedly, interleaved with 'breather' context resets (10 compactions without subagent completion) and 'session unexpectedly ended' events. Context windows are small (DeepSeek 70k). Lesson: failure ladder with bounded counters and context-reset are core features, and tasks must be sliced into atoms with durable progress.
- Loop guard false positive: identical non-edit tool calls after each edit were flagged; fixed by resetting counter on any file change. Heartbeat must not reset error streak. Lesson: guard heuristics need tuning knobs and tests.
- Gate misses are common on the writing use-case: required quality auditor/final report missing after run (rules 16/17); two automatic follow-ups then ai:gate-missing and human restart. Squad roles (Quality Auditor, canon-steward, outline-architect) only exist for Copilot; the OpenCode profile has no sub-agent roles and gates only on the marked final comment. Lesson: gates must be executor-independent.
- n8n platform pitfalls: update_workflow saves only a draft until publish_workflow; DB grew to 462-482 MB with 130k+ executions and event logs unrotated; 4 stale September workflows still active; custom node version drift (jada 0.4 vs 0.7). Lesson: engine-owned run retention, versioned definitions with publish semantics, no stale active definitions.
- Data model hygiene: metric_history and autonomous_loop tables empty; counts inconsistent across docs (3 vs 2 failed jobs; 2,777 sessions vs 2,708 'done' issues); several numbers marked estimated. Treat figures as indicative.
- Workspace sprawl: orphaned worktrees (143 MB, git worktree list empty), duplicated node_modules/.opencode per worktree, 2.4 GB opencode package cache, 40 MB event logs, 3.9 GB global node_modules. Lesson: automatic worktree sweep, shared dependency caches, retention policy (cleanup report: quarantine for 30 days, protected list).
- Secrets handling debt: tokens in shell rc (removed), secret backups/admin login file in home, shared bot token used by Copilot and OpenCode (same token, deliberately not copied). The bot identity (aiForgeAgent, never owner) is a deliberate guardrail.
- Owner-stated requirements for a better system (feasibility 'Why not READY' and open questions): (1) define dependency label/field format and validation incl. cycle detection; (2) decide epic branch push policy (local-only vs origin) and who may merge to main; (3) specify epic discovery (label, comment or manual); (4) operator feedback loop for phase progress, conflicts and WP status (Telegram, comments or web UI); (5) conflict-resolution UX (manual, suggestion, rerun WP); (6) per-WP model choice within an epic; (7) epic completion criteria (all WPs done vs manual approval); (8) whether PRs per WP or only epic->main; (9) whether orchestration lives in n8n or the runner; (10) prototype the phase scheduler standalone first with 8 synthetic WPs and conflict tests.
- Design principles the owner documented: never auto-merge and never auto-set Done; agents do not self-certify (deterministic scripts and gates decide); defensive-by-default (uncertain = fail); idempotent transitions with baseline; allowlist of repos; additive DB changes with documented rollback ids; use-case-agnostic engine (same pipeline used for coding and for novel/outline writing); bot identity separate from owner; autonomous runs must never block on a prompt.
- Risk register items to carry over: merge conflicts across WPs (squash default, dry-run merge, per-epic lock), orphaned worktrees, launcher slot exhaustion, dependency cycles, model context contamination, SQLite/DB races, epic branch divergence from main (rebase before phase), resource exhaustion (per-WP timeout, concurrent worktree limit), worktree boundary escape, GitHub rate limits from parallel polling.

## Offen / nicht belegt

- Grafana dashboards AI Usage and AI Pipeline Control Center are not described in any document of this slice; only the Grafana/otel-collector/litellm containers are mentioned in the cleanup report. Panel content, metrics and data sources are unknown here.
- Exact n8n node graphs, webhook paths and credentials are not in these docs (workflow names, a few node names and version ids only); to be taken from the n8n DB slice.
- Contents of the aiforge-* scripts are only described by name, size and docs; the claim 'all deterministic, no LLM' comes from the audit and was not verified by reading the scripts.
- Whether github-project-ai was intentionally superseded is undocumented (audit section G); who wrote it is unknown. Why Copilot is called 'no longer used' while rollback evidence of 2026-11-02 shows copilot-squad runs before switching to opencode-aiforge on the next day is inferred as a migration, not documented.
- Where exactly the epic branch push to origin happens (WP implementation vs finalisation) is called a documented gap in the reuse assessment.
- parallel-wp-execution*.md and parallel-wp-e2e-verification.md exist in the same folder but are outside this slice, so the actual parallel WP implementation state is not covered here.
- Writing use-case (Netrats outlines, Squad framework, canon, quality auditor) is visible only through rollback comments; its full spec is not in these docs.
- Numbers (sessions, issues, failed job count) are inconsistent between documents; the 99.3% success rate and 295 executions come from the audit without shown query.
