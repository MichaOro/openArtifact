# 5. Hilfsskripte (deterministische Gates, Kontextbau, Betrieb)

[Zurück zur Übersicht](../BESTANDSAUFNAHME.md)

*Gegenstand der Analyse:* Operational helper scripts in /home/orologas/bin: aiforge-* (without the parallel-wp / wp / worktree / merge family), aiforge_decisions.py, opencode-aiforge, github-project-ai, n8n-shrink-db, copilot-*, claude-* launchers, mcp-* wrappers, telemetry-*/netrats-*/vcard-* launchers (46 files), plus their n8n call sites, systemd timers and the owner's docs that explain them.

## Überblick

The slice is a toolbox of small deterministic scripts that sit around the LLM agent runs of the owner's AI-Forge pipeline (n8n + GitHub issues and a GitHub Project board + Postgres schema github_automation + OpenCode runs inside Codeman/tmux sessions). They are not the orchestrator: n8n (workflows GitHub.Agentic.Coding / .Events / .Writing) calls them over SSH, the run launcher starts them as detached watchers, or systemd timers run them. They fall into seven families: (1) card-state primitives (labels, assignees, board fields, comments, run start, resume gate); (2) routing and self-healing (triage, healer, mode switches, decision log); (3) context builders that hand an agent a narrow, current input pack; (4) quality gates that decide pass/fail by script instead of by the model (impl-check, epic-check plan/side-effect/metric checks, result-contract validators with evidence check, model probe); (5) run supervision and runtime hygiene (opencode-aiforge launcher, session-end, session-watch + digest, recycle, host-sample, oac-config); (6) reporting and visibility (run-log comment, run counter, hand-over mirror, Grafana feeds); (7) launchers, secret handling and ops (copilot-*, claude-*, mcp-*, per-project launchers, n8n-shrink-db, legacy github-project-ai). Common design: almost every helper ends with one machine-readable last line (AIFORGE <json>) and mostly exits 0; context builders and reporters fail open (never stop the run), gates fail closed with explicit reasons; every new automation is rolled out in modes off/observe/act; verdicts on measurable facts come from scripts, not from the model. Status seen today: n8n call sites exist for triage, resume-check, project, issue, comment, runlog, epic-context, epic-check (context and pr), epic-delta, epic-pr (via routing_rules.handover_command), review-context, impl-check (via routing_rules.check_command), session-watch (via the launcher's detached watcher) and the launcher itself. systemd timers are enabled only for host-sample and sync-runs; session-watch.timer and github-project-ai.timer are disabled; the n8n node that called opencode-recycle is disabled and unconnected; handover-sync, triage --sweep, triage-switch, model-probe, oac-config, start and n8n-shrink-db have no scheduler or caller (manual tools).

## Fähigkeiten

Verzeichnis: STATE: Terminal one-step run start (two-key start); STATE: Ordered, idempotent label/assignee transitions as the bot (REST); STATE: Typed board fields get/set with auto-add and schema cache; STATE: Terminal 'Done' clears the card; STATE: Bot-identity comment API (post, edit, list-all, replace body); STATE: Resume gate after a health pause (needs new human input); GATE: Result-contract enforcement at write time; GATE: Per-action result-contract validators and evidence check; ROUTING: Next-action triage before dispatch (rules engine); ROUTING: Healer for invalid, stale or missing next_action; ROUTING: Optional LLM arbitration of contradictory state; ROUTING: Rollout modes and operator switch (off / observe / active); ROUTING: Decision audit log and notification de-duplication; ROUTING: Sweep of stuck cards (healer only); CONTEXT: Narrow input pack for epic clarification; CONTEXT: Review minifest with diff and machine findings; CONTEXT: Finaliser inputs with discovered tool manifest; CONTEXT: Pull-request context pack for the documenter; GATE: Implementation run completeness preflight; GATE: Regression check against a cached baseline (type check, tests, build); GATE: Test-case traceability (TC-n to named tests, manual declaration); GATE: Pseudo-test and fake-coverage detection; GATE: Pipeline-artifact leak and PR hygiene checks; GATE: Red/green verification report as the judged result; GATE: Epic acceptance-plan validation (grounded in the spec text); GATE: Whole-epic side-effect scan against the default branch; GATE: Measured acceptance criteria and metric history; GATE: Functional criteria bound to named tests; GATE: Spec-to-delta persistence and informational follow-up card; STATE: Deterministic pull-request opening from the documenter's text; GATE: Decision-traceability helper (user decisions must reach the spec); GATE: Model admission probe (three-task eligibility test); SUPERVISION: Live run digest (loop, error, context and progress facts); SUPERVISION: Session watchdog judge with matrix guard (off / observe / act); SUPERVISION: Watchdog actions (nudge, in-place restart), record and notification policy; RUNTIME: Agent run launcher with isolation and split identity; RUNTIME: Per-workspace session resume and per-message model pin; RUNTIME: Continue the same conversation after a provider abort; RUNTIME: Exactly-once, kill-proof end-of-run signal; RUNTIME: Per-run temp directory with guaranteed cleanup; RUNTIME: Idle-aware recycle of a leaking shared agent server with drain; OPS: Host sampler and back-pressure signal; RUNTIME: Unattended-agent profile derived from an interactive agent (OAC); RUNTIME: Hand-over file contract in the run workspace; CROSS: Stage hook model as seen from the scripts; REPORTING: One run-log comment per run (state-in-comment, folded reports); REPORTING: Run counter mirrored to the board; REPORTING: 'Waiting for you' hand-over mirror; REPORTING: Dashboards fed by this slice (Grafana) and the gaps; CROSS: Uniform helper result protocol and fail-open / fail-closed policy; CROSS: Secret handling pattern for launchers and helpers; LAUNCHER: Copilot run profiles with per-model prompt caps (squad / plain); LAUNCHER: Isolated Claude Code profiles through the gateway (qwen / free / private) and telemetry header; LAUNCHER: Per-project launchers with repository allow-list guard; LAUNCHER: Secret-injecting MCP tool-server wrappers; OPS: n8n execution-history shrink with backup and automatic rollback; LEGACY: Board-status poller with baseline, idempotency, allow-list and secret scan

### STATE: Terminal one-step run start (two-key start)

