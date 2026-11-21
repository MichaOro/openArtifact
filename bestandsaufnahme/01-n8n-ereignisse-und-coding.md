# 1. n8n: Ereignis-Eingang und Coding-Ablauf

[Zurück zur Übersicht](../BESTANDSAUFNAHME.md)

*Gegenstand der Analyse:* n8n event intake and agentic CODING flow: GitHub.Agentic.Coding (51i4DKVhJgKcuphb, inferred id), GitHub.Agentic.Events (hook events + run-end handling + error workflow), InternalReentry, execution.Gate, Copilot.ToolGuard, DB.AgentManagement, GitHub.Gateway, GitHub.SetProjectField, GitHub.UpdateLabels (old, inactive), GitHub.IsCompletion, GitHub.PrepareAgentContext, commitDiggest, tmp-aiforge-errtest. Source: /home/orologas/.n8n/database.sqlite table workflow_entity (read-only), dumped to the scratchpad .c/.txt files under /tmp/claude-30992/-home-orologas-repos-openArtifact/1f79cdd6-6e49-4226-9866-5a8399efd9aa/scratchpad/n8n/.

## Überblick

The coding pipeline is a label/assignee-driven, DB-queue-backed state machine over GitHub issues, with Postgres (schema github_automation + prompt_evolution) as the source of truth and GitHub only as UI/trigger.

TWO MAIN WORKFLOWS (both active)
1. GitHub.Agentic.Coding = "intake + launcher". Triggers: (a) GitHub issues webhook /agenticCoding (HMAC-checked, observation mode only, never blocks); (b) internal webhooks /agenticCodingWake (wake the queue) and /agenticCodingRetry (re-enqueue a follow-up/retry). A Switch filters events: ai:ready label (or aiForgeAgent assignment) on an issue labelled epic or work_package AND assigned to the agent => start; label ai:go => shortcut that re-labels/assigns and thereby re-fires ai:ready; ai:slice => manual stage transition; ai:accept => user accepts a stage. Start path: expire stale queue rows (>3h inactivity) -> resume-check script (health-pause needs a user reply) -> upsert issue + enqueue (unique partial index prevents double enqueue) -> claim oldest runnable queue row (FIFO, FOR UPDATE SKIP LOCKED, dependency check deps_met) -> acquire global server slot (max_active_runs) -> read board fields -> optional triage script -> resolve action (recovery prompt > issues.next_action > start action of artefact type) -> load routing rule (stage, agent, model, run profile, temperature, branch mode, runtime/stall/watch limits) -> load work package -> resolve model via run-profile endpoints/cluster -> abort/close older active sessions of same chain -> create git worktree (+epic branch) -> create a Codeman (tmux) session -> render system/user prompts from versioned DB prompt configs -> register session row BEFORE launch -> write prompt files into the worktree -> launch OpenCode CLI inside the tmux session with env vars (session id, stall ms, max runtime, expected result files, action, watch interval) -> wait up to 120 s for a "prompt submitted" hook event -> mark processing, set labels ai:processing / board Status In progress.
2. GitHub.Agentic.Events = "supervision + result reading + next-step engine". Trigger: POST /copilotEvents (hook events from the CLI plugin: sessionStart, userPromptSubmitted, postToolUse, agentStop, stopFailure, errorOccurred, preCompact, loopAbort, sessionEnd, heartbeat). Every event is logged (copilot_events) and mapped to issue/session. For coding runs, agentStop/stopFailure/sessionEnd on an active session atomically claims the run (session active->closed), kills the tmux session, removes the worktree, reads the result (agent comments with a marker line, or a JSON result file in the worktree, or a deterministic check script), validates the output contract, discards invalid comments, and either retries (max 3 attempts), or decides the next step from routing rules (Decide Next), writes next_action, hands over to the human, or schedules work packages. Errors in the workflow itself are caught by an n8n error workflow, which fails the queue row/issue and hands over to the human.

SUPPORTING WORKFLOWS: InternalReentry (HMAC re-signing forwarder so internal re-entry is accepted by the public webhook), Copilot.ToolGuard (PreToolUse hook loop guard), execution.Gate + GitHub.Gateway (older board-polling dispatcher with a DB-less lock table), GitHub.SetProjectField / IsCompletion / UpdateLabels / PrepareAgentContext (older sub-workflow helpers for project fields, parent-completion, labels, prompts), DB.AgentManagement (LLM that creates/updates agent prompt configs in the DB with an LLM goal-gate), commitDiggest (separate commit-digest + prompt-optimizer prototype), tmp-aiforge-errtest (inactive test that deliberately throws to test the error path).

ISSUE/ARTIFACT STATE MACHINE (reconstructed)
Artefact types: epic and work_package (WP). Pipeline stages per type (from stage names in code): epic-refinement (epic-gap-analysis -> gate -> optional epic-gap-resolution, with on_empty_action skipping resolution if no open points) -> epic-slicing (wp-slicing -> wp-slicing-gate; on pass seeds the work_packages table, creates one sub-issue per WP, relinks [[WP-x]] placeholders to issue numbers) -> per sub-issue wp-refinement (wp-build -> wp-build-gate [creates WP body]; wp-review -> wp-review-gate -> wp-apply -> wp-apply-gate loop; exit when implementation-readiness >= threshold (default 95) and no blocker/critical/high, or rule-based exit after N review cycles, optional independent confirmation review wp-review-confirm) -> implementation (wp-implement with OAC OpenCoder agent -> deterministic check script (impl-check) -> wp-implement-gate -> optional wp-code-review [-gate]; failures loop back to wp-implement with verbatim failures) -> implemented (ai:implemented, board Done) -> epic finalisation (epic-finalise: delta analysis) -> epic-document (PR text; handover_command opens the epic PR; label ai:pr-ready) -> merge (epic-merge-resolve). Health watchdog actions (X-health) run every N cycles of a loop and return continue / accept / pause.
Per-run states: queue.status pending -> claimed -> processing -> done | failed (also waiting); session.status active -> closed | failed; issue.state queued -> processing -> done | failed. Labels: ai:ready (trigger), ai:queued, ai:processing, ai:failed, ai:autonomous, ai:implementation-ready, ai:implemented, ai:pr-ready, ai:gate-missing, human:review, human:question, commands ai:go / ai:slice / ai:accept; assignee aiForgeAgent = agent owns it, human owner = human owns it. Board Status: Ready / Queued / In progress / Waiting / Done.
Handover to human: remove ai:* labels, remove agent assignee, add human assignee, add human:review (or human:question when the last marked agent comment is a question/answer), board Status Ready; the human resumes by setting ai:ready again (or ai:accept / ai:slice / ai:go); after a health pause ai:ready requires a new user comment.

## Fähigkeiten