- **Was sie tut:** aiforge-start <issue> [owner/repo] (or owner/repo#n; default repo from env or the main project repo) refuses anything that is not an OPEN issue, then in ONE gh call assigns the bot account aiForgeAgent and adds label ai:ready. The assignee goes first because the labeled-ai:ready event is the actual start and the n8n guard needs the agent already assigned when it arrives. Same effect as the ai:go label shortcut. Stale state labels (human:review, ai:failed ...) are replaced by n8n at run start; the Run Profile (model cluster) comes from the board field, not from the script. ai:ready alone only pre-marks a card (documented 'Vormerken').
- **Auslöser und Eingaben:** Manual CLI by the owner; args: issue number, optional repo. Equivalent GitHub label ai:go is handled by n8n GitHub.Agentic.Coding nodes 'Switch: Pre-Gate (epic + ai:ready + aiForgeAgent)' and 'Code: ai:go Command'.
- **Ergebnis und Zustand:** Issue gets assignee + label ai:ready, which fires the GitHub webhook into the Coding workflow.
- **Fehlerbehandlung:** set -e; issue not OPEN -> message and exit 1; no retry logic.
- **Externe Systeme:** GitHub (gh CLI under the owner's login).
- **Abstraktion für das Produkt:** [core] 'Start run' command on a card (UI button, CLI, API, MCP tool): sets the card ready-for-agent through an explicit two-part trigger (agent assignment plus ready flag applied last), rejects closed/finished cards, takes the run profile from a card field, and lets the runtime clear stale hand-over flags at start.
- **Beleg:** /home/orologas/bin/aiforge-start:4-28; /home/orologas/docs/opencode-run-profiles.md sections 'Start-Abkürzung' and 'Neustart eines Laufs'

### STATE: Ordered, idempotent label/assignee transitions as the bot (REST)

- **Was sie tut:** aiforge-issue <owner/repo> <n> [--add-label L].. [--remove-label L].. [--add-assignee U].. [--remove-assignee U].. | --clear. All calls use the GitHub REST API as the bot account (own rate limit, no GraphQL cost). Fixed order: remove labels, remove assignees, add assignees, add labels, so a trigger label is set last. A label that is already gone (404) is not an error; every call is still attempted and exit code 1 reports any other failure. --clear removes ALL labels and ALL assignees. Side effect: adding or removing human:review, human:question or ai:pr-ready inserts/deletes a row in github_automation.handover_open (errors swallowed) for the 'waiting for you' list.
- **Auslöser und Eingaben:** Called by n8n over SSH at every transition: 'SSH: Mark Issue Started/Queued/Failed (Coding)/Stopped', 'Code: Handover Commands (Valid)/(Failed)/(WP Done)', 'SSH: Triage Handover', 'SSH: Start Sub-Issue/Finish Sub-Issue/Hand Over Sub-Issue (Failed)', 'Code: ai:go/ai:slice/ai:accept Command' (about 15 distinct nodes in GitHub.Agentic.Coding and .Events); also called by aiforge-resume-check and aiforge-project (Done).
- **Ergebnis und Zustand:** Labels and assignees on the issue; handover_open rows; stdout 'ok' / 'ok cleared'.
- **Fehlerbehandlung:** Per-call stderr captured (first 200 chars); rc=1 on any non-404 failure; handover bookkeeping never aborts.
- **Externe Systeme:** GitHub REST (bot token read from the copilot MCP config file); Postgres schema github_automation.
- **Abstraktion für das Produkt:** [core] State-transition primitive on a card: add/remove flags and assignees in one request with a defined order (trigger flag last), idempotent on absent flags, per-call failure reporting, a clear-all transition for terminal cards, and automatic upkeep of a 'waiting for human' index when hand-over flags change. Automation acts under a service identity with its own API quota.
- **Beleg:** /home/orologas/bin/aiforge-issue:4-84 (order 54-66, clear 39-50, handover tracking 71-82); n8n workflows GitHub.Agentic.Coding and GitHub.Agentic.Events, nodes listed above

### STATE: Typed board fields get/set with auto-add and schema cache

- **Was sie tut:** aiforge-project [--owner L] [--project N] get|set <owner/repo> <n> [<field> <value>]. get returns {itemId, fields{name:value}} (single select as option NAME, text, number; issue not on the board -> {itemId:null, fields:{}}). set adds the issue to the project if needed and writes a Text, Number or Single-select field by option name; empty value clears; unknown field or option is an error (exit 1). A per-project cache (~/.cache/aiforge-project: project id, field list, data types, item ids) makes a cached set cost ONE GraphQL call instead of four; stale ids drop the cache and the call is repeated once. Runs under the owner's gh login because the bot token has no project access. Default owner/project number are hard-coded.
- **Auslöser und Eingaben:** n8n 'SSH: Read Project Fields' (get, before triage/resolve action) and many 'set Status Ready / In progress / Done' calls at start, queued, hand-over, failed, stopped; aiforge-triage uses get.
- **Ergebnis und Zustand:** JSON on stdout; board values: Status (Ready, In progress, Done), Run Profile, Läufe, Stage. Stage/Action/Iteration/Next Action are no longer written to the board (kept in DB/Grafana, comment in 'Code: Handover Commands (Valid)').
- **Fehlerbehandlung:** GraphQL failure -> exit 1; n8n 'Code: Resolve Action' throws on a failed get, most set calls are wrapped with || true.
- **Externe Systeme:** GitHub Projects v2 GraphQL through gh.
- **Abstraktion für das Produkt:** [core] Typed custom fields on cards (text, number, single-select) addressable by name and option label through API/CLI/MCP, with the card joining the board on first write; a status column is just a select field. In a native board the cache/GraphQL tricks vanish, but 'unknown field/option is an error' and 'empty clears' stay.
- **Beleg:** /home/orologas/bin/aiforge-project:4-172 (fetch_item 53-79, set 91-165); n8n nodes 'SSH: Read Project Fields', 'Code: Resolve Action', 'Code: Handover Commands (Valid)'

### STATE: Terminal 'Done' clears the card

- **Was sie tut:** When aiforge-project sets field Status to Done (unless AIFORGE_DONE_KEEP=1) it calls aiforge-issue --clear: all labels and all assignees are removed and handover bookkeeping is deleted, so a finished issue carries nothing. Callers must set Done as their LAST step; hand-over flows deliberately set Ready instead so labels survive.
- **Auslöser und Eingaben:** Any 'aiforge-project set <repo> <n> Status Done' (n8n 'SSH: Finish Sub-Issue', 'Code: ai:accept Command').
- **Ergebnis und Zustand:** Clean issue; handover_open rows removed.
- **Fehlerbehandlung:** If clearing fails, stderr message 'Done gesetzt, Labels/Assignees nicht vollständig entfernt'; Done stays set.
- **Externe Systeme:** GitHub REST/GraphQL, Postgres.
- **Abstraktion für das Produkt:** [core] Lifecycle rule: moving a card to its terminal state clears all transient run flags and assignees, while hand-over states keep them; needs an explicit keep-flags escape.
- **Beleg:** /home/orologas/bin/aiforge-project:166-170; /home/orologas/bin/aiforge-issue:39-50; n8n 'Code: Handover Commands (Valid)' comment 'Status Done is never set here'

### STATE: Bot-identity comment API (post, edit, list-all, replace body)

- **Was sie tut:** aiforge-comment post|edit|list|issue-body. All calls run as the bot, never as the owner. post prints the comment URL; edit replaces a comment by id; list returns a JSON array {id, author, created_at, body} across ALL pages (100 per page), optionally only created_at >= --since ISO8601; issue-body replaces the issue text (the epic text; GitHub keeps the edit history). The token is read at run time from the copilot MCP config and handed to gh only as GH_TOKEN for that one call.
- **Auslöser und Eingaben:** n8n (about 16 distinct nodes: 'SSH: List Run Comments', 'Code: Discard Command', 'Code: Build Gate Block', 'Code: WP Table Comment', 'SSH: Read Target Comments', 'Code: Gate Context', 'Mark Issue Failed/Stopped' ...), agents inside runs, and other helpers (resume-check, triage, impl-check, epic-delta, session-watch).
- **Ergebnis und Zustand:** Comments on the issue; JSON on stdout.
- **Fehlerbehandlung:** Argument validation with usage; die() on unreadable body file or missing token; gh failure propagates (set -e).
- **Externe Systeme:** GitHub REST.
- **Abstraktion für das Produkt:** [core] Card discussion API with an explicit actor identity (agent vs owner): create and edit own comments, list the COMPLETE thread with a time filter, replace the card description with version history. 'List everything' must be the default because pagination bugs hid decisions.
- **Beleg:** /home/orologas/bin/aiforge-comment:4-86; /home/orologas/docs/opencode-run-profiles.md 'Kommentar-Pagination' (Netrats#38: 38 comments, models read page 1 only)

### STATE: Resume gate after a health pause (needs new human input)

- **Was sie tut:** aiforge-resume-check <repo> <issue> runs at the start branch of the Coding workflow (after 'DB: Expire Stale Coding Runs', before 'DB: Enqueue New Issue'). If issues.health_paused_at is empty it just lets the start proceed. If a health watchdog paused the stage, it counts comments by non-bot authors since the pause (aiforge-comment list --since). No reply: the run is NOT started; ai:ready and ai:queued are removed, human:question is added, the assignee is swapped bot -> owner and a comment <!-- aiforge:resume-blocked --> explains (answer the health question then set ai:ready, or set ai:accept); proceed=false. Reply present: health counters reset (health_reset_at=now, health_paused_at=NULL) and a 'recovery' run starts with next_action and the user's replies (newest last, max 4000 chars) injected as userReply into the prompt. Last line AIFORGE {proceed, resume, kind, prompt, replies, result}.
- **Auslöser und Eingaben:** n8n GitHub.Agentic.Coding: 'SSH: Resume Check' -> 'Code: Parse Resume' -> 'If: Resume Proceed?'; 'Code: Resolve Action' reads userReply; pause is set by Events 'DB: Save Next Action' (health_paused_at).
- **Ergebnis und Zustand:** issues.health_reset_at / health_paused_at; labels/assignee changes; comment; feeds Grafana panel 'Health-Pausen'.
- **Fehlerbehandlung:** Fail-open: bad args, list failure, DB failure -> proceed=true without resume (result codes bad-args, list-failed, db-update-failed); n8n 'Code: Parse Resume' also defaults to proceed.
- **Externe Systeme:** Postgres, GitHub REST (via aiforge-issue/aiforge-comment).
- **Abstraktion für das Produkt:** [hardening] 'Blocked on human' state with a resume guard: a card paused by a loop/health watchdog can only restart after new human input exists; the answer is injected into the next run's prompt and counters reset. Prevents re-running with no new information.
- **Beleg:** /home/orologas/bin/aiforge-resume-check:1-51; n8n nodes named above; /home/orologas/repos/telemetry/docs/ai-pipeline-control-center.md panel 63

### GATE: Result-contract enforcement at write time

- **Was sie tut:** When the launcher sets AIFORGE_ACTION (regex ^[a-z][a-z-]*$), aiforge-comment post|edit first runs aiforge-comment-contract.mjs <action> <body-file>. A violation means the comment is NOT posted, exit 1, and the reason is printed to the agent, which must correct and repost inside the same run instead of losing a whole cycle. Comments that are no result of the action (marker absent) and n8n's own calls pass unchecked; AIFORGE_COMMENT_CHECK=0 disables the check. n8n repeats the same validation server-side after the run ('Code: Check Contract') and 'Code: Discard Command' rewrites invalid candidates into a <!-- aiforge:discarded --> note (attempt n/3).
- **Auslöser und Eingaben:** Every agent comment through the aiforge-comment CLI during a pipeline run; env AIFORGE_ACTION set in n8n 'Codeman: Launch Run'.
- **Ergebnis und Zustand:** Posted or rejected comment; reason on stderr.
- **Fehlerbehandlung:** If node is missing the check is skipped; the retry budget is 3 attempts per run in n8n.
- **Externe Systeme:** node (contract script), GitHub REST.
- **Abstraktion für das Produkt:** [hardening] Typed result contracts per action validated synchronously when the agent submits its result (reject plus machine-readable reason) so the agent self-corrects in-session, with the same validator re-run server-side when the run ends. Needs ONE source of truth for contracts (today a hand-maintained copy).
- **Beleg:** /home/orologas/bin/aiforge-comment:55-63; /home/orologas/bin/aiforge-comment-contract.mjs:1-8 (says it is a COPY of n8n node 'Code: Check Contract' in GitHub.Agentic.Events); n8n 'Code: Discard Command', 'Codeman: Launch Run'

### GATE: Per-action result-contract validators and evidence check

- **Was sie tut:** Marker <!-- aiforge:<action> --> must be the FIRST line (marker elsewhere = violation 'nothing before the marker'). Per action: epic-gap-analysis needs at least one parsable json block with arrays manuell and autonom; wp-slicing needs exactly one json block with arbeitspakete/abdeckung/aenderungen, strict field sets and types, unique ids, positions exactly 1..n, dependencies only on existing ids with a smaller position, every package with epic_bezug, coverage ids existing, change types from a fixed list; wp-review (and -confirm) needs the line '**Implementation Readiness: n %**' AND summary.implementationReadinessPercent as integer 0..100 with the same value; epic-finalise needs exactly one json block {ergebnis kein-delta|delta, deltas[], hinweise[], treue_zum_auftrag} with every delta having art (offen|abweichend|seiteneffekt), gewicht (wesentlich|gering|vernachlaessigbar), bezug, beschreibung, beleg, and kein-delta only with an empty list; epic-document needs '## PR-Text' with '### Titel' and '### Beschreibung'; wp-code-review needs exactly one json block {urteil ok|befunde, befunde[] with id, schwere kritisch|hoch|mittel|niedrig, art fehler|abweichung|qualitaet, datei, zeilen, beschreibung, beleg, empfehlung}, a '### Kriterien' table with a row per AK-n/TC-n, findings for every 'nicht erfüllt' row, verdict befunde only with at least one kritisch/hoch finding and ok only without. Extra evidence check at post time: every finding names a file that exists in the worktree or appears in .aiforge/run/change.diff, and the lines lie inside that file; invented findings are rejected.
- **Auslöser und Eingaben:** Called by aiforge-comment (write time) and by n8n Events 'Code: Check Contract' (after the run); evidence check needs AIFORGE_EVIDENCE_ROOT or the git toplevel.
- **Ergebnis und Zustand:** exit 0/1 and reason text; no state.
- **Fehlerbehandlung:** Unknown actions pass; reason strings are in German and meant for the agent.
- **Externe Systeme:** none (pure validation; reads the worktree for the evidence check).
- **Abstraktion für das Produkt:** [hardening] Declarative result schemas per stage: required header/marker, JSON schema with enums, cross-field consistency (unique ids, ordering, dependency direction, verdict vs severity, percent line equals JSON) and 'cited evidence must exist in the workspace'. Output is pass/fail with a human-readable reason fed back to the agent.
- **Beleg:** /home/orologas/bin/aiforge-comment-contract.mjs:35-242 (checkEpicGap 36, checkWpSlicing 50, checkWpReview 103, checkEpicFinalise 121, checkEpicDocument 143, checkWpCodeReview 154, checkEvidence 186, checkComment 211)

### ROUTING: Next-action triage before dispatch (rules engine)

- **Was sie tut:** aiforge-triage <repo> <issue> [--queue-id] [--mode N] [--llm] [--dry-run] decides, before a MANUALLY started run is dispatched, what should really happen. It gathers: GitHub REST (labels, assignees, open/closed, issue events to detect an ai:accept/ai:slice command in the last 20 min, the epic's PRs by head branch epic/<N> or a closing keyword, with mergeable state polled up to 7x5 s), Postgres (issues.state/current_action/next_action/lane/stages_done, active sessions, other claimed/processing queue rows, work packages and which are implemented, unimplemented predecessors, allowed actions from routing_rules) and board fields via aiforge-project get. Epic rules: merged PR -> none; open PR with conflicts -> run epic-merge-resolve if the merge agent is on, else wait; open mergeable PR -> wait ('please merge'); mergeability unknown -> wait; only closed unmerged PRs -> wait; any failed package -> wait; all built but not all implemented -> wait; some unbuilt -> run unchanged; all implemented without PR -> run epic-finalise if no finalise marker, else epic-document if no document marker, else wait (finished but no PR). Work package: already implemented -> none, else unchanged. Bypasses (run unchanged): label ai:force, explicit ai:accept/ai:slice within 20 min (ai:accept = accept the stage result and move on, ai:slice = manual stage transition, ai:go = reset and start), an already running session/queue row, card that is neither epic nor work_package. Result: run (optional nextAction override), wait (comment to the owner, run ends) or none (done, run ends). Last line AIFORGE triage {decision, nextAction, stop, apply, mode, reason, comment, source, proposal, inconsistent, previousNextAction}.
- **Auslöser und Eingaben:** n8n GitHub.Agentic.Coding: 'If: Triage Applicable?' (queue kind=new AND a human sender, i.e. manual starts only) -> 'SSH: Triage' -> 'Code: Triage Decision' -> 'If: Triage Stop?'; stop -> 'DB: Triage Mark Stopped' (queue and issue done) -> 'SSH: Triage Handover' (labels back to human:review, assignee to owner, board Ready).
- **Ergebnis und Zustand:** issues.next_action (mode 2, changed run decision), comment <!-- aiforge:triage --> (wait/none/repair), row in github_automation.triage_decision.
- **Fehlerbehandlung:** Any exception or missing output -> decision run with empty nextAction and stop=false (continue as before); n8n 'Code: Triage Decision' applies the same default.
- **Externe Systeme:** GitHub REST (bot token from the vault-rendered env file), Postgres, local aiforge-project/aiforge-comment, optional LiteLLM gateway.
- **Abstraktion für das Produkt:** [core/hardening] A 'what should happen next' step before dispatch: reads the card's real state (workflow position, child cards, linked pull requests, running sessions, human commands) and returns run / wait / done with a reason and a human-readable comment, so a card is never started on stale state and the human gets an explicit 'nothing to do, please merge' instead of a pointless run.
- **Beleg:** /home/orologas/bin/aiforge-triage:2-20 (doc), 70-162 (gather), 266-334 (decide_core), 445-506 (main); n8n nodes 'If: Triage Applicable?', 'SSH: Triage', 'Code: Triage Decision', 'If: Triage Stop?', 'DB: Triage Mark Stopped', 'SSH: Triage Handover'

### ROUTING: Healer for invalid, stale or missing next_action

- **Was sie tut:** diagnose() repairs issues.next_action when it is (a) invalid (not an active routing action, e.g. an agent key such as wp-implementer instead of wp-implement, or a typo), (b) stale (belongs to a stage already in stages_done) or (c) missing although stages are done. Mapping order: unique agent-key -> action; difflib close match (cutoff 0.8, ambiguity needs a >0.1 similarity gap); otherwise the entry action of the next open stage (work-package order wp-building->wp-build, wp-refinement->wp-review, wp-implementation->wp-implement). Guards: a mapped action that belongs to a finished stage is not taken blindly; wp-implement is refused while predecessor packages are not implemented; 'all stages done but package not implemented' ends in wait with a question to the owner. Heals only when no session/queue row is active, also with ai:force and after a command, and comments '(vorher: <old>)'. For epics only invalid actions are repaired; an invalid value the rules would leave unchanged ends in wait.
- **Auslöser und Eingaben:** Inside aiforge-triage on every manual start, and in its --sweep mode.
- **Ergebnis und Zustand:** Updated issues.next_action; comment with the old value; triage_decision row (repair flag).
- **Fehlerbehandlung:** Unsafe repair -> wait with comment; nothing is guessed silently.
- **Externe Systeme:** Postgres, GitHub REST.
- **Abstraktion für das Produkt:** [hardening] Self-repair of the card's 'next step' pointer: validate against the current workflow definition, detect stale/missing/mistyped values, repair deterministically with an audit comment, escalate to a human question when repair is unsafe.
- **Beleg:** /home/orologas/bin/aiforge-triage:177-263 (map_invalid, diagnose, decide); pre-healer copy /home/orologas/pipeline-backup-20261120/aiforge-triage.vor-healer (23.6 KB) vs current 33.0 KB, healer added 2026-11-20

### ROUTING: Optional LLM arbitration of contradictory state

- **Was sie tut:** Only when triage_llm=1 (or --llm) AND the rules flag the state inconsistent AND no repair applies: a model (agent 'next-action-triage', ai-hub deepseek through the local LiteLLM gateway, temperature 0.1, max 800 tokens) gets the state JSON plus the rule proposal. Its JSON {entscheidung run|wait|none, naechste_aktion, begruendung, kommentar} is accepted only if the decision is valid, a reason exists and any named action is in the allowed-actions list; otherwise the rule result stands. System and user prompt parts come from the versioned registry table prompt_evolution.agent_configurations_md (production environment first, latest version).
- **Auslöser und Eingaben:** Inside aiforge-triage; switch triage_llm (0 = off, value 0 per the 2026-11-19 audit, not re-verified).
- **Ergebnis und Zustand:** final decision with source=llm and latency_ms in triage_decision.
- **Fehlerbehandlung:** Any failure or invalid answer -> None -> rules decision.
- **Externe Systeme:** LiteLLM gateway (local), Postgres prompt registry.
- **Abstraktion für das Produkt:** [optional] LLM tie-breaker for contradictory card state with strict output validation against the allowed-action set, the deterministic proposal as fallback, model/latency recorded, prompts in a versioned agent registry.
- **Beleg:** /home/orologas/bin/aiforge-triage:338-373, 473-477; /home/orologas/bin/aiforge-triage-switch:4-6

### ROUTING: Rollout modes and operator switch (off / observe / active)

- **Was sie tut:** scheduler_setting triage_mode: 0 off, 1 observe (judge and log into triage_decision, change and comment nothing), 2 active (sets next_action; wait/none end the run). merge_agent_mode and triage_llm are separate switches. aiforge-triage-switch [show | triage 0|1|2 | merge 0|1 | llm 0|1] reads and updates github_automation.scheduler_setting; 'merge' also activates/deactivates the routing rules epic-merge-resolve, epic-merge-gate, epic-merge-health in one transaction (the merge agent is only ever started by triage); 'show' prints the three settings, the rule states and the number of decisions (and applied ones) in the last 24 h. Per-card escape: label ai:force.
- **Auslöser und Eingaben:** Manual operator CLI; read by aiforge-triage on each start.
- **Ergebnis und Zustand:** scheduler_setting rows, routing_rules.active for the merge rules.
- **Fehlerbehandlung:** Argument validation; psql ON_ERROR_STOP; merge toggle is one transaction.
- **Externe Systeme:** Postgres.
- **Abstraktion für das Produkt:** [hardening] Gradual-rollout switch per automation (off / observe-shadow / active) with an operator command (CLI or admin UI) and a per-card override; observe mode must still write the decision log so behaviour can be reviewed before enabling it.
- **Beleg:** /home/orologas/bin/aiforge-triage-switch:2-21; /home/orologas/bin/aiforge-triage:6-19, 461-470; audit values as of 2026-11-19 (triage_mode=2, merge_agent_mode=1, triage_llm=0, session_watchdog_mode=1) in /home/orologas/docs/automation-architecture-activity-audit.md, not re-verified

### ROUTING: Decision audit log and notification de-duplication

- **Was sie tut:** Every non-off triage result is logged in github_automation.triage_decision (repository, issue, artefact type, mode, state snapshot jsonb, rule proposal, final decision, next_action, reason, comment, source rules|llm|sweep, applied flag, previous next_action, model, latency_ms). Triage comments carry the marker <!-- aiforge:triage --> and mention the owner; before posting, a hash of the text is compared with the last triage comment so an identical message is not posted twice.
- **Auslöser und Eingaben:** Inside aiforge-triage (modes 1 and 2).
- **Ergebnis und Zustand:** triage_decision rows; at most one new triage comment per distinct text.
- **Fehlerbehandlung:** Log write failure is reported on stderr and does not change the decision.
- **Externe Systeme:** Postgres, GitHub (via aiforge-comment).
- **Abstraktion für das Produkt:** [hardening] Append-only decision log (input snapshot, proposal vs final, applied?, who decided: rule or LLM, latency) and de-duplication of repeated identical bot notifications.
- **Beleg:** /home/orologas/bin/aiforge-triage:377-403 (post_comment, log_decision), 490-494

### ROUTING: Sweep of stuck cards (healer only)

- **Was sie tut:** aiforge-triage <repo> --sweep [--dry-run] scans issues in state failed/queued with empty current_action, skips those with an active session or queue row, runs only the healer and in mode 2 writes next_action and comments; every candidate is logged with source=sweep. The docstring suggests cron.
- **Auslöser und Eingaben:** Manual or cron; no scheduler or n8n caller found.
- **Ergebnis und Zustand:** issues.next_action, comments, triage_decision rows.
- **Fehlerbehandlung:** Per-issue errors are printed and the sweep continues.
- **Externe Systeme:** GitHub REST, Postgres.
- **Abstraktion für das Produkt:** [optional] Periodic self-healing sweep over stuck cards.
- **Beleg:** /home/orologas/bin/aiforge-triage:406-442; no reference in /home/orologas/.config/systemd or n8n workflow_entity

### CONTEXT: Narrow input pack for epic clarification

- **Was sie tut:** aiforge-epic-context <repo> <issue> <out.md> writes one file with (1) the current epic text (issue body), (2) the newest valid gap analysis (marker <!-- aiforge:epic-gap-analysis -->, including the user's checked options), (3) the newest gap resolution (marker <!-- aiforge:epic-gap-resolution -->, with collapsed 'previous version of the epic' blocks stripped because they are stale), (4) every comment of the user (not the bot), oldest first. Slicing results, discarded attempts, older analyses and tables are left out; each block is capped at 30,000 chars; the header tells the agent not to read the comment history again. Last line: AIFORGE epic-context ok bytes= user_comments= analysis=<id|-> resolution=<id|->.
- **Auslöser und Eingaben:** n8n 'Code: Run Files Command' for actions epic-gap-analysis and epic-gap-resolution, before the agent starts; file lands in .aiforge/run/epic-context.md.
- **Ergebnis und Zustand:** epic-context.md in the git-excluded run directory.
- **Fehlerbehandlung:** Never fails the run: on read errors it writes what it has plus a 'Hinweis' line.
- **Externe Systeme:** GitHub REST (via gh and aiforge-comment).
- **Abstraktion für das Produkt:** [hardening] Curated, size-capped context pack per stage (current spec, latest relevant machine outputs, all human comments) instead of the raw thread, so long-lived cards do not blow the agent's context window.
- **Beleg:** /home/orologas/bin/aiforge-epic-context:1-99 (reason documented: Epic #106, 2026-11-09, comment history 40k+/30k+ caused context compaction)

### CONTEXT: Review minifest with diff and machine findings

- **Was sie tut:** aiforge-review-context <repo> <issue> <worktree> [out-dir] writes review-context.md and change.diff before a wp-code-review run. Base = parent of the oldest commit 'Refs #<issue>' on origin/main..HEAD; change.diff is the whole change; review-context.md lists commits, changed files with +/- line counts, 'machine findings' (hints with file and line that the reviewer must verify) and the verbatim work-package text (acceptance criteria, test cases). Findings: pseudo-tests (reuses impl-check pseudo_tests), literal URLs/paths (href/src/data-src/poster/fetch/new URL) pointing to files that exist neither in public/ nor dist/ (with a note when only src/<path> exists, because sources are not served under their src path), Playwright/Puppeteer scripts that launch a browser but never call goto/navigate/setContent/route (they would measure an empty page), new dependencies in package.json.
- **Auslöser und Eingaben:** n8n 'Code: Run Files Command' for action wp-code-review.
- **Ergebnis und Zustand:** review-context.md and change.diff in .aiforge/run (also read later by the evidence check of the contract).
- **Fehlerbehandlung:** Everything caught -> 'AIFORGE review-context failed <reason>' and exit 0.
- **Externe Systeme:** git, gh issue view, local impl-check module.
- **Abstraktion für das Produkt:** [hardening] Deterministic reviewer pre-pass: a compact review packet (what changed, diff, requirement text, tool-detected suspicious items) so an independent reviewer model starts from facts and verifies hints instead of exploring; packet generation never blocks the run.
- **Beleg:** /home/orologas/bin/aiforge-review-context:1-138 (url_findings 38-60, browser_scripts_without_navigation 67-79, new_deps 82-86)

### CONTEXT: Finaliser inputs with discovered tool manifest

- **Was sie tut:** aiforge-epic-check context <repo> <epic> <worktree> writes .aiforge/run/epic.md (epic issue body), wps.json (work packages from github_automation.work_packages: id, position, title, issue, status, implemented_at) and manifest.json: the test/measuring tools the repository offers RIGHT NOW, discovered and never maintained by hand (package.json scripts except dev/start/preview/serve/watch, scripts/*.mjs|js|py|sh with the file head comment as description, presence of vitest/playwright configs and of a preview script). The finaliser's plan may only use tools from this manifest.
- **Auslöser und Eingaben:** n8n 'Code: Run Files Command' before action epic-finalise.
- **Ergebnis und Zustand:** epic.md, wps.json, manifest.json; last line AIFORGE epic-context ok epic_bytes= wps= tools=.
- **Fehlerbehandlung:** Errors -> 'FEHLER' line plus 'AIFORGE epic-context failed', exit 0.
- **Externe Systeme:** GitHub REST, Postgres, repository files.
- **Abstraktion für das Produkt:** [hardening] Tool discovery for acceptance verification: the runtime inspects the repository and publishes the list of runnable checks to the agent so a verification plan can only reference tools that exist.
- **Beleg:** /home/orologas/bin/aiforge-epic-check:94-135

### CONTEXT: Pull-request context pack for the documenter

- **Was sie tut:** aiforge-epic-check pr <repo> <epic> <worktree> writes .aiforge/run/pr-context.md: work packages with a '(NICHT umgesetzt)' flag, non-merge commits origin/main..HEAD, diff stat, open deltas from github_automation.epic_delta (status offen or info-epic, with the info-epic number), cleanliness findings (files that do not belong in a PR) and the newest epic-finalise result comment (max 20,000 chars). The PR text may only add what the documenter can prove from the repository.
- **Auslöser und Eingaben:** n8n 'Code: Run Files Command' for action epic-document, after aiforge-epic-delta apply.
- **Ergebnis und Zustand:** pr-context.md; last line AIFORGE epic-pr ok wps= commits= deltas= unsauber=.
- **Fehlerbehandlung:** Exceptions -> 'AIFORGE epic-pr failed' style line and exit 0.
- **Externe Systeme:** git, Postgres, GitHub REST.
- **Abstraktion für das Produkt:** [core] Pull-request context pack for the documentation stage: commits, packages (done / not done), diffstat, known deltas, hygiene findings and the finalisation verdict.
- **Beleg:** /home/orologas/bin/aiforge-epic-check:488-528

### GATE: Implementation run completeness preflight

- **Was sie tut:** aiforge-impl-check <repo> <issue> <worktree> [--post] [--skip-push] [--no-cache] [--base-branch ref] first verifies that the implementation run really finished: on a branch (no detached HEAD), at least one commit 'Refs #<issue>' between base ref and HEAD (base ref = origin/main; for branches epic/<N>-wp/<x> it is origin/epic/<N>), no uncommitted changes, branch pushed (HEAD equals origin/<branch>, skipped with --skip-push), and the agent's final report .aiforge/impl.md exists and is not empty. The worktree must be under /home/orologas/worktrees/.
- **Auslöser und Eingaben:** n8n GitHub.Agentic.Events: routing_rules.check_command of the step after wp-implement is read by 'DB: Coding Run Context' (next_check_command) and run by 'SSH: Read Gate File' as <check_command> <repo> <issue> <worktree> --post (must match /home/orologas/bin/<name>); the last line returns Base64 to 'Code: Check Contract'.
- **Ergebnis und Zustand:** AIFORGE impl-check {ok, failures[], hints[], manual_tcs[], branch, head, base, commits, url}.
- **Fehlerbehandlung:** Invalid worktree -> ok:false exit 2; any crash prints ok:false with the crash text and exits 0 so the pipeline always gets a result line.
- **Externe Systeme:** git, GitHub (gh issue body), Postgres none.
- **Abstraktion für das Produkt:** [core] 'Definition of done' preflight for an implementation run: work is committed with the card reference, the workspace is clean, the branch is published and the agent filed its final report.
- **Beleg:** /home/orologas/bin/aiforge-impl-check:2-24 (doc), 199-262; n8n Events nodes 'DB: Coding Run Context', 'SSH: Read Gate File', 'Code: Check Contract', 'Code: Decide Next'

### GATE: Regression check against a cached baseline (type check, tests, build)

- **Was sie tut:** Everything is compared with the state BEFORE the package (base = parent of the oldest 'Refs #n' commit), because main may already have type errors and red tests. The baseline is computed once per base commit in a temporary detached git worktree (node_modules symlinked): astro check (TS error signature file|code|message) and vitest json results, cached in ~/.cache/aiforge-impl-check/<sha>.json. At HEAD: new type errors fail; a test that passed at base and now fails fails; new red tests fail; a test file that loaded at base and no longer loads fails; vitest producing no result fails; npm run build must succeed. Hint only: formerly green tests that no longer exist. The environment is scrubbed of *_API_KEY / *_API_SECRET variables (agent provider keys otherwise flip env-dependent tests), NO_COLOR and CI are set, PATH gets ~/.local/bin (n8n's SSH shell lacks it); each tool has a 1200 s timeout.
- **Auslöser und Eingaben:** Same call as the completeness preflight.
- **Ergebnis und Zustand:** failures[] / hints[] in the result JSON; baseline cache files.
- **Fehlerbehandlung:** Baseline worktree creation failure -> failure entry and finish; timeouts return exit 124 text.
- **Externe Systeme:** git worktrees, npx astro/vitest, npm.
- **Abstraktion für das Produkt:** [core] Verification suite with baseline-diff semantics: run type check, tests and build on the parent state once (cached per commit), run again on the result and fail only on regressions the change introduced; hermetic environment (no provider keys, CI mode); pluggable per repository (here Astro, vitest and npm are hard-wired).
- **Beleg:** /home/orologas/bin/aiforge-impl-check:34-123, 264-297

### GATE: Test-case traceability (TC-n to named tests, manual declaration)

- **Was sie tut:** Test cases of the work package (a line that STARTS with TC-<n> or TC-<n>.<m> as heading, bold, list item or plain line, searched in the section 'Testfälle' or else the whole issue text) must each be covered: at least one vitest test whose full name contains the id (TC-3 matches TC-3/TC-03/TC 3 but not TC-30 or TC-3.1) and ALL such tests pass, or .aiforge/impl.md names the id on a line containing 'manuell' with a reason (listed as manual_tcs and judged by the goal gate). Missing or red -> failure 'TC-n ohne Test' / 'TC-n rot'. No test cases found -> hint only.
- **Auslöser und Eingaben:** Part of aiforge-impl-check.
- **Ergebnis und Zustand:** tc_rows in the posted report, manual_tcs in the result JSON.
- **Fehlerbehandlung:** Failures are listed verbatim and fed into the correction run.
- **Externe Systeme:** GitHub issue body, vitest results.
- **Abstraktion für das Produkt:** [core/hardening] Requirement-to-test traceability: acceptance and test-case IDs in the card text must map to named automated tests that pass, or be declared manual with a reason that a later reviewer judges.
- **Beleg:** /home/orologas/bin/aiforge-impl-check:131-147, 298-317

### GATE: Pseudo-test and fake-coverage detection

- **Was sie tut:** For test files changed by the package: failure when a file imports no production code (relative, @/, ~/, src/ imports excluding other tests, mocks, fixtures) and reads no repository files (readFileSync, ?raw, glob, page.goto ...), because it can only test a copy of its own logic; failure for literal assertions that can never fail (expect(true).toBe(true) with equal literals), at most 6 reported plus a count; hint (not failure) for test blocks without any assertion (helpers named assert*/verify*/check* count). A manual test case belongs in .aiforge/impl.md with a reason, not as a placeholder test. The same function feeds the reviewer packet.
- **Auslöser und Eingaben:** aiforge-impl-check; reused by aiforge-review-context via module import.
- **Ergebnis und Zustand:** failures[] and hints[].
- **Fehlerbehandlung:** Unreadable files are skipped.
- **Externe Systeme:** repository files only.
- **Abstraktion für das Produkt:** [hardening] Static detection of fake coverage (tests that do not touch real code, tautological assertions, assertion-free tests) as a gate failure plus reviewer hints.
- **Beleg:** /home/orologas/bin/aiforge-impl-check:149-196, 326-330; /home/orologas/bin/aiforge-review-context:112-115

### GATE: Pipeline-artifact leak and PR hygiene checks

- **Was sie tut:** impl-check fails when files under .aiforge/ or .tmp/ were committed ('git rm --cached', commit, push; files stay local). epic-check clean <worktree> lists suspicious files in origin/main...HEAD with 'SAUBERKEIT <path>: <reason>' and 'AIFORGE epic-clean <n>': .aiforge/, .opencode/, .tmp/, test-results/playwright-report/coverage, node_modules, *.log/.bak/.orig/.rej/.bak-*, names like manifest|plan|results|delta|health|gate|impl .json/.md, and tracked files that .gitignore excludes (only files this branch added or changed). The runtime also adds .aiforge/ to the repo's .git/info/exclude.
- **Auslöser und Eingaben:** impl-check (per package); epic-check clean/pr (per epic, before PR text).
- **Ergebnis und Zustand:** failure entries / SAUBERKEIT lines; cleanliness section of pr-context.md.
- **Fehlerbehandlung:** Report only; the documenter and gate decide.
- **Externe Systeme:** git.
- **Abstraktion für das Produkt:** [hardening] Hygiene gate: platform hand-over files, tool caches, logs and ignored files must never enter a pull request; the platform keeps its own working files out of version control by construction.
- **Beleg:** /home/orologas/bin/aiforge-impl-check:321-325; /home/orologas/bin/aiforge-epic-check:450-485; n8n 'Code: Run Files Command' (info/exclude)

### GATE: Red/green verification report as the judged result

- **Was sie tut:** With --post and everything green, aiforge-impl-check posts a report comment with marker <!-- aiforge:wp-implement --> (check table, TC mapping with green/manual/red, commits, hints, collapsible agent report up to 20,000 chars) which is the result the goal gate judges. With any failure it posts a short red report with a different marker <!-- aiforge:impl-check --> (failures, TC table, hints) that the goal gate never judges but the user and the health gate can see; the failure list goes verbatim into the correction run. In n8n a check that RAN is a valid run result either way (ok -> gate; not ok -> correction run); only a missing or unreadable check result counts as contract violation and retry.
- **Auslöser und Eingaben:** aiforge-impl-check --post via 'SSH: Read Gate File'.
- **Ergebnis und Zustand:** Issue comment with marker; result JSON incl. url.
- **Fehlerbehandlung:** Post failure appends 'Prüfbericht konnte nicht gepostet werden' to failures.
- **Externe Systeme:** GitHub (aiforge-comment post).
- **Abstraktion für das Produkt:** [core] Deterministic verification stage between agent run and judge: green produces the artifact the LLM judge evaluates, red produces a visible progress report and a precise correction brief for the next attempt; the two states must not be confusable.
- **Beleg:** /home/orologas/bin/aiforge-impl-check:336-381; n8n Events 'Code: Check Contract' (wp-implement branch, lines about impl), 'Code: Decide Next' comments

### GATE: Epic acceptance-plan validation (grounded in the spec text)

- **Was sie tut:** The epic finaliser agent writes .aiforge/plan.json; aiforge-epic-check run validates it before anything executes. Each criterion needs a unique id that literally occurs in the epic text, class messbar|funktional|nicht_pruefbar, a reason (begruendung) and optional fundstellen that must exist in the worktree. messbar: tool must be an entry of manifest.json, metric snake_case, operator one of < <= > >= =, numeric threshold, a 'zitat' that occurs verbatim (whitespace-normalised) in the epic text AND contains the threshold number (no invented limits), result extraction via json_pfad or regex with a capture group (optional file), optional preparation 'preview' only if the repo has a preview script. funktional: named tests (file > name) or fundstellen as evidence. Errors print as 'FEHLER ...' lines plus 'AIFORGE epic-check invalid' so the agent fixes the plan.
- **Auslöser und Eingaben:** INFERRED: run by the epic-finalise agent itself in its session (no n8n node calls 'epic-check run'; n8n only calls 'context' and 'pr').
- **Ergebnis und Zustand:** FEHLER lines, AIFORGE epic-check invalid | ok {json}.
- **Fehlerbehandlung:** Plan errors are reported not raised; exit 0.
- **Externe Systeme:** repository, epic issue text.
- **Abstraktion für das Produkt:** [hardening] Acceptance-criteria plan validation: criteria must be traceable to the spec (ID plus verbatim quote of the threshold), classified (measurable, functional, not checkable), bound to tools that exist, with machine-readable extraction rules; the model proposes, the validator rejects anything not grounded in the spec.
- **Beleg:** /home/orologas/bin/aiforge-epic-check:2-24 (doc), 199-266 (validate), 372-387; absence of callers in n8n workflow_entity

### GATE: Whole-epic side-effect scan against the default branch

- **Was sie tut:** Level A of epic-check run compares merge-base(origin/main, HEAD) with HEAD using astro check, vitest and npm run build; the base snapshot is cached per commit in ~/.cache/aiforge-epic-check/<sha>.json. Reported side effects: test-entfernt (green on main, gone on the branch), test-uebersprungen (now skipped/pending/todo), test-rot, testdatei-laedt-nicht, typfehler-neu, build-kaputt. Written to .aiforge/results.json (level_a base/head counts and seiteneffekte) and printed as 'SEITENEFFEKT <art>: ...'; the finaliser reports them as 'seiteneffekt' deltas.
- **Auslöser und Eingaben:** aiforge-epic-check run (see plan validation).
- **Ergebnis und Zustand:** .aiforge/results.json; baseline cache.
- **Fehlerbehandlung:** merge-base failure -> 'FEHLER' + invalid; cached baseline reused.
- **Externe Systeme:** git worktrees, npx astro/vitest, npm.
- **Abstraktion für das Produkt:** [hardening] Regression/side-effect scan of the whole epic branch against the default branch (removed or skipped or red tests, new type errors, broken build), independent of the criteria plan.
- **Beleg:** /home/orologas/bin/aiforge-epic-check:140-194, 388-436

### GATE: Measured acceptance criteria and metric history

- **Was sie tut:** Level B: for every 'messbar' criterion the script itself runs the named tool (timeout 900 s; optionally after npm run build and a preview server on a free port, default 4321, started in its own process group and killed afterwards), extracts the number (json_pfad on JSON output or a result file, or a regex group), compares it with the threshold using the declared operator and records value, unit, threshold, operator, criterion id and tool per commit in github_automation.metric_history. The verdict comes from the script, never from the model; an unmeasurable criterion stays 'offen' with the reason (port busy, build failed, no JSON, regex miss, not a number).
- **Auslöser und Eingaben:** aiforge-epic-check run.
- **Ergebnis und Zustand:** metric_history rows, results.json kriterien/metriken.
- **Fehlerbehandlung:** Metric write failure only prints a hint; the measurement stays valid.
- **Externe Systeme:** local tools, preview server, Postgres.
- **Abstraktion für das Produkt:** [hardening] Measured acceptance: automatic execution of declared measuring tools (optionally against a started preview), threshold comparison with the spec's own numbers, a metrics time series per commit, verdict computed by code, unmeasurable criteria flagged open instead of guessed. Little production evidence: metric_history had 0 rows in the 2026-11-19 audit.
- **Beleg:** /home/orologas/bin/aiforge-epic-check:295-369, 403-417; /home/orologas/docs/automation-architecture-activity-audit.md (metric_history 0 rows, not re-verified)

### GATE: Functional criteria bound to named tests

- **Was sie tut:** For 'funktional' criteria with tests: every named test must exist at HEAD and be green; missing or red -> not fulfilled with detail ('Test fehlt', 'Test nicht grün'); criteria with only fundstellen stay open ('Urteil durch den Finaliser'); nicht_pruefbar stays open. Summary line AIFORGE epic-check ok {kriterien, erfuellt, nicht_erfuellt, offen, seiteneffekte, build_ok}.
- **Auslöser und Eingaben:** aiforge-epic-check run.
- **Ergebnis und Zustand:** results.json kriterien[].
- **Fehlerbehandlung:** n/a
- **Externe Systeme:** vitest results.
- **Abstraktion für das Produkt:** [hardening] Criterion-to-test binding: functional acceptance criteria are satisfied only by named automated tests that exist and pass; evidence-only criteria are explicitly marked as judged by a reviewer.
- **Beleg:** /home/orologas/bin/aiforge-epic-check:418-445

### GATE: Spec-to-delta persistence and informational follow-up card

- **Was sie tut:** aiforge-epic-delta apply <repo> <epic> [--dry-run] takes the newest bot comment with marker <!-- aiforge:epic-finalise --> (the result the goal gate passed), reads its json {ergebnis, deltas[], hinweise[], treue_zum_auftrag}, replaces the 'offen' rows of github_automation.epic_delta (kind, weight, reference, description, evidence, comment_id; idempotent per comment id; rows a user set to akzeptiert/erledigt are never touched). If at least one delta is 'wesentlich' and the epic has no info epic yet, it creates an issue 'Delta aus #N: <title>' as the bot with label epic ONLY (no ai:ready, no assignee, so the pipeline does NOT start it): origin, delta table, evidence, wording of the epic ids and an explicit 'information, not an order' banner; wesentlich/gering rows become status info-epic with the new number; vernachlässigbar deltas are excluded.
- **Auslöser und Eingaben:** n8n 'Code: Run Files Command' for epic-document, before aiforge-epic-check pr.
- **Ergebnis und Zustand:** epic_delta rows; new info-epic issue.
- **Fehlerbehandlung:** Never stops the run: skipped / failed lines (AIFORGE epic-delta skipped|failed|ok), exit 0.
- **Externe Systeme:** GitHub REST (bot token), Postgres.
- **Abstraktion für das Produkt:** [core/hardening] Spec-vs-actual delta register per epic and an auto-drafted but NOT auto-started follow-up card describing the gap; human decides whether to start it.
- **Beleg:** /home/orologas/bin/aiforge-epic-delta:2-15, 54-170; n8n 'Code: Run Files Command'

### STATE: Deterministic pull-request opening from the documenter's text

- **Was sie tut:** aiforge-epic-pr <repo> <epic> [--dry-run] opens the epic's pull request (head epic/<N> -> default branch) without an agent: takes the newest bot comment with marker <!-- aiforge:epic-document --> (the result the goal gate passed), extracts '## PR-Text' with '### Titel' and '### Beschreibung' (code fences tolerated), appends 'Closes #<N>' when no closing keyword is on a plain line plus an origin footer ('merge by the user'), creates the PR as the bot via REST, assigns the owner and requests the owner as reviewer, and comments <!-- aiforge:epic-pr --> on the epic with the PR link or the reason none was opened. An already open PR for the head branch is never overwritten (the user may have edited it) and is just reported. The branch must exist and be ahead of base. It never merges.
- **Auslöser und Eingaben:** routing_rules.handover_command of the epic-document rule, run first at hand-over after the passed epic-document gate ('Code: Handover Commands (Valid)': <handover_command> <repo> <issue>; path must match /home/orologas/bin/<name>).
- **Ergebnis und Zustand:** PR, assignee/reviewer, comment on the epic.
- **Fehlerbehandlung:** All errors caught -> failure comment on the epic and 'AIFORGE epic-pr failed <reason>', exit 0 so the hand-over is never blocked.
- **Externe Systeme:** GitHub REST (bot token).
- **Abstraktion für das Produkt:** [core] 'Open PR' action: generates the PR from the documenter's validated text, idempotent, links/closes the card, assigns the owner as reviewer, never merges automatically, reports success or the failure reason on the card.
- **Beleg:** /home/orologas/bin/aiforge-epic-pr:2-15, 118-179; n8n Events 'Code: Handover Commands (Valid)'

### GATE: Decision-traceability helper (user decisions must reach the spec)

- **Was sie tut:** aiforge_decisions.py (imported by aiforge-wp-manifest and aiforge-wp-lint, outside this slice) parses the section '### Entscheidungen' of a work-package text (list items = decisions made by the user), extracts code-like expressions from backtick spans (brackets, ===, =>, .x( ... excluding file references) and unimplemented() returns every decision expression that does NOT occur elsewhere in the text (whitespace and quote normalised), i.e. a user decision that never reached the specification.
- **Auslöser und Eingaben:** Library functions decisions(text) and unimplemented(text).
- **Ergebnis und Zustand:** list of (entry line, expression).
- **Fehlerbehandlung:** Missing section -> empty result.
- **Externe Systeme:** none.
- **Abstraktion für das Produkt:** [hardening] Decision traceability: explicit human decisions recorded on a card must appear concretely in the derived task/spec text; unmatched decisions are surfaced as findings.
- **Beleg:** /home/orologas/bin/aiforge_decisions.py:1-30

### GATE: Model admission probe (three-task eligibility test)

- **Was sie tut:** aiforge-model-probe <provider/model> tests whether a model may join a routing cluster. In a throwaway directory with the pipeline's isolated OpenCode config it runs three tasks (opencode run --pure, timeout PROBE_TIMEOUT default 180 s each): (1) text: answers exactly 'OK'; (2) read: reads a file with a tool and returns its content; (3) scope: changes ONLY a.txt, leaves b.txt untouched and honestly reports what it changed. Last line PROBE {model, text, read, scope, score, seconds}. Documented rule: add a model only when it scores 3/3; the probe uses the same free daily quota as real runs.
- **Auslöser und Eingaben:** Manual by the owner when adding a model (no scheduler/caller).
- **Ergebnis und Zustand:** PROBE json line; temp dir removed.
- **Fehlerbehandlung:** timeout per task; failures simply score 0 for that task.
- **Externe Systeme:** OpenCode CLI, model providers via gateway/OpenRouter (keys loaded from the vault-rendered file).
- **Abstraktion für das Produkt:** [optional] Model admission test (instruction following, tool use, scope discipline) before a model is enabled in a routing cluster.
- **Beleg:** /home/orologas/bin/aiforge-model-probe:1-30; /home/orologas/repos/Netrats/.aiforge/run-profiles.md 'Ein Modell ändern oder hinzufügen'

### SUPERVISION: Live run digest (loop, error, context and progress facts)

- **Was sie tut:** aiforge-session-digest <session_id> prints a read-only JSON digest of a RUNNING run from Postgres (sessions, issues, previous session_watch snapshot), the OpenCode SQLite database opened read-only (tool calls, compactions, per-message tokens; context size = input + cache read/write of the latest assistant message; output tokens), git in the worktree (commits since start, uncommitted files excluding .aiforge/.tmp) and bot comments since start (excluding the watchdog's own). Derived: idle minutes, top repeated (tool, input-hash) pairs in the last 40 calls (>=3), repeated errors, last 8 tool calls, context_pct of a 140k window, deltas since the previous look, plus a proposed verdict from a matrix: neustart if context >= 85 % or >= 3 compactions or a nudge was already sent and it still repeats; anstupsen if the same tool call with the same input >= 4 times in the last 40 calls or the same error >= 3 times; otherwise weiterlaufen with progress evidence as reason; no OpenCode data -> no judgement (keep running).
- **Auslöser und Eingaben:** Imported by aiforge-session-watch; also runnable by hand with a session id.
- **Ergebnis und Zustand:** JSON on stdout; nothing is changed.
- **Fehlerbehandlung:** Unreadable OpenCode data is added as hint; digest still returned.
- **Externe Systeme:** Postgres, OpenCode sqlite (read-only), git, GitHub comments.
- **Abstraktion für das Produkt:** [hardening] Live run telemetry digest (tool-call loops, repeated errors, context saturation, compaction count, progress evidence such as commits/changes/comments) used by a supervisor to decide continue / nudge / restart.
- **Beleg:** /home/orologas/bin/aiforge-session-digest:1-173 (thresholds 19-23, matrix 137-165)

### SUPERVISION: Session watchdog judge with matrix guard (off / observe / act)

- **Was sie tut:** aiforge-session-watch [--run <run id> | --session <id>] [--dry-run] takes one look at a running session. Mode from scheduler_setting session_watchdog_mode (0 off, 1 observe: judge, record and comment but do nothing, 2 act) plus session_watchdog_restart; due sessions: status active, the routing rule has watch_after_minutes (then every watch_every_minutes), gate and health runs are not watched; max 4 sessions per tick, flock lock, 60 s de-dupe per run. The digest and its matrix proposal go to a model (agent 'session-watchdog' prompt from the registry, ai-hub deepseek via the local LiteLLM gateway, temperature 0.2) which confirms or overrides with JSON {urteil weiterlaufen|anstupsen|neustart, begruendung, nachricht, zusammenfassung}. Guard against a lenient model: a non-continue matrix verdict may only be overridden to weiterlaufen when the digest shows progress (commits, changed files, result comments or something new since the last look); any model failure -> the matrix verdict counts.
- **Auslöser und Eingaben:** Per-run detached watcher started by opencode-aiforge when AIFORGE_WATCH_AFTER_MIN is set by 'Codeman: Launch Run' from routing_rules.watch_after_minutes / watch_every_minutes (default every 8 min); aiforge-session-watch.timer (every 2 min) exists but is DISABLED (fallback); manual --session.
- **Ergebnis und Zustand:** See next entry (record, comment, actions).
- **Fehlerbehandlung:** Never raises; one failing session does not stop the others; false-positive risk for repeated identical tool calls is INFERRED (the owner's ToolGuard needed a reset on file edits, Netrats#38).
- **Externe Systeme:** LiteLLM gateway, Postgres, Codeman REST, GitHub.
- **Abstraktion für das Produkt:** [hardening] Run supervisor combining a deterministic rules matrix with an LLM judge; the rules act as guard against over-lenient judgement and as fallback when the model is down; staged rollout off / observe / act.
- **Beleg:** /home/orologas/bin/aiforge-session-watch:2-24, 80-98, 143-163, 253-293; /home/orologas/.config/systemd/user/aiforge-session-watch.timer (not enabled); n8n 'Codeman: Launch Run'

### SUPERVISION: Watchdog actions (nudge, in-place restart), record and notification policy

- **Was sie tut:** In mode 2: anstupsen types 'Hinweis des Session-Wächters: ...' into the same Codeman/tmux session through its REST input endpoint; neustart (needs session_watchdog_restart=1) finds the launcher process via /proc (environment AIFORGE_SESSION_ID), writes a note with the judge's summary to /tmp/aiforge-restart/<run>.md and SIGTERMs the OpenCode child (SIGKILL after 20 s); the launcher loop (which stays alive) restarts OpenCode in the SAME worktree with a fresh conversation = original prompt + note (no new queue row, no new worktree, committed and uncommitted work kept, AIFORGE_RESTARTS counter). Every look is recorded in github_automation.session_watch (checks, last verdict, snapshot facts, history jsonb, comment id) and as copilot_events 'sessionWatch'. Issue comment <!-- aiforge:session-watch --> mentions the owner and tables all looks (matrix vs final verdict): the first look creates it, further 'weiterlaufen' looks EDIT it (no new notification), any other verdict posts a new comment.
- **Auslöser und Eingaben:** Inside aiforge-session-watch (mode 2); launcher restart loop reads the marker file.
- **Ergebnis und Zustand:** session_watch row, copilot_events row, comment, SIGTERM to the agent process.
- **Fehlerbehandlung:** Restart reports 'kein Launcher/kein OpenCode-Prozess' and does nothing; nudge errors are recorded in the entry.
- **Externe Systeme:** Codeman REST (127.0.0.1:3001), /proc, GitHub.
- **Abstraktion für das Produkt:** [hardening] Supervisor actions: inject a hint into a live terminal session, or restart the agent in the same workspace with a summary of the previous attempt; every decision is recorded and surfaced on the card with notification only when something happens.
- **Beleg:** /home/orologas/bin/aiforge-session-watch:101-140, 172-198, 201-250; /home/orologas/bin/opencode-aiforge:198-237

### RUNTIME: Agent run launcher with isolation and split identity

- **Was sie tut:** opencode-aiforge --nemotron|--deepseek|--qwen|--model <provider/model> [opencode args] is the single launcher n8n types into a Codeman shell session (with --prompt from .aiforge/run/user.md). It picks the model, loads the model provider keys and the bot GitHub token ONLY from the vault-rendered env file (no fallback to the caller's environment; aborts when a mandatory one is missing), points XDG_CONFIG_HOME at the isolated pipeline config (or an OAC config when AIFORGE_XDG_CONFIG_HOME is a path below ~/.config/aiforge-opencode/) so the owner's interactive config and plugins are neither read nor changed, and splits identities: GitHub actions (gh, MCP, comments, PRs, pushes) run as the bot via GH_TOKEN; commits carry the owner's author identity because Vercel Hobby only deploys commits whose author is a team member; pushes are rewritten from SSH to HTTPS (pushInsteadOf) so git asks the gh credential helper (bot token) while fetches stay on SSH. Environment contract set by n8n: AIFORGE_SESSION_ID, AIFORGE_ACTION, AIFORGE_EXPECT_FILES, AIFORGE_STALL_MS, AIFORGE_MAX_RUNTIME_MS, AIFORGE_WATCH_AFTER_MIN/EVERY_MIN, AIFORGE_XDG_CONFIG_HOME, OPENCODE_CONFIG_CONTENT (system.md as instructions); AIFORGE_MODEL makes the plugin pin the model on every user message.
- **Auslöser und Eingaben:** n8n GitHub.Agentic.Coding 'Codeman: Launch Run' (types the command into the Codeman session; Codeman API start shell, wait-output, input); older Writing workflow 'Codeman: Launch Copilot Session'.
- **Ergebnis und Zustand:** A running OpenCode process in the run worktree; events reach n8n through the aiforge-hooks plugin (sessionStart, userPromptSubmitted, agentStop, errorOccurred, preCompact, heartbeat, tool guard).
- **Fehlerbehandlung:** Usage error exit 2; missing secret exit 1; see following runtime entries.
- **Externe Systeme:** OpenCode CLI, Codeman (tmux), LiteLLM/OpenRouter/AI Hub providers, GitHub.
- **Abstraktion für das Produkt:** [core] Agent run launcher: per-run model/profile selection, isolated agent configuration, credentials injected only into the run process, a separate service identity for platform actions versus commit authorship, and a documented environment contract for limits (stall, max runtime, expected output files, watch schedule).
- **Beleg:** /home/orologas/bin/opencode-aiforge:4-84, 112-120; n8n 'Codeman: Launch Run'; /home/orologas/docs/opencode-run-profiles.md 'Events an n8n', 'Identität'

### RUNTIME: Per-workspace session resume and per-message model pin

- **Was sie tut:** --continue/-c is replaced by --session <id> of the newest non-archived ROOT session whose directory equals THIS worktree (read-only lookup in the OpenCode SQLite db; none yet -> new session), because OpenCode's --continue picks the globally latest session: with parallel runs a resumed run attached itself to another issue's session and received its prompts (2026-11-02). The launcher also exports AIFORGE_MODEL so the plugin pins the chosen model on every user message, because the TUI keeps the model of the resumed session and ignores --model.
- **Auslöser und Eingaben:** Every launcher start with --continue; AIFORGE_RESUME=1 set by n8n for resumes.
- **Ergebnis und Zustand:** --session <id> argument.
- **Fehlerbehandlung:** Lookup failure -> empty id -> new session.
- **Externe Systeme:** OpenCode sqlite (read-only).
- **Abstraktion für das Produkt:** [hardening] Deterministic session identity per card/workspace (resume the session bound to this workspace, never 'the latest') and per-message model pinning so a changed run profile really takes effect on resume.
- **Beleg:** /home/orologas/bin/opencode-aiforge:62-64, 122-147; /home/orologas/docs/opencode-run-profiles.md 'Fortsetzung', 'Modellwahl bei Fortsetzung' (Netrats#39/#50 into #40; Netrats#38 runs 210/211)

### RUNTIME: Continue the same conversation after a provider abort

- **Was sie tut:** For pipeline runs (AIFORGE_SESSION_ID set, a --prompt present, no session named, AIFORGE_CONTINUE_ON_ABORT not 0): if the previous root session of THIS worktree (updated < 3 h ago) ended with an APIError/UnknownError that looks like a provider/stream problem (payload not completed, TransferEncoding, terminated, timed out, ECONNRESET, socket, bad gateway, upstream, unavailable, overloaded, rate limit, 502/503/504, fetch failed, connection), the retry continues that session with a short continuation note instead of the full prompt and sets AIFORGE_RESUME=1. Never for user aborts, stall/runtime guards, context overflows or other errors (they start fresh).
- **Auslöser und Eingaben:** Every launcher start of a pipeline run.
- **Ergebnis und Zustand:** --session <id> plus replaced --prompt text.
- **Fehlerbehandlung:** Any error -> start as before.
- **Externe Systeme:** OpenCode sqlite (read-only).
- **Abstraktion für das Produkt:** [hardening] Smart retry: classify why the previous attempt ended; continue the same conversation after transient provider failures, restart fresh after logic or limit failures.
- **Beleg:** /home/orologas/bin/opencode-aiforge:149-196

### RUNTIME: Exactly-once, kill-proof end-of-run signal

- **Was sie tut:** aiforge-session-end <marker> <reason> <cwd> posts sessionEnd to the n8n webhook copilotEvents exactly once (headers X-Copilot-Hook: sessionEnd, X-Codeman-Session; JSON {sessionId, reason, cwd}; 4 s timeout; errors ignored). The marker file is the claim: whoever renames it first sends. The launcher does not exec OpenCode; it keeps running, sets traps (HUP, TERM, EXIT) and starts a detached watcher (setsid in a subshell, re-parented to init) that polls the launcher pid and reports plus removes the run temp dir even after a SIGKILL of the whole process group (Codeman stops sessions with SIGTERM to the process group, possibly SIGKILL). n8n GitHub.Agentic.Events closes the session on it and, if the agent was mid-turn, hands the issue back as failed ('session lost': comment, ai:failed, queue and issue failed, assignee to owner). The plugin delays agentStop by AIFORGE_STOP_GRACE_MS because a SIGTERM made OpenCode emit session.idle, which n8n had treated as completion.
- **Auslöser und Eingaben:** Launcher traps and detached watcher; needs AIFORGE_SESSION_ID and CODEMAN_SESSION_ID; AIFORGE_WEBHOOK_BASE overrides the base for tests.
- **Ergebnis und Zustand:** Webhook event in n8n; marker file consumed.
- **Fehlerbehandlung:** Silent best effort by design (curl -m 4, || true).
- **Externe Systeme:** n8n webhook, curl, jq.
- **Abstraktion für das Produkt:** [core] Reliable end-of-run signal from the runtime: exactly-once, survives hard kills, carries a reason; the platform closes the run and treats a mid-turn end as a lost session (comment, failed flag, queue slot released, card back to the owner); 'agent finished' must be distinguishable from 'process ended'.
- **Beleg:** /home/orologas/bin/aiforge-session-end:1-13; /home/orologas/bin/opencode-aiforge:86-110; /home/orologas/docs/opencode-run-profiles.md 'Abbruch von außen (SIGTERM) meldet kein agentStop' (Netrats#38/#39, 2026-11-02)

### RUNTIME: Per-run temp directory with guaranteed cleanup

- **Was sie tut:** Each pipeline run gets its own TMPDIR (mktemp -d /tmp/aiforge-run.XXXXXX) passed only to OpenCode and removed when the run ends (after OpenCode exits, or by the detached watcher after a SIGKILL). Reason (2026-11-09): OpenCode, a Bun single binary, unpacks embedded native libraries (~14 MB .so each) into TMPDIR on every start and never removes them: 490 files / 3.7 GB had accumulated in /tmp.
- **Auslöser und Eingaben:** Every launcher start with AIFORGE_SESSION_ID.
- **Ergebnis und Zustand:** temporary directory lifecycle.
- **Fehlerbehandlung:** Watcher cleans even after SIGKILL; path pattern guard before rm -rf.
- **Externe Systeme:** filesystem.
- **Abstraktion für das Produkt:** [hardening] Per-run scratch/tmp isolation with guaranteed cleanup (also after kill) to stop resource leaks from agent runtimes.
- **Beleg:** /home/orologas/bin/opencode-aiforge:93-110, 211-237

### RUNTIME: Idle-aware recycle of a leaking shared agent server with drain

- **Was sie tut:** aiforge-opencode-recycle [--dry-run] restarts opencode.service when the pipeline is idle and the service's anonymous memory (cgroup memory.stat anon, no file cache) is >= scheduler_setting opencode_recycle_mb (default 2048). Reason: the shared opencode serve kept ~250 MB per finished session and burned more CPU (08.11.: 309 MB -> 3.3 GB after ~10 sessions, 136 % CPU). Idle = no session with status active and no queue row claimed/processing with a launcher. Check and restart run in ONE psql session holding the advisory lock hashtext('aiforge-launcher-slot') (the same lock as acquire_server_slot) so no run can take a slot in between; before restarting it stamps all ended sessions with instance_disposed_at so the orphan finder does not dispose them again; restart via sudo -n systemctl, waits up to 60 s for HTTP 200/401 on port 4096, then writes a fresh host sample which lifts the drain (while the newest host_sample shows opencode_mem_mb >= threshold, acquire_server_slot hands out no new slot). Last line AIFORGE {ok, result, anon_mb, threshold_mb} (below-threshold, busy, restarted, dry-run-would-restart, restart-not-ready, no-cgroup, no-threshold, error).
- **Auslöser und Eingaben:** n8n node 'SSH: Recycle OpenCode' in GitHub.Agentic.Coding (documented as FIRST branch of 'Trigger: Coding Wake') but the node is DISABLED and has no connections in the stored workflow; INFERRED: superseded by per-run OpenCode processes under Codeman (host-sample says instances run in tmux-spawn scopes, not in a service).
- **Ergebnis und Zustand:** Service restart, instance_disposed_at, host_sample row.
- **Fehlerbehandlung:** restart-not-ready -> ok:false; any psql error text returned (cut to 160 chars).
- **Externe Systeme:** systemd (sudo), Postgres advisory lock, cgroup filesystem, OpenCode HTTP port.
- **Abstraktion für das Produkt:** [ops/optional] Idle-aware maintenance window for long-lived shared agent servers: restart only when no run holds a slot, lock against new dispatches, back-pressure (drain) while memory is high. Irrelevant if every run gets its own short-lived process.
- **Beleg:** /home/orologas/bin/aiforge-opencode-recycle:2-56; n8n GitHub.Agentic.Coding node 'SSH: Recycle OpenCode' (disabled, no edges); /etc/systemd/system/opencode.service

### OPS: Host sampler and back-pressure signal

- **Was sie tut:** aiforge-host-sample (systemd user timer every minute, ENABLED) inserts one row into telemetry.host_sample: load1/5, PSI avg60 for cpu/io/memory, MemAvailable MB, swap used MB, number of opencode processes (comm == opencode, found via /proc because instances run in tmux-spawn scopes) and claude processes (pgrep), opencode anonymous memory MB (sum of RssAnon), opencode CPU % (tick deltas over processes present in the previous sample; 100 % = one core), whole-host CPU busy % (from /proc/stat deltas, counters kept in ~/.local/state/aiforge/host-sample.json) and active_runs via github_automation.active_runs for the main repo; deletes rows older than 30 days. The newest row also drives back-pressure: acquire_server_slot withholds new slots while opencode_mem_mb is above the recycle threshold.
- **Auslöser und Eingaben:** /home/orologas/.config/systemd/user/aiforge-host-sample.timer (OnBootSec 1 min, OnUnitActiveSec 1 min).
- **Ergebnis und Zustand:** telemetry.host_sample rows (30 days).
- **Fehlerbehandlung:** psql failure raises (check=True); CPU values are NULL on the first sample or without a state file.
- **Externe Systeme:** /proc, Postgres, Grafana dashboard 'Server: Last und Läufe (Pipeline)' (uid aiforge-server-load).
- **Abstraktion für das Produkt:** [ops] Host/runtime telemetry sampler (load, pressure, memory, agent process count, concurrent runs) stored as a time series and used by dashboards and by the scheduler for concurrency and back-pressure (server has 4 cores; max_active_runs=2 per the run-profiles doc).
- **Beleg:** /home/orologas/bin/aiforge-host-sample:1-125; /home/orologas/repos/Netrats/.aiforge/db/schema-telemetry-host-sample.sql; /home/orologas/repos/telemetry/grafana/dashboards/server-load.json

### RUNTIME: Unattended-agent profile derived from an interactive agent (OAC)

- **Was sie tut:** aiforge-oac-config [--check] builds ~/.config/aiforge-opencode/oac-xdg/opencode from the pipeline config and the interactive 'OAC' agents: opencode.jsonc (pipeline config plus read access to the OAC context/skills), symlinks to the pipeline plugin and node_modules, agent/opencoder-pipeline.md (the interactive OpenCoder with ten exact text replacements that remove approval gates: approval granted by the task message, never ask or wait, fix test/type/build failures itself and stop only after 3 failed attempts on the same error, leave .tmp files; frontmatter denies the question tool and risky bash/edit patterns: rm -rf, sudo, chmod, curl, wget, docker, kubectl, force push, .env/.key/.secret/.git edits) and copies of all subagents with every 'ask' permission turned into 'deny' (an ask would stall an unattended run). Every replacement is asserted to match exactly once; if upstream changes, the script stops instead of building a half-converted agent; --check only verifies. Used for actions wp-implement and epic-merge-resolve (fixed in 'Codeman: Launch Run': AIFORGE_XDG_CONFIG_HOME + --agent opencoder-pipeline).
- **Auslöser und Eingaben:** Manual build step (no caller found); consumed by the launcher via AIFORGE_XDG_CONFIG_HOME.
- **Ergebnis und Zustand:** generated config directory (rebuilt atomically via .new rename).
- **Fehlerbehandlung:** die() on any non-unique replacement.
- **Externe Systeme:** OpenCode config files.
- **Abstraktion für das Produkt:** [hardening] 'Unattended mode' derivation for any interactive agent definition: auto-grant approval from the task, deny interactive tools and permissions, destructive-command deny list, bounded self-fix attempts, and a build step that fails loudly when the source agent drifts.
- **Beleg:** /home/orologas/bin/aiforge-oac-config:2-19, 45-94, 109-179; n8n 'Codeman: Launch Run' (OAC_AGENTS); /home/orologas/bin/opencode-aiforge:79-83

### RUNTIME: Hand-over file contract in the run workspace

- **Was sie tut:** Pipeline and agent exchange data through files in the run worktree under .aiforge/ (added to the repo's .git/info/exclude if missing). Written by n8n before launch: .aiforge/run/system.md (system prompt), user.md (first message, max 120,000 bytes), and per-action context files (epic-context.md, epic.md/wps.json/manifest.json, pr-context.md, review-context.md + change.diff, manifest.md). Written by the agent: .aiforge/impl.md (implementation report), gate.json (gates), health.json (health runs), wp.md and apply.json (build/apply), merge.md (merge resolve), plan.json (finaliser plan) and results.json (epic-check output). The launcher sets AIFORGE_EXPECT_FILES so the plugin's output guard asks the model once to deliver a missing file instead of reporting the turn as finished. Pipeline files must never be committed (impl-check and epic-check clean fail on them).
- **Auslöser und Eingaben:** n8n 'Code: Run Files Command' (base64, never shell-interpolated), 'SSH: Write Run Prompts', 'Codeman: Launch Run'.
- **Ergebnis und Zustand:** files in the worktree; AIFORGE_EXPECT_FILES env.
- **Fehlerbehandlung:** Prompt over 120,000 bytes or invalid worktree path throws before launch.
- **Externe Systeme:** git worktree, Codeman.
- **Abstraktion für das Produkt:** [core] Run workspace contract: a reserved, VCS-ignored hand-over directory with named input files (prompts, context packs) and required output files (report, verdict JSON, plan), enforced by the runtime (missing output = one reminder, committed hand-over files = gate failure).
- **Beleg:** n8n GitHub.Agentic.Coding nodes 'Code: Run Files Command' and 'Codeman: Launch Run' (expectFiles); /home/orologas/bin/aiforge-impl-check:321-325; /home/orologas/bin/aiforge-epic-check:450-458

### CROSS: Stage hook model as seen from the scripts

- **Was sie tut:** Observed wiring (n8n GitHub.Agentic.Coding / .Events plus routing_rules columns). Before dispatch: aiforge-resume-check, aiforge-project get, aiforge-triage. Before the agent starts ('Code: Run Files Command', by action): epic-gap-analysis/-resolution -> aiforge-epic-context; epic-finalise -> aiforge-epic-check context; epic-document -> aiforge-epic-delta apply + aiforge-epic-check pr; wp-code-review -> aiforge-review-context; wp-review/-confirm/wp-apply/health -> aiforge-wp-manifest (other slice). At launch: env AIFORGE_ACTION (contract), AIFORGE_EXPECT_FILES, AIFORGE_STALL_MS (routing_rules.stall_minutes), AIFORGE_MAX_RUNTIME_MS (max_runtime_minutes), AIFORGE_WATCH_* (watch_after/every_minutes), sampling temperature (routing_rules.temperature), fixed OAC agent for wp-implement and epic-merge-resolve. After the run ('DB: Coding Run Context' reads rule columns on_pass/on_fail/on_empty_action, handover_on_pass, handover_label, handover_command, check_command of the NEXT rule, is_gate/is_health via agent_key goal-gate/health-gate): deterministic check (aiforge-impl-check), contract validation, LLM goal gate or health gate, follow-up or hand-over, hand-over command (aiforge-epic-pr), hand-over writes via aiforge-issue/aiforge-project. Stage map (2026-11-19 audit): epic-refinement (epic-gap-analysis -> epic-gap-resolution), epic-slicing (wp-slicing), wp-building (wp-build), wp-refinement (wp-review -> wp-apply cycle, optional wp-review-confirm), wp-implementation (wp-implement -> gate -> wp-code-review -> gate), epic-finalisation (epic-finalise), epic-documentation (epic-document -> epic-merge-pr), merge-agent rules (epic-merge-resolve/-gate/-health).
- **Auslöser und Eingaben:** routing_rules rows in Postgres evaluated by n8n.
- **Ergebnis und Zustand:** next_action, queue rows, sessions.
- **Fehlerbehandlung:** Context builders never stop the run; gates return reasons; commands outside /home/orologas/bin/<name> are refused by n8n regex.
- **Externe Systeme:** n8n, Postgres, SSH to the host.
- **Abstraktion für das Produkt:** [core] Pipeline stage definition with pluggable hooks per action: pre-run context builders, launch limits (stall, max runtime, watch schedule, temperature, agent profile), expected output files, post-run deterministic check, result contract, LLM goal/health gates with on_pass/on_fail/on_empty transitions, and on-pass hand-over commands; hook commands are allow-listed by path pattern.
- **Beleg:** n8n nodes 'Code: Run Files Command', 'Codeman: Launch Run', 'DB: Coding Run Context', 'SSH: Read Gate File', 'Code: Handover Commands (Valid)', 'Code: Decide Next'; /home/orologas/docs/automation-architecture-activity-audit.md (stage table, not re-verified); /home/orologas/repos/Netrats/.aiforge/db/schema-github_automation.sql (routing_rules comment: static stage/action DAG)

### REPORTING: One run-log comment per run (state-in-comment, folded reports)

- **Was sie tut:** echo '<json>' | aiforge-runlog [--dry-run] keeps ONE summary comment per run. Events: start, note, review, close (single or batch 'events'). State lives as hidden JSON in the first line (<!-- aiforge:runlog {...} -->); the visible markdown is re-rendered deterministically from it on every event (nothing parsed from markdown): headline with run number, profile and model, status (running/closed/failed), result, 'Dein nächster Schritt' vs 'Weiter' (human_next derives it from verdict and review: nothing open, answer questions, decide author steps, take over the action order with ai:ready), the review block and a collapsible 'Technik und Verlauf' list. An open run = newest runlog comment whose status is not closed; the next start creates a new comment; run number = max(count of runlog comments, issue_run_counts.laeufe - 1) + 1; model names normalised. On close it folds the latest agent report (<= 14,000 chars) and progress comments (<= 3,000 each, budget 38,000) of this run into collapsible sections and deletes the originals only after the write succeeded; questions, answers and author comments stay. Size cap 60,000 chars (GitHub limit 65,536) by dropping the oldest events.
- **Auslöser und Eingaben:** n8n Writing 'GitHub: Comment Run Model', 'RunLog: Worktree Failed'; Events 'GitHub: Comment Gate Check', 'GitHub: Comment Integration', 'GitHub: Comment Model Error', 'GitHub: Comment Breather', 'GitHub: Comment Session Lost', 'Code: Review Command' (review), 'RunLog: Close' (JSON via heredoc on stdin).
- **Ergebnis und Zustand:** One GitHub comment per run; originals deleted after folding.
- **Fehlerbehandlung:** Never blocks: errors -> AIFORGE {ok:false, error}, exit 0.
- **Externe Systeme:** GitHub REST via gh (owner login), Postgres (issue_run_counts).
- **Abstraktion für das Produkt:** [core] Run timeline per card: one living summary entry per run (start, model, status, result, next step for the human, hand-over), machine state stored structurally, long agent output collapsed; never blocks the pipeline.
- **Beleg:** /home/orologas/bin/aiforge-runlog:1-229 (render 48-83, human_next 97-115, apply 118-168, fold 171-178); /home/orologas/repos/Netrats/.aiforge/run-profiles.md 'Sammelkommentar je Lauf'

### REPORTING: Run counter mirrored to the board

- **Was sie tut:** aiforge-sync-runs (systemd timer every 2 min, ENABLED) writes the number of runs per issue into the board number field 'Läufe' (GitHub Project 5): reads github_automation.issue_run_counts (a run = one start by the author via ai:ready/assignment, queue kind new or comment; several events in the same minute count once; automatic recoveries, gate checks and integrations do not count; a stopped run counts), pages through all project items (100 per page) and updates only items whose value differs, 15 aliased GraphQL mutations per request; issues without runs stay empty. Project and field ids are hard-coded.
- **Auslöser und Eingaben:** /home/orologas/.config/systemd/user/aiforge-sync-runs.timer.
- **Ergebnis und Zustand:** board field values.
- **Fehlerbehandlung:** DB error -> exit with message; GraphQL error raises.
- **Externe Systeme:** GitHub Projects GraphQL (owner login), Postgres.
- **Abstraktion für das Produkt:** [optional] Derived per-card counters (run count, recovery count) shown on the card or board, computed by the platform rather than mirrored to an external board.
- **Beleg:** /home/orologas/bin/aiforge-sync-runs:1-63; /home/orologas/repos/Netrats/.aiforge/run-profiles.md 'Feld Läufe im Project'

### REPORTING: 'Waiting for you' hand-over mirror

- **Was sie tut:** aiforge-handover-sync mirrors every open issue or PR that carries a hand-over label (routing_rules.handover_label values plus human:review, human:question, ai:pr-ready) of all repositories known in github_automation.issues into github_automation.handover_open (PRs on head branch epic/<N> are attributed to epic <N>; since = updated_at) and replaces the table in one transaction. On any GitHub error nothing is deleted ('never delete from uncertainty'). It exists because aiforge-issue only tracks labels it sets itself, so labels removed by humans would leave an issue stuck in 'wartet auf dich' on the Grafana board (view handover_waiting hides a hand-over once a newer queue row exists). No scheduler or n8n caller exists.
- **Auslöser und Eingaben:** Manual / ad hoc (INFERRED: no caller found).
- **Ergebnis und Zustand:** handover_open rows.
- **Fehlerbehandlung:** Raises before the transaction on GitHub errors; exit 1 with message.
- **Externe Systeme:** GitHub REST (bot token from vault env file), Postgres.
- **Abstraktion für das Produkt:** [ops] 'Waiting for you' inbox derived from card flags and reconciled periodically against the source of truth; never delete on partial information.
- **Beleg:** /home/orologas/bin/aiforge-handover-sync:1-67; /home/orologas/repos/telemetry/docs/ai-pipeline-control-center.md ('Hinweis: handover_waiting ist ein View auf handover_open ...')

### REPORTING: Dashboards fed by this slice (Grafana) and the gaps

- **Was sie tut:** Server load dashboard 'Server: Last und Läufe (Pipeline)' (uid aiforge-server-load, 5 panels: load average on 4 cores, CPU pressure PSI, active runs and agent processes, memory and swap, CPU busy %) reads telemetry.host_sample written by aiforge-host-sample. AI Pipeline Control Center (uid ai-pipeline-control-center, 33 panels per the 2026-11-10 doc; areas pipeline overview counts, reliability KPIs, active-issues table with health logic, errors by model/launcher, productivity, throughput/tokens/cost) uses handover_waiting (status 'wartet auf dich' / 'PR ready', maintained by aiforge-issue and aiforge-handover-sync), health_paused_at/health_reset_at (panel 'Health-Pausen', set by n8n and aiforge-resume-check) and per-package correction-run counts (INFERRED: driven by impl-check failures). AI Usage (uid ai-usage, 24 panels: requests, tokens, cost incl. shadow cost, latency by source/provider/model) is fed from telemetry.usage; in this slice only claude-otel-headers (collector auth for Claude Code export) and the gateway-routed launchers relate to it. GAP: grep of the dashboard JSONs finds no use of triage_decision, session_watch, metric_history, epic_delta or issue_run_counts, so triage decisions, watchdog verdicts, metrics and deltas are recorded but not visible there; the 'Läufe' count is visible only as a board field.
- **Auslöser und Eingaben:** Grafana (read-only user) polling Postgres every 15-60 s.
- **Ergebnis und Zustand:** dashboards only.
- **Fehlerbehandlung:** n/a
- **Externe Systeme:** Grafana, Postgres.
- **Abstraktion für das Produkt:** [ops/optional] Run analytics for the product: overview counts per state, reliability KPIs (failure rate, runs per package, correction runs, health pauses), a waiting-for-human worklist, host load versus concurrent runs, token/cost usage, and surfacing of gate, triage and watchdog decisions that today are recorded but not displayed.
- **Beleg:** /home/orologas/repos/telemetry/grafana/dashboards/server-load.json, ai-usage.json, ai-pipeline-control-center.json (panel titles read, no queries run); /home/orologas/repos/telemetry/docs/ai-pipeline-control-center.md sections 4-5

### CROSS: Uniform helper result protocol and fail-open / fail-closed policy

- **Was sie tut:** Nearly every helper ends with one machine-readable last line: AIFORGE <json> (triage, resume-check, recycle, runlog, impl-check, review-context, epic-context, epic-check, epic-delta, epic-pr) or PROBE <json> (model-probe), usually with exit 0 even on failure so n8n can run '| tail -1' and JSON.parse. Unreadable output means 'continue as before' for advisory helpers (triage, resume-check) or a failed step for gates (impl-check -> contract retry; aiforge-project get throws in 'Code: Resolve Action'). Exit 2 is reserved for usage errors. Context builders, reporters, epic-delta and epic-pr are explicitly 'never stop the run'; gates return explicit failures with reasons.
- **Auslöser und Eingaben:** All n8n SSH call sites ('Code: Triage Decision', 'Code: Parse Resume', 'Code: Check Contract').
- **Ergebnis und Zustand:** last-line JSON.
- **Fehlerbehandlung:** See text; silent degradation is a risk (see lessons).
- **Externe Systeme:** n8n SSH node.
- **Abstraktion für das Produkt:** [core] Uniform typed step-result envelope (status, reason, payload, links) for every hook, gate and context builder, with a declared fail-open vs fail-closed policy per hook type, so the orchestrator never parses text and a broken helper cannot stall the pipeline silently.
- **Beleg:** last-line protocol in /home/orologas/bin/aiforge-triage:19, aiforge-resume-check:11, aiforge-opencode-recycle:17, aiforge-impl-check:22, aiforge-review-context:15, aiforge-epic-check:21, aiforge-epic-delta:13, aiforge-epic-pr:14; n8n nodes 'Code: Triage Decision', 'Code: Parse Resume'

### CROSS: Secret handling pattern for launchers and helpers

- **Was sie tut:** Secrets live in a vault agent that renders env files under /run; launchers read ONE key with sed into a local variable and hand it only to the exec'd process (env), never as a flag value (claude-*, opencode-aiforge, model-probe); unrelated variables inherited from the parent shell are unset with env -u so nothing leaks into isolated profiles; config dirs are chmod 700; per-purpose helpers (mcp-vault-var, mcp-headers-github, mcp-headers-n8n, claude-otel-headers) print only the header JSON. Observed exceptions where a secret appears as a command-line argument (visible in ps): mcp-postgres and mcp-vercel-blob (npx ... --connection-string/--token), the telemetry/vcard/netrats-opencode attach wrappers (--password). github-project-ai scans diffs and new files for token patterns and redacts logs and results. The bot token is read from two places (copilot MCP config file in aiforge-comment/issue/epic-delta/epic-pr, vault env file in the launcher, triage and handover-sync). A plaintext token once sat in the shell rc (found in the 2026-10-25 audit) and was removed.
- **Auslöser und Eingaben:** Every launcher and helper start.
- **Ergebnis und Zustand:** none (environment only).
- **Fehlerbehandlung:** Missing secret -> message and exit 1 (all launchers).
- **Externe Systeme:** Vault agent (OpenBao), tmpfs env files.
- **Abstraktion für das Produkt:** [core/hardening] Central secret store with scoped per-run injection into the agent process environment, redaction of logs and outputs, a secret-pattern scan before a diff is published, one credential source per identity, and no secrets in argv.
- **Beleg:** /home/orologas/bin/claude-qwen:7-43, claude-free:7-43, opencode-aiforge:44-65, mcp-vault-var, mcp-postgres, mcp-vercel-blob, telemetry-opencode, github-project-ai:38-59, 667-686; /home/orologas/docs/github-project-ai-automation-audit.md 'Nachdiagnose GitHub-Zugang'

### LAUNCHER: Copilot run profiles with per-model prompt caps (squad / plain)

- **Was sie tut:** copilot-squad --nemotron|--deepseek|--qwen|--gemma maps a Run Profile to a provider function (copilot-openrouter or copilot-litellm defined in the owner's shell rc, loaded with bash -ic), model and COPILOT_PROVIDER_MAX_PROMPT_TOKENS, then starts Copilot CLI as 'squad' coordinator (--agent=squad). Caps: 70,000 for AI Hub DeepSeek/Qwen and local Gemma (above ~75k DeepSeek streams abort far more often: ~10 % aborted at 25-75k prompt tokens vs ~33 % at 75-125k, measured 30-31 Oct 2026), 425,000 for Nemotron (at 70k only ~9k of conversation fit after ~48k system prompt and tool definitions and Copilot compacted every ~10 calls: 134 compactions in 15 sessions on Netrats#38; no compaction at 750k, max prompt 218k). The guard model for small mechanical subagents (lint, schema, hashes, references, format) is Qwen on the AI Hub for every profile (deliberate break of the same-provider rule, decision 2026-10-31). The model variable is set after the rc is loaded because the rc exports defaults unconditionally. copilot-plain is the EXPERIMENT variant without the squad agent and has no caller.
- **Auslöser und Eingaben:** n8n GitHub.Agentic.Writing 'Codeman: Launch Copilot Session' (copilot-squad); recovery pairing nodes in Events mention copilot-squad launchers.
- **Ergebnis und Zustand:** A Copilot CLI session in the current directory.
- **Fehlerbehandlung:** Missing provider function -> exit 127 with message; usage exit 2.
- **Externe Systeme:** Copilot CLI, LiteLLM/OpenRouter, AI Hub.
- **Abstraktion für das Produkt:** [optional/legacy] Run-profile to (tool, provider, model, context budget, guard model) mapping with per-model prompt caps derived from measured abort and compaction rates.
- **Beleg:** /home/orologas/bin/copilot-squad:4-55; /home/orologas/bin/copilot-plain:4-55; /home/orologas/docs/automation-architecture-activity-audit.md (Copilot CLI no longer main runtime, not re-verified)

### LAUNCHER: Isolated Claude Code profiles through the gateway (qwen / free / private) and telemetry header

- **Was sie tut:** claude-qwen routes Claude Code through the local LiteLLM gateway (ANTHROPIC_BASE_URL without /v1) to a Qwen model alias; claude-free routes to the 'free-pool' alias (automatic free-tier model choice; models change per request so quality, tool use and latency vary; prompts go to third parties, so no confidential data); claude-private starts Claude Code with its own OAuth config dir and unsets work telemetry (OTEL_*, CLAUDE_CODE_ENABLE_TELEMETRY), base URL and model overrides. Each uses its own CLAUDE_CONFIG_DIR (mode 700), maps all model tiers (opus/sonnet/haiku/small-fast/subagent) to the one alias, disables experimental betas and non-essential traffic, and unsets Anthropic key/OAuth/Bedrock/Vertex variables for the process. Compatibility switch CLAUDE_CODE_MODEL_CAPABILITIES=<alias>=-mid_conv_system,-mid_conv_tool_change,-per_turn_effort because Claude Code 2.1.x sends role:system messages mid-conversation, Qwen's chat template requires system first and the AI Hub answers 400; the README adds a troubleshooting table (key rotated, connection refused, 400, model not found, verify via gateway spend logs, reasoning tokens count against small max_tokens). claude-otel-headers prints the OTLP Authorization header JSON for Claude Code's otelHeadersHelper so the collector credential is never in the settings file; this feeds the telemetry collector behind the AI Usage dashboard (INFERRED from the telemetry README).
- **Auslöser und Eingaben:** Interactive use by the owner; no n8n caller found (0 hits).
- **Ergebnis und Zustand:** Claude Code process with its own config dir.
- **Fehlerbehandlung:** Missing key, missing binary -> message and exit 1.
- **Externe Systeme:** LiteLLM gateway, FreeLLMAPI pool, AI Hub, OTLP collector.
- **Abstraktion für das Produkt:** [optional] Provider-agnostic agent CLI through a gateway: model alias per tier, per-model capability downgrades, hermetic profile directories (history, config, telemetry separated by purpose), usage verification through gateway spend logs, and telemetry export of agent CLI usage with runtime-injected auth.
- **Beleg:** /home/orologas/bin/claude-qwen:1-43, claude-qwen.README.md:1-50, claude-free:1-43, claude-private:1-37, claude-otel-headers:1-7; /home/orologas/repos/telemetry/README.md (data flow)

### LAUNCHER: Per-project launchers with repository allow-list guard

- **Was sie tut:** netrats-/vcard-/telemetry-opencode attach an OpenCode TUI to the persistent local opencode server (127.0.0.1:4096, username from config, password read from a vault-rendered file) with --dir set to that project's repository. netrats-/vcard-/telemetry-copilot start Copilot (copilot-openrouter or copilot-litellm via bash -ic; netrats also --agent=squad) in the repo or in COPILOT_WORKTREE but REFUSE to start (exit 2) unless the worktree's git origin equals the expected repository URL (added so the legacy poller can pass COPILOT_WORKTREE safely). 'telemetry' in these names is the project (the Grafana/OTel repo), not a telemetry emitter.
- **Auslöser und Eingaben:** Interactive use by the owner; copilot wrappers were called by github-project-ai.
- **Ergebnis und Zustand:** agent session attached to the project directory.
- **Fehlerbehandlung:** Origin mismatch -> 'Refusing Copilot launch' exit 2.
- **Externe Systeme:** OpenCode server, Copilot CLI, git.
- **Abstraktion für das Produkt:** [optional] Per-project workspace launchers with a repository allow-list guard (origin must match) before an agent with broad tool access starts.
- **Beleg:** /home/orologas/bin/netrats-opencode:1-7, vcard-opencode, telemetry-opencode, netrats-copilot:1-14, vcard-copilot:1-14, telemetry-copilot:1-14; /home/orologas/docs/github-project-ai-automation.md 'Files'

### LAUNCHER: Secret-injecting MCP tool-server wrappers

- **Was sie tut:** mcp-vault-var <NAME> prints one value from the vault-rendered mcp env file (never logged or exported). mcp-headers-github and mcp-headers-n8n print {Authorization: Bearer ...} for Claude Code's headersHelper of the remote GitHub MCP server and the n8n MCP server (the n8n one lets Claude Code read, update and publish n8n workflows). mcp-github runs the official GitHub MCP server as a docker stdio container with the token as container env. mcp-postgres starts the Postgres MCP server through npx with a DSN from the vault; mcp-vercel-blob starts the Vercel Blob MCP server through npx with a token. The pipeline's own OpenCode server runs WITHOUT local MCP servers (each worktree instance would spawn ~9 processes / ~350 MB); pipeline agents use gh and the aiforge scripts instead.
- **Auslöser und Eingaben:** Started by Claude Code / other MCP clients on the owner's machine.
- **Ergebnis und Zustand:** none.
- **Fehlerbehandlung:** Each helper exits 1 with a message when its secret is missing.
- **Externe Systeme:** GitHub MCP, n8n MCP, Postgres, Vercel Blob, docker, npx.
- **Abstraktion für das Produkt:** [optional] Tool-server (MCP) provisioning with runtime-injected credentials; for pipeline runs expose platform capabilities as a few thin CLI/API tools instead of per-run MCP servers.
- **Beleg:** /home/orologas/bin/mcp-github, mcp-headers-github, mcp-headers-n8n, mcp-postgres, mcp-vault-var, mcp-vercel-blob (6-12 lines each); /etc/systemd/system/opencode.service.d/pipeline-no-local-mcp.conf (comment); /home/orologas/docs/opencode-run-profiles.md ('restore_workflow_version', 'publish_workflow')

### OPS: n8n execution-history shrink with backup and automatic rollback

- **Was sie tut:** n8n-shrink-db [--yes] is a one-off maintenance script. Without --yes it only previews (execution counts total / older than MAX_AGE_H (72 by default) / running < 15 min, DB size, free disk). With --yes: abort if executions with status running newer than 15 min exist (unless FORCE=1); stop n8n (downtime ~1-2 min, running executions and webhook events in that time are lost); copy the DB to database.sqlite.pre-shrink (needs ~1.5 GB); delete execution_data and execution_entity older than MAX_AGE_H; VACUUM; integrity_check; write a systemd drop-in 98-pruning.conf (EXECUTIONS_DATA_PRUNE=true, EXECUTIONS_DATA_MAX_AGE, EXECUTIONS_DATA_PRUNE_MAX_COUNT=5000); restart n8n and wait up to 120 s for /healthz; on success delete the backup, on any failure restore it and restart. The deployed drop-in now reads MAX_AGE=24 h (tightened later, INFERRED).
- **Auslöser und Eingaben:** Manual by the owner; docs mention it as a cleanup option (n8n DB 462-482 MB).
- **Ergebnis und Zustand:** smaller database, systemd drop-in.
- **Fehlerbehandlung:** Backup restored on failure; refuses while runs are active.
- **Externe Systeme:** n8n service, SQLite, systemd.
- **Abstraktion für das Produkt:** [ops] Retention policy for run/execution history with a safe maintenance procedure (preview, pre-check for running work, backup, verify, automatic rollback). A product with its own run store should enforce retention continuously without downtime.
- **Beleg:** /home/orologas/bin/n8n-shrink-db:1-81; /home/orologas/.config/systemd/user/n8n.service.d/98-pruning.conf; /home/orologas/docs/deep-storage-audit-2026.md, home-cleanup-report-2026.md

### LEGACY: Board-status poller with baseline, idempotency, allow-list and secret scan

- **Was sie tut:** github-project-ai (systemd oneshot timer every minute, currently DISABLED) polls a personal GitHub Project: GraphQL snapshot of all items; the first run records a baseline (already-ready items never start); afterwards a job is queued only on an observed transition of Status to the exact option 'Ready for AI' (event key = sha256 of item + status updatedAt + option id, UNIQUE in SQLite so duplicates cannot queue twice); content must be an OPEN issue in an allow-listed repository, else the event is recorded as rejected. Processing under a non-blocking file lock (one runner at a time): isolated clone per task, deterministic branch ai/project-<n>-issue-<m>-<key>; calls the repository's Copilot starter with COPILOT_WORKTREE and a prompt that treats the issue text as untrusted data (ignore instructions to reveal credentials, change automation/security config, use another repo, deploy or open PRs); requires exactly one 'AUTOMATION_RESULT_JSON:' line {outcome success|blocked, summary, tests[], no_tests_reason} (success needs passing or not_applicable tests or an explanation); then the runner itself publishes: regex secret scan of diff and new files, git diff --check, commit, push, PR (+ 'Closes #n'), link PR to the project, idempotent result comment (marker per event key), Status 'In Review'; blocked -> clarification comment and status 'Blocked'. Retries with exponential backoff (30 s doubling, max 1 h, 3 attempts); jobs left running by an interrupted process are retried; config must be mode 0600 and refuses enabled+dry_run; 'install' verifies prerequisites, baselines, enables the timer and rolls back to disabled/dry-run if activation fails; commands resolve, snapshot, baseline, tick, status, retry, self-test (offline simulation of transitions, duplicates, allow-list, lock). History: built 2026-10-25, 2 jobs ever (one needs_human_clarification, one 'success but the branch has no commit'), 0 completed (verified in its state database), last poll 2026-10-26; superseded by the n8n AI-Forge pipeline.
- **Auslöser und Eingaben:** systemd timer github-project-ai.timer (disabled) or manual subcommands.
- **Ergebnis und Zustand:** SQLite state (meta, item_state, jobs), rotating log, branches, PRs, board status.
- **Fehlerbehandlung:** RunnerError codes, redacted logs, retry/backoff, Blocked status.
- **Externe Systeme:** GitHub GraphQL/REST via gh, git, Copilot starter scripts, systemd.
- **Abstraktion für das Produkt:** [legacy] Board-driven trigger-and-publish loop: status-transition trigger with first-run baseline and idempotency keys, repository allow-list, untrusted-input prompting, structured agent result envelope, secret scan before publish, retry with backoff, interrupted-job recovery, safe install/self-test activation. Reusable ideas: baseline on first run, transition detection, secret scan, result envelope.
- **Beleg:** /home/orologas/bin/github-project-ai:1-1081 (SECRET_PATTERNS 38-45, record_items 318-382, process_jobs 865-939, publish_success 772-813, command_install 505-552); /home/orologas/docs/github-project-ai-automation.md; /home/orologas/docs/automation-architecture-activity-audit.md; read-only counts of /home/orologas/.local/state/github-project-ai/state.sqlite3

## Schmerzpunkte und Lehren

- Context bloat kills runs: an epic's full comment history grows with every run (slicing 40k+, resolutions 30k+, discarded attempts) and pushed the gap analysis into context compaction after a few steps (Epic #106, 2026-11-09). Fix: a narrow, size-capped input builder; lesson: agents get curated packs, never the raw thread (/home/orologas/bin/aiforge-epic-context:6-13).
- Contract violations cost whole cycles: result comments that broke the output contract were found only after the run, so they are now rejected at post time and the agent corrects itself (aiforge-comment:55-63). The validator code is a hand-maintained COPY of the n8n node 'Code: Check Contract' (aiforge-comment-contract.mjs:3-5): two sources of truth can drift.
- Parallel-run cross-talk: OpenCode --continue resumes the globally latest session; a resumed run attached itself to another issue's session and worktree and received its prompts (2026-11-02: gate checks of Netrats#39 and two test runs of #50 ended in #40's session; state snapshots saved in /home/orologas/docs/rollback/*.json). Fix: explicit --session per worktree. Lesson: a run's session identity must be bound to the card/workspace, never to 'latest' (docs/opencode-run-profiles.md 'Fortsetzung').
- A changed run profile silently ran the old model on resume because the TUI keeps the last message's model (Netrats#38 runs 210/211). Fix: AIFORGE_MODEL pinned on every message (opencode-aiforge:62-64).
- Stopping a run looked like completion: SIGTERM made OpenCode emit session.idle, the plugin sent agentStop and n8n started gate checks and follow-up for a run someone had just stopped (Netrats#38/#39, 2026-11-02). Fix: grace delay before agentStop and a launcher-owned sessionEnd; a mid-turn sessionEnd is treated as 'session lost'. Lesson: distinguish 'agent finished' from 'process ended'.
- Hard kills lose end-of-run signals: Codeman stops sessions with SIGTERM to the process group and may SIGKILL; a watcher that is still a child dies with the tree and the run stayed active / ai:processing (seen on Netrats#40). Fix: setsid-detached watcher plus marker-file claim for exactly-once reporting (opencode-aiforge:86-110).
- Agent runtimes leak resources: the shared opencode serve grew ~250 MB per finished session (309 MB -> 3.3 GB after ~10 sessions, 136 % CPU, 08.11.) -> idle-aware recycle with drain (now superseded, node disabled); OpenCode unpacked ~14 MB native libs into TMPDIR on every start (490 files / 3.7 GB, 2026-11-09) -> per-run TMPDIR. Lesson: isolate per run and reclaim after the run.
- MCP servers are expensive per run (~9 processes / ~350 MB per worktree instance), so the pipeline server runs without local MCP servers and agents use gh plus helper scripts (/etc/systemd/system/opencode.service.d/pipeline-no-local-mcp.conf).
- Provider limits shape the design: AI Hub DeepSeek stream aborts rise with prompt size (~10 % at 25-75k vs ~33 % at 75-125k tokens) -> 70k prompt cap; Nemotron needs a much higher cap (425k) because at 70k Copilot compacted every ~10 calls (134 compactions in 15 sessions, Netrats#38). Free-tier quotas (OpenRouter 1,000 requests/day shared; Zen limit unpublished and varying, 678 vs ~290 requests) are handled by detecting limits and cooling models down instead of counting; model probes and tests burn the same quota; a retry after a provider abort should continue the session (copilot-squad:13-24; opencode-aiforge:149-196; /home/orologas/repos/Netrats/.aiforge/run-profiles.md).
- Per-model compatibility quirks: Qwen's chat template rejects mid-conversation system messages (400 from the AI Hub) so capability flags are needed per model; reasoning tokens count against small max_tokens (claude-qwen.README.md).
- Baselines matter: main may already have type errors and red tests, so every check compares with the state before the change (impl-check:7-9); provider API keys in the agent's environment flipped env-dependent tests and had to be scrubbed (impl-check:40-45); n8n's non-interactive SSH shell lacks ~/.local/bin so PATH is set inside the script (impl-check:38-45).
- Fake quality is real: tests that re-implement the logic inside the test, tautological assertions, browser scripts that never navigate, links to files that are not served -> explicit detectors; manual test cases must be declared with a reason, not faked (impl-check:149-196; review-context:33-79).
- Pipeline files leak into pull requests (.aiforge/, .tmp/, logs, result files): countered by git info/exclude, an impl-check failure and epic-check clean (impl-check:321-325; epic-check:450-485).
- Models invent numbers and evidence: acceptance thresholds must be quoted verbatim from the epic text and the verdict is computed by code (epic-check:14-21, 240-246); review findings must cite existing files and lines (aiforge-comment-contract checkEvidence).
- The next-action pointer drifts: agent key instead of action name, typos, stale after stage completion, empty despite finished stages -> healer added 2026-11-20 with a rollback copy (/home/orologas/pipeline-backup-20261120/aiforge-triage.vor-healer); unsafe repairs escalate with a question instead of guessing.
- Loops without new information: after a health pause a plain restart re-found the same points -> resume-check demands a human reply first (aiforge-resume-check:1-11).
- Automation is rolled out by observation: triage_mode, merge_agent_mode, triage_llm, session_watchdog_mode are 0/1/2 style switches; the watchdog was observe-only per the 2026-11-19 audit and its timer fallback is disabled. Lesson: new automation first runs in shadow mode with a decision log.
- Helpers must not stop the pipeline, so almost all fail open and exit 0 (triage -> run unchanged, runlog -> ok:false, epic-delta -> skipped/failed, epic-pr -> failure comment). Risk: silent degradation. No dashboard shows triage decisions, watchdog verdicts, metric_history or epic_delta (grep of the dashboard JSONs), and metric_history had 0 rows on 2026-11-19, so some gates may never have run in production.
- State is smeared across many stores: labels, assignees, comment markers (<!-- aiforge:... --> first-line rule), board fields, Postgres tables (issues, queue, sessions, work_packages, handover_open, triage_decision, session_watch, epic_delta, metric_history, scheduler_setting, routing_rules), worktree files, /tmp marker files, the legacy SQLite. Reconciliation scripts exist because they drift (handover-sync). The owner already stopped mirroring Stage/Action/Iteration/Next Action to the board (comment in n8n 'Code: Handover Commands (Valid)').
- API cost and identity limits: label, assignee and comment calls moved to REST as the bot (own quota); board writes need the owner's login because the bot token has no project access; aiforge-project caches ids to turn 4 GraphQL calls into 1; sync-runs batches 15 mutations per request.
- Comments are used as database and UI: pagination bugs hid decisions (the MCP reader returned 30 per page oldest first and models read page 1 only, Netrats#38), the run log folds many comments into one (60,000 of 65,536 chars), and results are still passed through comment markers that must be the first line.
- Identity quirks: Vercel Hobby deploys only commits authored by a team member, so commits carry the owner's identity while PRs, comments and pushes stay the bot (opencode-aiforge:66-74); /home/orologas/docs/opencode-run-profiles.md still says git author = bot (documentation drift).
- Credential handling is inconsistent: two sources for the bot token (copilot MCP config vs vault env file), some wrappers pass secrets as command-line arguments (mcp-postgres, mcp-vercel-blob, opencode attach wrappers), a plaintext token once sat in the shell rc (removed 2026-10-25).
- Hard-coded environment: absolute /home/orologas paths, allow-listed /home/orologas/bin command paths (regex in n8n), default repo and board ids (sync-runs, host-sample active_runs, aiforge-project defaults), Astro/vitest/npm-specific checks. A product needs configurable workspace roots and verification adapters.
- The first attempt (github-project-ai, 2026-10-25) processed 2 jobs in total, completed none and was abandoned within a day; the reason is not documented. Its safety ideas (baseline on first run, transition detection, idempotent event keys, allow-list, secret scan, untrusted-input prompt, install/self-test with rollback) were worth keeping; the replacement moved to event-driven n8n plus Postgres.
- n8n operations: the execution database reached ~460-480 MB, shrinking needs downtime and retention was later set to 24 h; update_workflow saves only a draft and publish_workflow activates it (rollback via restore_workflow_version). Pipeline definitions need explicit draft/publish/rollback (docs/opencode-run-profiles.md 'n8n-Änderungen').
- Before each pipeline change the owner makes backups and rollback SQL and quarantines instead of deleting (/home/orologas/pipeline-backup-20261120, /home/orologas/backups/n8n-phase2/rollback-*.sql, /home/orologas/temp/quarantine-2026-11-19, /home/orologas/docs/rollback/*.json). The product needs versioned pipeline definitions and one-click rollback.
- Watchdog false-positive risk (INFERRED): the owner's ToolGuard flagged identical scripts after each edit as loops (Netrats#38) and needed a counter reset on file changes; aiforge-session-digest also counts identical (tool, input) pairs (>= 4 of the last 40 calls), so similar false nudges are plausible, which is why observe mode and the matrix guard exist.
- Some helpers have no scheduler or caller (handover-sync, triage --sweep, triage-switch, model-probe, oac-config, start, shrink-db): self-healing and reconciliation exist as code but depend on someone running them.
- Prose docs in /home/orologas/docs can contradict the code (for example an audit claims all helpers are LLM-free although triage and session-watch can call a model, and describes poller flags that the code does not use); treat code and node definitions as authoritative.

## Offen / nicht belegt

- Published versus draft n8n workflow versions: I read only workflow_entity (name, nodes, connections, active) read-only; n8n keeps published versions elsewhere. Statements such as 'SSH: Recycle OpenCode is disabled and unconnected' reflect the stored definition and are inferred to be current.
- Live database state was not queried: current scheduler_setting values, routing_rules content (check_command, handover_command, watch_*, stall/runtime per action), and the contents of triage_decision, session_watch, epic_delta, metric_history. Counts and mode values quoted from /home/orologas/docs/automation-architecture-activity-audit.md (2026-11-19) are not re-verified and that document contains at least some inaccurate details.
- Not read: the aiforge-hooks plugin (events, loop guard, stall/max-runtime/output guards, model pin, comment pagination), opencode.jsonc, the prompt registry (agents next-action-triage, session-watchdog, goal-gate, health-gate, finaliser and others), the shell rc functions copilot-litellm / copilot-openrouter, secrets-apply and aiforge-set-token (out of slice, secret-related), and all secret files.
- 'aiforge-epic-check run' is not called by any n8n node (only 'context' and 'pr'); it is presumably executed by the epic-finalise agent from its prompt, which I could not see.
- No scheduler or caller found for handover-sync, triage --sweep, triage-switch, model-probe, oac-config, aiforge-start and n8n-shrink-db; assumed manual.
- The launchers claude-opus / claude-sonnet named by the Writing workflow and the 'Claude:Sonnet/Opus' profiles were not found in ~/bin, ~/.local/bin or as named shell functions; opencode-restart.timer is a dangling symlink in timers.target.wants (an earlier time-based restart that was removed, unknown).
- Why github-project-ai was abandoned is undocumented; whether Copilot CLI is still used by the Writing pipeline (copilot-squad is still referenced there) is unclear.
- Exact schemas of triage_decision, session_watch, epic_delta, metric_history, handover_open, issue_run_counts were inferred from SQL in the scripts; the schema export in /home/orologas/repos/Netrats/.aiforge/db is from 2026-11-03 and predates them.
- Grafana: only dashboard JSON titles and table names were inspected, no queries were run; feeders of the AI Usage dashboard other than claude-otel-headers and the gateway are outside this slice.
- Process note: opening the legacy poller's WAL-mode state.sqlite3 read-only refreshed its -shm/-wal sidecar timestamps (SQLite housekeeping, no data written); the n8n database was opened with mode=ro for workflow_entity only. All scratch files are under the session scratchpad slice_s directory.