Verzeichnis: Webhook intake with signature check and fast acknowledge; Event routing by labels, assignee and event type; Durable run queue with FIFO, dependencies and de-duplication; Global concurrency slot / capacity limiting; Data-driven routing rules (action graph per artefact type); Goal gates (LLM judge of another agent's result); Health watchdog (loop budget and user pause); Agent run start: worktree, prompts, tmux session, CLI launch; Model and profile resolution with fallback chain; Supervision via hook events (heartbeat, stall, runtime, output guard, watcher); Result reading and output contract validation; Retry and correction loop; Model-error recovery chain; Breather (context-saturation restart); Tool-call loop guard; Autonomous follow-up (agent-to-agent loop with human brake); Handover to human and resume; Stage handover and manual accept (ai:slice, ai:accept); Epic -> work package decomposition and scheduler; Findings ledger and review quality rules; Code review stage and implementation checks; Cleanup, orphan finders and worktree lifecycle; Error workflow (n8n failure -> run failure); Internal re-entry through signed webhooks; Run log comment and hand-over report; Legacy writing/Copilot gate-check, integration and Claude review (still in the Events workflow); Board-polling dispatcher (older gateway design); Prompt configuration management (agents as data); Commit digest (side product); Triage before run

### Webhook intake with signature check and fast acknowledge

- **Was sie tut:** GitHub issue events hit /agenticCoding. The workflow computes HMAC-SHA256 over the raw body, compares constant-time with X-Hub-Signature-256, logs one observation row per execution (delivery id, event, source github/internal-forwarder/other, valid, reason; also kept in static data, last 200), and answers 'Workflow got started.' (or 401). Currently in OBSERVATION MODE: 'never blocks' - the Respond node is chosen by the signature check but the code comment states it only observes (Phase 4B/F1).
- **Auslöser und Eingaben:** POST /webhook/agenticCoding; headers x-github-event, x-hub-signature-256, x-github-delivery, user-agent; body = GitHub issue payload.
- **Ergebnis und Zustand:** Observation rows; immediate HTTP 200 before heavy work (responseMode responseNode, Respond: Accepted precedes the Restore Request node).
- **Fehlerbehandlung:** Crypto/Verify nodes continueRegularOutput so a failure in the check does not block intake; invalid signature returns 401 JSON.
- **Externe Systeme:** GitHub webhooks; Postgres (webhook_signature_observation).
- **Abstraktion für das Produkt:** Inbound event endpoint per integration with HMAC verification, replay/delivery-id log, ack-first-then-process, and a configurable enforce vs observe mode.
- **Beleg:** GitHub.Agentic.Coding: Trigger: GitHub Agentic Coding Webhook, Crypto: HMAC Raw Body, Code: Verify GitHub Signature, DB: Log HMAC Check, If: Signature Valid?, Respond: Accepted / Respond: 401 Invalid Signature.

### Event routing by labels, assignee and event type

- **Was sie tut:** A 4-output Switch decides what an inbound issue event means: (0) action labeled:ai:ready with assignee aiForgeAgent, OR action assigned:aiForgeAgent while ai:ready is present, and issue labelled epic or work_package => start a run; (1) labeled:ai:go on epic/WP => shortcut (reset ai:ready, assign agent, remove human owner, sleep 2 s, re-add ai:ready, remove ai:go); (2) labeled:ai:slice on epic => manual stage transition; (3) labeled:ai:accept on epic/WP => accept stage. Everything else is ignored.
- **Auslöser und Eingaben:** Webhook headers/body: x-github-event=issues, body.action, body.label.name, body.issue.labels, body.issue.assignees, body.assignee.login.
- **Ergebnis und Zustand:** Branch selection only; commands then mutate labels via helper scripts.
- **Fehlerbehandlung:** Commands validate repo/number by regex and throw on invalid input; unmatched events silently drop.
- **Externe Systeme:** GitHub (labels, assignees).
- **Abstraktion für das Produkt:** Declarative trigger rules: (event type, label added, assignee set, artefact type) => action; plus 'command labels' (go/slice/accept) that humans use to steer the pipeline from the board. The 'sleep 2 + re-apply label' trick shows the need for a first-class 'restart/enqueue' command instead of label toggling.
- **Beleg:** GitHub.Agentic.Coding: Switch: Pre-Gate (epic + ai:ready + aiForgeAgent), Code: ai:go Command, SSH: ai:go Shortcut, Code: ai:slice Command, DB: Stage Handover, Code: ai:accept Command, DB: Accept Stage.

### Durable run queue with FIFO, dependencies and de-duplication

- **Was sie tut:** Each start request becomes a row in github_automation.queue (status pending). Enqueue upserts the issue row (state queued; running/queued issues keep their state) and inserts a queue row only if there is no open (pending/claimed/processing) row for this issue younger than 3 h; a unique partial index on (repository, issue_number, COALESCE(wp_id,'')) for open coding rows guarantees no duplicate (DO NOTHING). Claim = oldest pending row whose dependencies are met (function deps_met compares queue.depends_on with issues.stages_done), taken with FOR UPDATE SKIP LOCKED, attempts+1, started_at, n8n_execution_id stored.
- **Auslöser und Eingaben:** Called from the intake path, from /agenticCodingWake and from /agenticCodingRetry. Inputs: payload jsonb, kind (new|recovery), prompt (JSON for recovery), wp_id.
- **Ergebnis und Zustand:** queue(queue_id, event_id, repository, issue_number, payload, kind, prompt, status, attempts, started_at, finished_at, last_error, n8n_execution_id, wp_id, depends_on, launcher, queue_order, use_case); issues(state, next_action, stages_done, error_summary, processed_at, health_paused_at, health_reset_at, wp_table_comment_id).
- **Fehlerbehandlung:** Stale rows (no activity incl. hook events for 3 h) are failed by 'Expire Stale Coding Runs' before enqueue so they do not block a restart; conflicts end silently; any error after the claim goes to DB: Mark Failed (queue+issue+session failed).
- **Externe Systeme:** Postgres.
- **Abstraktion für das Produkt:** A run queue per pipeline with idempotent enqueue (one open run per card/chain), priority/FIFO ordering, dependency gating on completed stages, atomic claim (skip-locked semantics), stale-run expiry, and wake-up signals when capacity frees.
- **Beleg:** Coding: DB: Enqueue New Issue, DB: Claim Queued Issue, DB: Expire Stale Coding Runs, Trigger: Coding Wake, DB: Enqueue Retry; Events: DB: Close Coding Run (Valid).

### Global concurrency slot / capacity limiting

- **Was sie tut:** Before a run starts, github_automation.acquire_server_slot(queue_id,'opencode-codeman') enforces the global scheduler_setting max_active_runs. If no slot: the row goes back to pending, the issue gets ai:queued and board Status Ready, and the execution ends silently; a later wake (run ended, stage end) retries. Wake is fired after every run end, failure, give-up, stage end (up to 6 wakes for released + new rows).
- **Auslöser und Eingaben:** queue_id; scheduler_setting max_active_runs.
- **Ergebnis und Zustand:** queue.launcher set on success; ai:queued label as visible waiting state.
- **Fehlerbehandlung:** Slot error -> DB: Mark Failed. Orphan finders run on every wake (see cleanup capability).
- **Externe Systeme:** Postgres function; n8n internal webhook /agenticCodingWake (and legacy /agenticWritingWake).
- **Abstraktion für das Produkt:** Configurable max parallel runs (global and optionally per pipeline/repo), visible 'queued' state on the card, automatic drain when capacity frees.
- **Beleg:** Coding: DB: Acquire Server Slot, If: Slot Acquired?, SSH: Mark Issue Queued; Events: Coding: Wake Queue, Code: Wake Items (Stage End), Code: Wake Queue (Run Ended).

### Data-driven routing rules (action graph per artefact type)

- **Was sie tut:** Table routing_rules (use_case, artefact_type epic|work_package, stage, action, agent_key, on_pass_action, on_fail_action, on_empty_action, on_accept_action, mode run|skip|stop, handover_on_pass, handover_label, handover_command, check_command, model, run_profile, temperature, branch_mode, max_runtime_minutes, stall_minutes, watch_after/every_minutes, cycle_start, active) defines the pipeline graph. The start action is the lowest id of the artefact type; the next action after a run is chosen by Code: Decide Next walking on_pass/on_fail with up to 5 skip hops; mode stop => handover to human; missing rule => handover with a hint. A safeguard refuses to restart a cycle_start action of a stage already in issues.stages_done (loop #120 lesson).
- **Auslöser und Eingaben:** Finished run's action + verdict + settings (implementation_ready_threshold, ready_rule_based, ready_rule_min_cycles, ready_confirm, impl_fix_runs, health_first_check, health_check_every, parallel_wp_mode, run_stall_minutes).
- **Ergebnis und Zustand:** issues.next_action (exact next action name), queue prompt JSON for follow-ups.
- **Fehlerbehandlung:** No active rule => run fails via Mark Failed with message; no next action => handover human:review.
- **Externe Systeme:** Postgres.
- **Abstraktion für das Produkt:** A pipeline editor: stages with actions, per-action agent/prompt, model profile, limits, on-pass/on-fail/on-empty edges, skip/stop modes, human-handover flags, deterministic check commands and post-pass hooks. This is the core of the openArtifact pipeline/graph model.
- **Beleg:** Coding: DB: Load Routing Rule, Code: Resolve Action; Events: DB: Routing Rules, Code: Decide Next, DB: Save Next Action.

### Goal gates (LLM judge of another agent's result)

- **Was sie tut:** Rules whose agent_key is 'goal-gate' judge the preceding action. The gate run receives the judged agent's full definition (system+user config of the target agent) and its latest result (newest comment from the agent with marker <!-- aiforge:<action> -->, or the DB draft_md / apply_md for WP actions). The gate writes .aiforge/gate.json {verdict pass|fail, begruendung, kriterien[{kriterium, erfuellt, hinweis}]} which is schema-validated. A readable 'Goal Gate' block (details/summary with criteria checklist and timestamp) is appended to the judged comment. Pass follows on_pass_action; fail follows on_fail_action with the failed criteria as reason (correction run).
- **Auslöser und Eingaben:** Action with agent_key goal-gate; target found via routing_rules.on_pass_action = gate action.
- **Ergebnis und Zustand:** Comment edit, queue prompt reason for the retry, wp_findings ledger.
- **Fehlerbehandlung:** Missing/invalid gate.json counts as contract violation -> up to 3 attempts; no target found -> run fails.
- **Externe Systeme:** Agent CLI, GitHub comments, Postgres.
- **Abstraktion für das Produkt:** A 'review/gate' action type: an LLM (or rule) evaluator with explicit criteria that attaches a verdict to a result, routes pass/fail, and feeds failure reasons back as a correction prompt.
- **Beleg:** Coding: DB: Load Gate Target, SSH: Read Target Comments, Code: Gate Context, Code: Render Prompts (isGate); Events: Code: Check Contract (gate branch), Code: Build Gate Block, SSH: Append Gate Block, Code: Decide Next.

### Health watchdog (loop budget and user pause)

- **Was sie tut:** A 'health-gate' action of the same stage is inserted when the planned next action starts a cycle (cycle_start) and closed_runs >= health_first_check and (c - first) mod health_check_every == 0. It receives stage, iteration count and pending action, writes .aiforge/health.json {verdict continue|accept|pause, begruendung, beobachtungen[{fortschritt|stillstand|rueckschritt}], restpunkte, frage_an_user, loesungsvorschlag>=80 chars}. continue resumes the interrupted step (pendingAction kept in the queue prompt); accept ends the stage via on_accept_action (implementation-ready, implemented, or another action); pause hands over with human:question, the question and a copy-able proposed answer in the comment, and sets health_paused_at so a later ai:ready needs a new user comment (aiforge-resume-check). After resume only sessions since health_reset_at count.
- **Auslöser und Eingaben:** Iteration counts from sessions (closed, action in cycle_start rules of same stage), scheduler_settings.
- **Ergebnis und Zustand:** issues.health_paused_at / health_reset_at, comment block, queue prompt with pendingAction/pendingReason/iterations/pendingWpId, userReply injected into the resumed prompt as 'Antwort des Users'.
- **Fehlerbehandlung:** Invalid health.json -> contract retry; verdict pause without question => invalid.
- **Externe Systeme:** Postgres, GitHub comments, agent CLI.
- **Abstraktion für das Produkt:** Loop supervision: bounded iterations per stage with periodic LLM/rule progress check that can continue, accept-as-done, or pause for a human question, plus a resume protocol that requires a human answer before re-entering.
- **Beleg:** Coding: If: Health Run?, DB: Health Iterations, SSH: Resume Check, Code: Parse Resume; Events: Code: Check Contract (health branch), Code: Decide Next (startRun/isHealthRun), DB: Save Next Action.

### Agent run start: worktree, prompts, tmux session, CLI launch

- **Was sie tut:** For each run: (1) creates an isolated git worktree (detached from origin/HEAD, or a shared epic branch epic/<N>, or per-WP branch epic/<N>-wp/<id> via helper script in parallel_wp_mode; node_modules symlinked); (2) creates a Codeman session (shell mode, working dir = worktree, name <=100 chars) = a tmux-backed terminal; (3) renders the system and user prompts from versioned DB prompt configs (blocks identity, task, context, constraints, knowledge, examples, runtime, output) with placeholders {{issue.url}}, {{issue.repo}}, {{issue.number}}, {{worktree}}, {{branch}}, {{wp.*}}, {{epic.*}}, {{target.*}}, {{gate.output_file}}, {{health.*}}; unresolved placeholders are detected; retry reason, user reply, per-action helper paragraphs (lint self-check, manifest file, findings history, confirmation-review mode) are appended; (4) registers the session row BEFORE launch so hook events map immediately; (5) writes prompts as base64 files .aiforge/run/system.md and user.md (+ optional context files built by helper scripts: manifest, epic-context, epic check context, review-context/diff), adds .aiforge/ to git exclude; (6) types a launch command into the tmux session: env AIFORGE_SESSION_ID, AIFORGE_STALL_MS, AIFORGE_MAX_RUNTIME_MS, AIFORGE_EXPECT_FILES, AIFORGE_ACTION, AIFORGE_WATCH_*, OPENCODE_CONFIG_CONTENT (instructions file, temperature), then /home/orologas/bin/opencode-aiforge --model <provider/model> [--agent opencoder-pipeline] --prompt "$(cat user.md)" (user prompt limited to 120000 bytes); (7) polls the hook-event table for up to 120 s for userPromptSubmitted/agentStop/stopFailure/errorOccurred.
- **Auslöser und Eingaben:** Claimed queue row, routing rule, model resolution.
- **Ergebnis und Zustand:** sessions row (copilot_session_id = runId 'aif-<queue>-<ts>', codeman_session_id, launcher opencode-codeman, workdir, queue_id, action, attempt, model, cluster, wp_id); issue labels ai:processing, board In progress, assignee human removed.
- **Fehlerbehandlung:** Every step has an error output to DB: Mark Failed -> failure comment on issue (<!-- aiforge:error -->) + labels ai:failed, human:review, assignee human, board Ready + Codeman: Stop Stray Session deletes the tmux session; no start event within 120 s = failure.
- **Externe Systeme:** git, Codeman REST API on localhost:3001 (sessions, shell, wait-output, input), opencode CLI via a wrapper script, Postgres prompt_evolution schema.
- **Abstraktion für das Produkt:** An execution engine that provisions an isolated workspace, composes prompts from versioned templates with typed placeholders, launches an external agent CLI in a supervised terminal session with limits (runtime, stall, expected outputs), and verifies that the agent actually started.
- **Beleg:** Coding: OpenCode: Worktree Plan, SSH: Create Worktree, Code: Check Worktree, Codeman: Create Run Session, DB: Load Agent Prompts, Code: Render Prompts, DB: Register OpenCode Session, Code: Run Files Command, SSH: Write Run Prompts, Codeman: Launch Run, DB: Wait Prompt Submitted, Code: Check Run Started.

### Model and profile resolution with fallback chain

- **Was sie tut:** Effective Run Profile = routing rule's run_profile, else the issue board field 'Run Profile'. Profile maps (model_cluster -> model_endpoint, cli=opencode, ordered by cluster then priority, own cluster first, then fallback_cluster) to a provider/model; only provider 'ai-hub' (the LiteLLM gateway) is allowed. Precedence: if rule has profile => profile first, rule.model second; else rule.model first, then issue profile; else server default = first enabled ai-hub endpoint of cluster daily-driver. Result is stored in sessions.model/cluster and notes explain why.
- **Auslöser und Eingaben:** routing_rules.model/run_profile, board field Run Profile, model_cluster, model_endpoint.
- **Ergebnis und Zustand:** sessionModel, sessionCluster, modelNote.
- **Fehlerbehandlung:** Unresolvable model falls back to default; invalid model string fails the launch.
- **Externe Systeme:** Postgres; LiteLLM gateway (indirect).
- **Abstraktion für das Produkt:** Model profiles (named tiers, e.g. cheap/daily/strong) with ordered endpoints, per-action override, provider allow-list and a default; chosen model recorded on the run for usage/cost dashboards.
- **Beleg:** Coding: DB: Load Profile Endpoints, Code: Resolve Model, DB: Default Model; Events: DB: Fail Session (Recovery Attempt) uses next_endpoint/chain_remaining.

### Supervision via hook events (heartbeat, stall, runtime, output guard, watcher)

- **Was sie tut:** The CLI plugin 'aiforge-hooks' reports every event to /copilotEvents. Limits are enforced in the plugin from env vars set at launch: stall guard (no activity for run_stall_minutes => abort turn, stopFailure => pipeline retries), max runtime, output guard (if expected files are missing at end of turn, ask the model once to deliver them), and a detached session watcher (aiforge-session-watch) that looks at the run after watch_after minutes and every watch_every minutes (default 8). Pipeline-side: DB: Log Copilot Event derives error_burst (errors since last non-error event, capped 15 min), compactions_since_progress and breathers_since_stop.
- **Auslöser und Eingaben:** POST /copilotEvents with {event, sessionId, codemanSessionId, payload}.
- **Ergebnis und Zustand:** copilot_events log (also feeds Grafana and the 3 h staleness check).
- **Fehlerbehandlung:** Unmapped events are logged with NULL session; duplicate decisions prevented by unique index per Codeman session.
- **Externe Systeme:** opencode plugin (local), Codeman, Postgres copilot_events.
- **Abstraktion für das Produkt:** Run telemetry channel: agents emit lifecycle events; the engine derives health signals (error bursts, context compaction loops, stalls) and enforces timeouts/expected-artifact contracts.
- **Beleg:** Events: Trigger: Copilot Hook Events, DB: Log Copilot Event, Switch: Copilot Event; Coding: Codeman: Launch Run comments (AIFORGE_* env).

### Result reading and output contract validation

- **Was sie tut:** At run end (agentStop / stopFailure / sessionEnd for codeman sessions) DB: Coding Run Context claims the run atomically (session active->closed) and loads rule columns. The result is then read by action kind: normal agent => comments by the agent since run start (retry x3 on read); the first line must exactly equal <!-- aiforge:<action> -->; extra checks per action: epic-gap-analysis (json block with arrays manuell/autonom), wp-slicing (exactly one json block, arbeitspakete/abdeckung/aenderungen, unique ids, positions 1..n, dependencies only on smaller positions, epic_bezug present), wp-review (line 'Implementation Readiness: n %' and summary.implementationReadinessPercent equal), epic-finalise (one json block with ergebnis/deltas/hinweise/treue_zum_auftrag), epic-document (sections PR-Text/Titel/Beschreibung), wp-code-review (one json block urteil ok|befunde, findings with severity/art/datei/beleg/empfehlung, criteria table AK-n/TC-n consistency). Gate/health => JSON file read from the worktree (base64, max 300 kB, retry x3). wp-build => .aiforge/wp.md normalised (generated heading+metadata, required 8 headings in order, acceptance checkboxes, [[WP-x]] reference check, 60 kB cap, #n -> [[WP-id]] relinking). wp-apply => wp.md + apply.json (strict schema: readiness, changeLog with findingId F-n and outcomes, openDecisions, unresolvedGaps, codeReferences). wp-implement => deterministic check script (impl-check) whose summary decides; passing check posts the report comment.
- **Auslöser und Eingaben:** Run context, comments list, worktree files, DB work package row.
- **Ergebnis und Zustand:** valid/invalid verdict, chosen result comment id/url, invalid ids to discard, review/code-review parsed data.
- **Fehlerbehandlung:** Several valid comments => newest wins; others replaced by a '<!-- aiforge:discarded -->' note (agent edits its own comments). Invalid => retry with reason 'contract-violation: ...' up to attempt 3; then give up (issue failed, handover to human). A check that ran but failed is NOT invalid: it triggers a correction run.
- **Externe Systeme:** GitHub comments via helper CLI, files in worktree over SSH, Postgres.
- **Abstraktion für das Produkt:** Typed result contracts per action (schema/regex/required-sections/consistency rules) validated by the engine, with automatic discard of invalid output and a bounded retry that feeds the violation back to the agent. Results should be stored as structured run outputs, not parsed out of comments.
- **Beleg:** Events: DB: Coding Run Context, SSH: List Run Comments, SSH: Read Gate File, Code: Check Contract, Code: Discard Command, If: Retry Left?, Coding: Request Retry, DB: Fail Coding Run (Retry/Give-up).

### Retry and correction loop

- **Was sie tut:** Invalid contract => session+queue failed, new queue row (kind recovery) with JSON prompt {action, attempt+1, reason, pendingAction, pendingReason, iterations, wpId, pendingWpId} via /agenticCodingRetry (HTTP node retries 3x), same unique-open-row index prevents duplicates. Gate fail / failed impl-check / code-review findings => follow-up run of on_fail_action (or wp-implement) with failures verbatim (up to 2600 chars for wp-implement); the implementation loop has no fixed round limit, bounded by the health gate. Attempt number is part of the session title.
- **Auslöser und Eingaben:** Check Contract result, Decide Next decision.
- **Ergebnis und Zustand:** queue chain per issue/WP; sessions.attempt; discard comments.
- **Fehlerbehandlung:** Request Retry has its own error output to Code: Error Info -> Fail Coding Run (Error) -> handover failed.
- **Externe Systeme:** n8n internal webhook, Postgres.
- **Abstraktion für das Produkt:** Retry policy per action (max attempts, reason carried into next prompt) and a 'correction run' concept distinct from retry; both visible as run history on the card.
- **Beleg:** Events: Coding: Request Retry, DB: Enqueue Retry (in Coding), Code: Decide Next follow(), startRun().

### Model-error recovery chain

- **Was sie tut:** On errorOccurred burst >=6 (the CLI gave up after 5 retries), loopAbort, stopFailure, or preCompact loop (>=10 compactions without subagent progress after 3 breathers), DB: Fail Session (Recovery Attempt) decides once per tmux session (unique index): retry = same model again (AI Hub aborts streams randomly), max 2 per issue since last agentStop, 20 s pause; recover = next healthy endpoint of the chain (own cluster by priority, then fallback cluster, skipping models that failed since last agentStop, up to 10); fallback = Claude Sonnet in a fresh conversation as last line of defence (once); giveup = session stays active, issue labelled ai:failed, ai:processing removed, handed to human (next human comment goes straight into the session). Recovery stops the tmux session, waits (up to 15 s) until Codeman returns 404, then re-enters via the internal webhook with a synthetic 'recovery' event; a context loop forces freshSession. Each step comments <!-- aiforge:error --> with attempt counters.
- **Auslöser und Eingaben:** Hook events; model chain tables.
- **Ergebnis und Zustand:** copilot_events 'recovery'/'giveup'; sessions status failed; issue comment with failed/next launcher.
- **Fehlerbehandlung:** Idempotent decision (decided=false does nothing); legacy launchers keep a 2-recovery rule.
- **Externe Systeme:** Codeman REST, LiteLLM gateway (indirect), Claude CLI as fallback launcher, GitHub REST.
- **Abstraktion für das Produkt:** Provider-failover policy: ordered model chain per profile, same-route retry budget, final fallback to a different vendor, per-run give-up and human handover, all with idempotent decisions and an audit trail.
- **Beleg:** Events: DB: Record Model Error, DB: Fail Session (Recovery Attempt), If: Decision Won?, If: Recover?, Code: Trigger Recovery, GitHub: Comment Model Error.

### Breather (context-saturation restart)

- **Was sie tut:** If the coordinator compacts context 10 times without a subagent finishing and fewer than 3 breathers happened since the last agentStop, the session is closed (not failed, not counted as recovery), the tmux session is deleted, and the same launcher resumes in a fresh conversation that reconstructs state from issue + repo. Claim is atomic (closing the active session).
- **Auslöser und Eingaben:** preCompact events counts.
- **Ergebnis und Zustand:** copilot_events 'breather'; comment <!-- aiforge:breather -->.
- **Fehlerbehandlung:** After 3 breathers, the next loop goes to normal recovery chain.
- **Externe Systeme:** Codeman, internal webhook, GitHub comment.
- **Abstraktion für das Produkt:** Context-health policy: detect saturated agent context and restart with a clean context and state reconstruction, bounded count.
- **Beleg:** Events: DB: Claim Breather, If: Breather Won?, Code: Trigger Breather, GitHub: Comment Breather.

### Tool-call loop guard

- **Was sie tut:** Copilot.ToolGuard is a synchronous PreToolUse hook endpoint. It normalises the call (client copilot or claude, tool, canonical args without description/intent/explanation/reason, sorted keys, md5 fingerprint, sub-agent session = parent/agent_id) and records it in tool_calls. Rule: the 4th identical call (same fingerprint) within 10 minutes is denied; file edits count as progress (identical non-edit calls counted only since last allowed edit); polling/read-only tools are exempt; the 3rd denial in 10 min (once per 3 min, only for runs with a Codeman session) returns 'deny' but also POSTs a loopAbort event so Events treats it as a model error. The reply tells the model not to repeat and that an error result is a result; grants are never given (empty object = default permission flow). Rows older than 7 days purged. Also records spawned sub-agents (task/Agent) for the legacy gate check.
- **Auslöser und Eingaben:** POST /copilotToolGuard with toolName/toolArgs or Claude hook JSON; header x-codeman-session.
- **Ergebnis und Zustand:** tool_calls(session_id, tool_name, fingerprint, agent, args_excerpt, decision allow|deny|abort).
- **Fehlerbehandlung:** Workflow timeout 10 min; responds before reporting abort.
- **Externe Systeme:** Postgres tool_calls; CLI hook configs (.github/hooks/aiforge.json, .aiforge/claude/settings.json).
- **Abstraktion für das Produkt:** Agent guardrails: repeat-call/loop detection with deny then abort escalation, tool allow/deny policy, and a tool-call audit log per run.
- **Beleg:** Copilot.ToolGuard: Code: Normalize Tool Call, DB: Record And Decide, Code: Build Hook Response, If: Abort Run?, n8n: Report Loop Abort.

### Autonomous follow-up (agent-to-agent loop with human brake)

- **Was sie tut:** After a hand-over the Events workflow evaluates 'DB: Autonomous Decision': if the post-run review said next=agent, no question is open, and fewer than 3 autonomous runs happened in a row (autonomous_loop counter, reset after 6 h or when a human started the run), the issue is relabelled ai:ready + ai:autonomous with assignee agent (board Queued) so the next run starts without the human; otherwise human:review or human:question and board Waiting. Writing-flow-era feature (the Claude review script is Copilot-run based) still wired in the generic hand-over path.
- **Auslöser und Eingaben:** Review flag <!-- aiforge:next=agent|human -->, labels.
- **Ergebnis und Zustand:** autonomous_loop(repository, issue_number, loops, updated_at); runlog close line 'autonomous run n of 3'.
- **Fehlerbehandlung:** Session lost removes ai:autonomous.
- **Externe Systeme:** GitHub REST/GraphQL, Postgres autonomous_loop.
- **Abstraktion für das Produkt:** A bounded 'auto-continue' mode with a loop counter and automatic fall back to a human decision.
- **Beleg:** Events: DB: Autonomous Decision, GitHub: Set Labels for Review, GitHub: Set Project Status Waiting, RunLog: Close.

### Handover to human and resume

- **Was sie tut:** A single helper-script pattern: remove ai:ready/processing/queued/implementing, add human:review (or rule label, e.g. ai:pr-ready, human:question), remove agent assignee, assign human, set board Status Ready; failure path additionally adds ai:failed and posts an <!-- aiforge:error --> comment. Stop/skip rules (mode stop/skip) mark queue and issue done, comment '<!-- aiforge:stop -->' and hand over. Triage (aiforge-triage) before a run can end it as wait/none with a handover. A handover_command hook (e.g. open the epic PR) runs first on pass. DB: Track Handover keeps handover_open rows (human:review, human:question, ai:pr-ready) for a Grafana board of 'waiting on me'. Resume = human sets ai:ready again (or ai:accept/ai:slice/ai:go); a pending health pause requires a user comment first.
- **Auslöser und Eingaben:** Decide Next decision, rule columns handover_on_pass/handover_label/handover_command.
- **Ergebnis und Zustand:** handover_open table; issue labels; board Status.
- **Fehlerbehandlung:** Handover commands end with '|| true' so label failures never fail the pipeline.
- **Externe Systeme:** GitHub (labels, assignees, comments, board) through local helper CLIs aiforge-issue / aiforge-project / aiforge-comment / aiforge-runlog.
- **Abstraktion für das Produkt:** Human-in-the-loop handover as a first-class transition: owner change, reason (review/question/failed/pr-ready), a visible 'waiting for me' inbox, and explicit resume commands (continue, accept, slice).
- **Beleg:** Events: Code: Handover Commands (Valid/Failed/WP Done), SSH: Hand Over Issue (Valid), DB: Track Handover, SSH: Mark Issue Failed; Coding: SSH: Mark Issue Stopped, SSH: Triage Handover, Code: ai:accept Command.

### Stage handover and manual accept (ai:slice, ai:accept)

- **Was sie tut:** ai:slice sets issues.next_action to the to_action of an active stage_handover row (command_label ai:slice, artefact epic) and restarts via ai:ready. ai:accept calls accept_stage(repo, issue, type) which returns mode ready (stage ended: WP gets ai:implementation-ready or, for implementation, ai:implemented + board Done + Stage Implementation; waiting packages released), run (next_action = target, restart via ai:ready), busy (a step is running: comment asks to retry later) or none; a comment <!-- aiforge:accept --> documents it.
- **Auslöser und Eingaben:** Command labels from the human.
- **Ergebnis und Zustand:** issues.next_action, stages_done, label changes.
- **Fehlerbehandlung:** busy/none produce explanatory comments and remove the command label.
- **Externe Systeme:** GitHub, Postgres stage_handover and accept_stage().
- **Abstraktion für das Produkt:** Human stage-transition commands on a card (advance, accept as good enough, skip), with guards against acting during a running step.
- **Beleg:** Coding: DB: Stage Handover, DB: Accept Stage, Code: ai:accept Command, SSH: ai:accept.

### Epic -> work package decomposition and scheduler

- **Was sie tut:** After epic-slicing and a passed wp-slicing-gate: Code: Seed Work Packages turns the JSON arbeitspakete into rows in work_packages (wp_id, position, title, skeleton, status planned) - existing created packages are never overwritten (seeding skipped with a note); one sub-issue per package is created via aiforge-wp create (label work_package, idempotent by id/epic) with a skeleton body; ids are saved; [[WP-x]] placeholders are relinked to real #numbers. wp_start() (lock per epic) starts all planned packages whose predecessors are created / integrated (parallel_wp_mode requires integration record): it sets the sub-issue's next_action wp-build and Start Sub-Issue assigns the agent and adds ai:ready (sleep 2 s). Pass of wp-build-gate: sub-issue body replaced with the normalised package text (aiforge-wp update with issue map), package status created, issue done, next step wp-review. Stage end via wp_stage_end() records stages_done, releases waiting packages and enqueues the next stage row with depends_on from the skeleton; wakes the queue (up to 6). A self-updating 'Arbeitspakete (x von n fertig)' table comment on the epic shows id, title, wave (dependency depth), position, status geplant/in Arbeit/Entwurf/fertig/gescheitert/blockiert, attempts, last gate finding, sub-issue; stored comment id, edit-or-post fallback. When wp_start reports done, relink all sub-issues, close the epic row, and hand the epic to the human (Next Action cleared, human:review, board Ready). Failed packages (attempts exhausted) are marked failed; dependents become blocked, epic not touched; the table says these need the author's decision.
- **Auslöser und Eingaben:** Gate pass events, work_packages table, scheduler_settings.
- **Ergebnis und Zustand:** work_packages(repository, epic_number, wp_id, position, title, skeleton, status planned|building|drafted|created|failed, draft_md, apply_md, apply_json, issue_number, issue_id, attempts, last_reason); wp_table_comment_id.
- **Fehlerbehandlung:** Create/relink failures throw (placeholders would stay); WP failure isolates to the package; sub-issue handed to human with ai:failed.
- **Externe Systeme:** GitHub issues/sub-issues via helper CLI, Postgres functions wp_start, wp_stage_end, aiforge_wp_dep_ok, wp_schedule.
- **Abstraktion für das Produkt:** Parent card -> child cards decomposition with dependency graph (waves), a scheduler that starts children when predecessors are done, per-child stage pipeline, a parent progress table, failure isolation and a parent hand-over when all children finish. Maps directly to Epic/Card hierarchy in openArtifact.
- **Beleg:** Events: Code: Seed Work Packages, DB: Seed Work Packages, Code: Skeleton Bodies, SSH: Create Skeleton Issues, DB: Save Skeleton Issue, SSH: Relink Skeletons, DB: WP Start, Code: Start Items, SSH: Start Sub-Issue, SSH: Finish Sub-Issue, DB: Stage End, DB: WP Table Data, Code: WP Table Comment, DB: Close Epic (WP Done); Coding: DB: Load Work Package, DB: Bind Work Package.

### Findings ledger and review quality rules

- **Was sie tut:** Every valid wp-review / confirmation review writes its findings (severity, blocker flag, most similar earlier finding) to wp_findings via ledger_update(); a passed wp-apply-gate writes apply outcomes (clarification, refinement, restructuring, removal, rejected, open_decision, unresolved_gap, no_change) onto the newest review's findings. Prompts include the findings history (rejected/no_change findings may only be re-raised with new evidence), a change mode from the second review on, a manifest of repo facts, a deterministic lint (aiforge-wp-lint) as mandatory self-check. Readiness decision: threshold (default 95 %) + consistency (ready, no blocker, no critical/high) OR rule-based (no blocker/critical/high and either no medium or >= min review cycles) OR optional independent confirm review.
- **Auslöser und Eingaben:** Review comments and apply.json.
- **Ergebnis und Zustand:** wp_findings.
- **Fehlerbehandlung:** ledger update never fails the run (continue).
- **Externe Systeme:** Postgres.
- **Abstraktion für das Produkt:** Structured review findings with identity, dedup against history, resolution status; readiness scoring that is rule-based rather than trusting a percentage.
- **Beleg:** Events: DB: Update Findings Ledger, Code: Check Contract (checkWpReview, applyLogError), Code: Decide Next (wp-review-gate branch); Coding: Code: Render Prompts.

### Code review stage and implementation checks

- **Was sie tut:** wp-implement runs OpenCode with the OAC agent 'opencoder-pipeline' (fixed in the launcher, not in the DB) on a per-epic/WP branch with commits 'Refs #n' and pushes; at end a deterministic check_command of the next step (aiforge-impl-check, restricted to /home/orologas/bin/*) runs in the worktree and posts its report as the aiforge:wp-implement comment when green; red => correction run. Passed wp-implement-gate => optional wp-code-review (other model, minifest review-context.md + change.diff) => optional review gate => verdict: no critical/high => implemented, else correction run with findings. epic-finalise/epic-document/epic-merge-resolve use deterministic helper scripts (epic-check, epic-delta apply, epic-pr).
- **Auslöser und Eingaben:** Rule columns check_command, handover_command; worktree state.
- **Ergebnis und Zustand:** Commits/branches, impl.md, merge.md, PR text.
- **Fehlerbehandlung:** Impl-check infrastructure failure => contract retry; code review JSON consistency rules enforced.
- **Externe Systeme:** git, test/build tooling in the worktree, GitHub PRs via helper CLI.
- **Abstraktion für das Produkt:** Implementation stage with automated checks (tests/build/lint), an independent code-review action, branch/PR strategy per epic, and bounded correction loops.
- **Beleg:** Coding: Codeman: Launch Run (OAC_AGENTS, expectFiles), Code: Run Files Command (reviewCtxCmd, epicStageCmd); Events: Code: Check Contract (wp-implement, wp-code-review), Code: Decide Next.

### Cleanup, orphan finders and worktree lifecycle

- **Was sie tut:** At run end the tmux session is deleted (Codeman DELETE) and marked disposed; the worktree is removed by a guarded script (only paths under ~/worktrees, realpath-checked, dirty changes noted and discarded with reset+clean, extra run temp files removed, then a worktree sweep script). On every wake the Coding workflow runs two orphan finders: server-launcher sessions closed/failed >2 min ago whose workdir has no active session (dispose instance, max 20, SKIP LOCKED), and Codeman sessions listed by the API that belong to non-active pipeline sessions (>2 min) - only pipeline-owned launcher sessions are deleted, never user sessions. Old active sessions of the same chain are aborted/closed BEFORE a new run (closing in DB first so the killed process's sessionEnd is ignored). 'dirty' is recorded in queue.last_error 'worktree-dirty-discarded'. A recycle step for the shared opencode server is disabled (shared server leaked ~250 MB per session, hence one process per run).
- **Auslöser und Eingaben:** Run end; every wake.
- **Ergebnis und Zustand:** sessions.instance_disposed_at.
- **Fehlerbehandlung:** All cleanup nodes continueRegularOutput; legacy 'writing' flow Teardown commits and pushes before removing the worktree.
- **Externe Systeme:** Codeman REST, opencode server API (127.0.0.1:4096), git, Postgres.
- **Abstraktion für das Produkt:** Run sandbox lifecycle: provision, tear down, reap orphans, protect user-owned sessions, record dirty discards, memory hygiene.
- **Beleg:** Events: Code: Cleanup Command, SSH: Remove Run Worktree, Codeman: Stop Coding Session, DB: Mark Instance Disposed; Coding: DB: Claim Orphan Instances, Codeman: List Sessions, DB: Orphan Codeman Sessions, Codeman: Delete Orphan, Code: Plan Aborts.

### Error workflow (n8n failure -> run failure)

- **Was sie tut:** The Coding workflow's errorWorkflow is set to GpO1RoMMtZMZfnDl (the Events workflow's Error Trigger, inferred). Code: n8n Error Event normalises execution id, workflow, node and a sanitised message (@ neutralised, 400 chars). DB: Find Run by Execution maps execution id -> queue row (queue.n8n_execution_id). Every error is logged as n8nError in copilot_events. If a run is found (coding workflow only): queue/issue/session set failed, failure comment with node + message, ai:failed + human:review, assignee human, board Ready, and the queue is woken. Inside the Events workflow, Code: Error Info reconstructs the last executed node of the chain for 'events-error: <node>: <msg>' and fails the run. tmp-aiforge-errtest is an inactive webhook that inserts test rows and throws to exercise this path.
- **Auslöser und Eingaben:** n8n Error Trigger.
- **Ergebnis und Zustand:** copilot_events n8nError; queue.last_error; issue comment.
- **Fehlerbehandlung:** Unmapped errors are only logged.
- **Externe Systeme:** Postgres, GitHub helper CLIs.
- **Abstraktion für das Produkt:** Engine-level failure capture: any crash of the engine itself fails the run it belongs to, hands the card to a human with the failing step, and frees the slot.
- **Beleg:** Events: Trigger: n8n Error, Code: n8n Error Event, DB: Find Run by Execution, DB: Mark Failed (n8n), SSH: Mark Issue Failed (n8n), Code: Error Info; tmp-aiforge-errtest.

### Internal re-entry through signed webhooks

- **Was sie tut:** InternalReentry exposes /agenticWritingInternal and /agenticCodingInternal (header auth). It recomputes an HMAC-SHA256 over the unchanged raw body and forwards it to the public /agenticWriting|/agenticCoding webhook with X-Hub-Signature-256 and X-Aiforge-Forwarded: internal-reentry, so synthetic events (recovery, gatecheck, integrate, breather) take exactly the same path as a GitHub event. Callers (Events code nodes) authenticate with a shared internal token header. Saves no execution data (success/error none).
- **Auslöser und Eingaben:** POST internal webhook with synthetic GitHub-shaped body (action recovery|gatecheck|integrate, aiforge block).
- **Ergebnis und Zustand:** None beyond the re-entered run.
- **Fehlerbehandlung:** Throws if raw body missing; 30 s timeout.
- **Externe Systeme:** n8n itself (127.0.0.1:5678).
- **Abstraktion für das Produkt:** Internal event bus: the engine can emit its own events (retry, recover, follow-up) into the same trigger pipeline as external events, without bypassing validation.
- **Beleg:** GitHub.Agentic.InternalReentry (6 nodes); Events: Code: Trigger Recovery / Trigger Breather / Trigger Gate Retry / Trigger Integration Run.

### Run log comment and hand-over report

- **Was sie tut:** Helper aiforge-runlog posts/updates a single 'runlog' comment (<!-- aiforge:runlog -->) on the issue with notes (breather, error, integration, gate-check) and a close entry containing result (e.g. report delivered, N commits on main, question to author, no valid result), next step for the human ('review then ai:ready'), and failed flag. Result comments are marker-tagged: aiforge:<action>, error, stop, discarded, accept, wp-table, wp-apply, review, breather, resume-blocked, session-watch.
- **Auslöser und Eingaben:** JSON on stdin from Events nodes.
- **Ergebnis und Zustand:** Issue comments used as UI log and as the data channel to agents.
- **Fehlerbehandlung:** RunLog nodes continue on error.
- **Externe Systeme:** GitHub comments.
- **Abstraktion für das Produkt:** Per-card activity log with typed entries (note, close/result, next step for the human) plus typed system comments; in the product these should be first-class run events rather than comment markers.
- **Beleg:** Events: RunLog: Close, GitHub: Comment Model Error / Breather / Session Lost / Gate Check / Integration.

### Legacy writing/Copilot gate-check, integration and Claude review (still in the Events workflow)

- **Was sie tut:** Branch for non-coding use cases (agentic-writing): after coordinator agentStop, a deterministic gate check (rules 16/17 from .squad/routing.md) verifies that a Quality Auditor ran after the last author agent (roles outline-architect, prose-writer, canon-steward, ...), that a marked report/question/answer comment exists and that the report does not claim an audit that did not run; up to 2 automatic re-runs (gatecheck events) then label ai:gate-missing. Then an integration script commits leftovers, force-pushes branch ai/issue-N, cherry-picks new patch-distinct commits onto origin/main with retries when main moves, resets the branch, or aborts and reports conflict files (max 2 automatic conflict-resolution runs). Then teardown commits/pushes/removes the worktree and deletes the branch if all commits are on main. Before hand-over a read-only Claude (Sonnet) review (claude -p with read-only tools, 30 turns, 900 s) is posted as <!-- aiforge:review --> with verdict, findings, next steps, action order and a next=agent|human flag. A lost session (ended mid-turn: last prompt after last top-level agentStop) fails the issue with ai:failed and comment.
- **Auslöser und Eingaben:** Events with use_case agentic-writing (If: Coding Use Case? is false).
- **Ergebnis und Zustand:** copilot_events gatecheck/integrate; ai/issue-N branches.
- **Fehlerbehandlung:** Review never blocks (always exit 0, continueOnError); integration conflicts reported.
- **Externe Systeme:** git, Claude CLI, Codeman, GitHub.
- **Abstraktion für das Produkt:** Optional: independent second-opinion review action before handover; merge/integrate step with conflict handling; deterministic process-compliance checks. Mostly belongs to the writing pipeline - out of scope for a coding MVP but the review-before-handover pattern is reusable.
- **Beleg:** Events: Code: Evaluate Gates, DB: Gate Check Data, Code: Integration Command, SSH: Integrate Run, Code: Teardown Command, Code: Review Command, SSH: Claude Review, DB: Close Session, If: Session Lost?.

### Board-polling dispatcher (older gateway design)

- **Was sie tut:** execution.Gate is a schedule trigger (and an external /executionGate webhook) that reads a lock table (data table workflow_execution_locks); if no row has status RUNNING it generates a run id, inserts a RUNNING lock with idempotency_key 'github-issue-processing' and calls GitHub.Gateway /gateway. GitHub.Gateway queries the Projects v2 board (first 100 items with labels and field values), picks the first item with Status Ready+State unclaimed, then Status Backlog+State processable, records execution id/type/title in the lock and routes: Epic vs Work package -> Analysis / Refinement / Implementation webhooks (/analysis, /refinement, /implementation) based on the board field Stream. Board fields in this design: Status, State, Artefakt type, Stream, Stage, Action, Strategy, Promt key, Git Branch. GitHub.SetProjectField resolves field/option ids and applies a batched GraphQL mutation (update or clear) for all fields. GitHub.IsCompletion, on a webhook, loads the sub-issues of an epic and sets the parent to In progress or Done depending on whether all are CLOSED. The lock is never visibly released in these workflows (inferred: released by downstream workflows that are not in this slice).
- **Auslöser und Eingaben:** Schedule / external webhook; GitHub Projects v2 data.
- **Ergebnis und Zustand:** workflow_execution_locks(idempotency_key, run_id, execution_id, execution_type, execution_item, status).
- **Fehlerbehandlung:** No explicit lock expiry or release seen => a crash leaves the lock RUNNING (inferred pain point).
- **Externe Systeme:** GitHub GraphQL (token embedded in plain text in several nodes), n8n data table, n8n webhooks.
- **Abstraktion für das Produkt:** A scheduler that pulls the next ready card from the board by priority rules and holds a single global execution lock. In the current pipeline this was superseded by the label/queue model but shows the same 'pick next item' capability.
- **Beleg:** execution.Gate: Schedule Trigger, Get row(s), If, Generate Run ID, Insert Lock, Notify: github Gateway; GitHub.Gateway: Code: Find Next Project Item, Router nodes, Set Execution ID in Lock; GitHub.SetProjectField; GitHub.IsCompletion (all active=1 except old label workflow).

### Prompt configuration management (agents as data)

- **Was sie tut:** Prompts live in prompt_evolution.agents (agent_key, active_production_config_id) and agent_configurations(_md) with type system|user, environment production|experimental, status active, version, and eight blocks identity, task, context, constraints, knowledge, examples, runtime, output. The runtime picks the active production config (else experimental), highest version. DB.AgentManagement lets an LLM Agent Configuration Builder create a new agent config (webhook /agentCreationManagement; output via a strict JSON schema with auto-fix parser; model via OpenRouter free models with fallback) or update an existing one (/agentUpdateManagement) with tools to read existing agents/configs; a second LLM 'Goal Gate Refinement Agent' judges the builder output (goal_achieved and quality_passed) and on PASS inserts agent + version-1 production config (SQL built with string interpolation), otherwise re-triggers the builder via webhook (loop). GitHub.PrepareAgentContext (older) resolves prompts with {reference:{node,path,transform}} placeholders. commitDiggest contains prompt-improver agents (user/system prompt improver, migration agent that decomposes old monolithic prompts into the 8-block meta-model, atomicity-gate prompt) and records agent runs (run_type validation, environment experimental) for 'HISTORICAL OPTIMIZATION RUNS'.
- **Auslöser und Eingaben:** Webhooks with configurationDescription / agentName.
- **Ergebnis und Zustand:** agents, agent_configurations, agent_runs.
- **Fehlerbehandlung:** Builder errors continue; autoFix output parsers (retry 5); SQL via string interpolation (injection/quoting risk, inferred).
- **Externe Systeme:** Postgres, OpenRouter (nemotron free models), local OpenAI-compatible model 'gemma-4-26b-sovereign' for commit digests.
- **Abstraktion für das Produkt:** Versioned prompt/agent library with environments (experimental/production), block-structured prompts, templated placeholders, an LLM-assisted authoring/improvement loop with a judge, and run-based evaluation history.
- **Beleg:** DB.AgentManagement: Trigger: Agent Creation Management (External), AI: Agent Configuration Builder, AI: Goal Gate Refinement Agent, DB: Create Agent, DB: Create Agent1, Trigger: Agent Update Management (External); Coding: DB: Load Agent Prompts, Code: Render Prompts; commitDiggest: AI: User Promt Improver, AI: Promt Migration-Agent, Postgres: Insert Agent Run2.

### Commit digest (side product)

- **Was sie tut:** commitDiggest (active) lists branches and up to 100 commits per branch of a personal repo via GitHub REST, dedups by SHA, sorts by date, clusters commits into time windows (min 3 commits, 7-day lookback extended up to 42 days) and asks an LLM per cluster for displayTitle (1-3 words), titleAnchors, iterationSummary and summaryItems based only on commit messages. Sticky note: 'commit diggest n8n version'. Output is not used by the coding pipeline in this slice.
- **Auslöser und Eingaben:** Manual/sub-workflow with repo owner/name/issue/branch (inferred).
- **Ergebnis und Zustand:** Not seen persisted (inferred: displayed or consumed elsewhere).
- **Fehlerbehandlung:** AI agent node onError=continueErrorOutput.
- **Externe Systeme:** GitHub REST, local LLM gateway.
- **Abstraktion für das Produkt:** Optional: AI summary of recent repository activity per card/epic ('what changed in this iteration') as a timeline feature.
- **Beleg:** commitDiggest: HTTP Request, HTTP Request1, Code in JavaScript (clustering), AI Agent, OpenAI Chat Model.

### Triage before run

- **Was sie tut:** For kind 'new' events with a sender, aiforge-triage (queue_id passed) can decide stop (wait/none) with a reason, nextAction and mode; stop => queue and issue done, slot freed, handover to human; any error or unreadable result continues unchanged.
- **Auslöser und Eingaben:** Claimed queue row.
- **Ergebnis und Zustand:** AIFORGE triage {json} last line.
- **Fehlerbehandlung:** Fail-open (continue).
- **Externe Systeme:** Local script reading GitHub state (inferred).
- **Abstraktion für das Produkt:** A pre-flight check step that can cancel or redirect a run before an agent is launched (e.g. already done, waiting on user).
- **Beleg:** Coding: If: Triage Applicable?, SSH: Triage, Code: Triage Decision, If: Triage Stop?, DB: Triage Mark Stopped, SSH: Triage Handover.

## Schmerzpunkte und Lehren

- Duplicate/looping starts are the dominant failure class: the unique partial index uq_queue_coding_open_per_issue, the 3 h stale-expiry, the DO NOTHING enqueue, and the 'Sicherung (2026-11-10, Schleife #120)' guard that refuses to restart a cycle_start action of an already-completed stage all exist because next_action was cleared and the start-action fallback sent WP #120 (Epic #106) back to wp-review about 20 times. DB: Save Next Action now refuses to clear next_action while another 'new' row exists. Lesson: next step must be explicit state, never a fallback; one open run per card/chain must be enforced by the data layer.
- Races between webhook-driven steps: stage end enqueues the next stage and may be claimed within a second, hence the 'keep next_action while a row of another run exists' rule; duplicate agentStop events are neutralised by an atomic claim (session active->closed in one UPDATE ... RETURNING); recovery/breather decisions use unique indexes per Codeman session; wake calls are capped at 6. Lesson: claim run-end atomically and make every decision idempotent.
- Killing a run causes a second event: old sessions are closed in the DB BEFORE the tmux session is deleted so the killed process's sessionEnd is ignored (and a 'lost' detection that checks last prompt vs last top-level agentStop). Lesson: close state first, then kill; ignore late events from superseded sessions.
- Session registered before launch so early hook events map to it; start is verified by waiting for userPromptSubmitted (120 s); otherwise failure. Lesson: a launch is not successful until the agent proves it received the prompt.
- Shared opencode server leaked about 250 MB per session; replaced by one OpenCode process per run in its own tmux session (Codeman), with the recycle node left disabled and orphan finders as a safety net. Lesson: per-run process isolation, explicit reaping of orphans after crashes/kills, never touch user-owned sessions.
- AI gateway (LiteLLM/ai-hub) aborts streams at random: same-route retry (2x, 20 s pause) before switching endpoints; model chain per cluster with fallback cluster, then Claude Sonnet as last line of defence, then give-up with a human handover that keeps the session alive so the next human comment goes straight into it. Lesson: separate transient provider faults from model behaviour (loop abort and context loop never retry on the same model).
- Agents ignore deny messages and loop: tool-call fingerprint guard (4th identical call denied, 3rd denial aborts the run), edits count as progress; polling/read-only tools exempt; file writes through bash are not recognised (documented limitation). Lesson: guardrails need progress awareness and escalation to abort.
- Context saturation: 10 compactions without subagent progress => 'breather' (fresh conversation, max 3), then normal recovery; a context loop is not helped by resuming the same conversation (freshSession). Lesson: detect context loops and restart with state reconstruction.
- Output format drift is the second-largest cost: results are parsed out of GitHub comments by exact first-line marker and per-action schemas; invalid comments are rewritten to '<!-- aiforge:discarded -->'; retries limited to 3; many contract rules (wp slicing consistency, readiness line = JSON value, AK/TC criteria table, apply.json strict keys). The 'proposedChange only on rejected/open_decision/unresolved_gap' normalisation and wp.md heading generation by the pipeline (never the model) show that deterministic normalisation beats retrying. The OAC runs and gates write JSON FILES in the worktree because comment parsing was brittle. Lesson: structured output channel, deterministic normalisation, and lint scripts the agent runs on itself (aiforge-wp-lint) before finishing.
- Readiness percentages fluctuate (a medium finding produced 95 % and 90 %), so a rule-based exit (no blocker/critical/high; mediums only after N review cycles) and an independent confirmation review were added. Review loops are unbounded by count and are bounded only by the health gate; the health gate needs a reset (health_reset_at) after a human answers. Lesson: quantitative LLM scores are unreliable gates; keep a progress watchdog.
- Human handover state is encoded in labels+assignee+board status across 3 systems; helper scripts always end with '|| true' (label failures never fail the pipeline) and the sequence matters (remove labels, then assignees, then add; board Ready LAST after the trigger labels are gone; 'sleep 2' between assign and ai:ready so the assignment is visible). Lesson: single source of truth for ownership/state inside the product; no label toggling tricks.
- Health pause requires a user reply before ai:ready is honoured (aiforge-resume-check posts <!-- aiforge:resume-blocked -->). Lesson: a pause needs an explicit answer capture, not just a re-trigger.
- Handover tracking was added for Grafana (handover_open) because GitHub could not be queried cheaply; the Grafana dashboards (AI Usage, AI Pipeline Control Center) are fed by DB tables sessions, queue, copilot_events, handover_open, wp_findings (inferred: dashboards not inspected in this slice).
- SECURITY pain points (values intentionally not reproduced): a GitHub personal access token is embedded in plain text in nodes of GitHub.Gateway, GitHub.SetProjectField and GitHub.IsCompletion; a shared 'internal re-entry' token is hard-coded in several Events code nodes (comment says it must match the guard node); HMAC verification is observation-only so forged webhooks are not rejected; SQL in DB.AgentManagement and PrepareAgentContext is built with string interpolation of LLM/webhook values. Lesson: product needs a secret store, enforced signature verification and parameterised queries.
- Operational debt: the workflow carries a legacy writing/Copilot branch (gate checks, integration cherry-pick, Claude review, autonomous follow-up) alongside the coding branch, selected at runtime by use_case; WEBHOOK_PATHS maps both; duplicate worktree teardown scripts exist (normal + give-up); execution.Gate lock is inserted but never visibly released (crash leaves RUNNING, inferred); GitHub.UpdateLabels is inactive and replaced by helper CLIs; tmp-aiforge-errtest is an inactive test hook. Lesson: model use cases as pipeline definitions instead of branching inside one workflow.
- The n8n workflows are only the orchestration layer: most real logic lives in local scripts under /home/orologas/bin (aiforge-issue, aiforge-project, aiforge-comment, aiforge-runlog, aiforge-wp, aiforge-resume-check, aiforge-triage, aiforge-impl-check, aiforge-epic-check, aiforge-epic-delta, aiforge-review-context, aiforge-wp-manifest, aiforge-wp-lint, aiforge-wp-worktree, aiforge-worktree-sweep, opencode-aiforge, aiforge-session-watch) and in Postgres functions (acquire_server_slot, deps_met, wait_run_event, wp_start, wp_stage_end, accept_stage, ledger_update, next_endpoint, chain_remaining, aiforge_wp_dep_ok). Their code was not inspected here; the product needs equivalents as built-in actions.
- Timezone and API quirks documented in code: REST 'since' filter unreliable around DST changes (comments are filtered client-side); Codeman rejects session names over 100 characters; --prompt argument limited to ~128 KiB (guard at 120000 bytes); SSH node does not fail on non-zero exit so exit codes are checked in Code nodes; prompts/comments travel base64-encoded to avoid shell interpolation; @-mentions neutralised in error comments to avoid notifying people.
