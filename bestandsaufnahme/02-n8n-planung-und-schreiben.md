# 2. n8n: Planung (Epics, Work Packages) und Schreiben

[Zurück zur Übersicht](../BESTANDSAUFNAHME.md)

*Gegenstand der Analyse:* n8n PLANNING and WRITING workflows (read-only from workflow_entity in /home/orologas/.n8n/database.sqlite). Active (active=1): GitHub.EpicSlicing, EpicSlicingContext, EpicWPRefiner, EpicClarification, EpicDecisionIntegration, Analysis, Refinement, SequenceBuilding, CreateManifest (35-node version), CreateReview, ApplyReview, OutlineRefinement (50-node version), SceneBlockWriting, Agentic.Writing. Inactive (active=0): CreateManifest (21-node old), OutlineRefinement (27-node old), OutlineContinuityReview, SeuqnzeStart, Prompt Optimization & Validation Loop, Slack.IntakeGateway, Slack.StakeholderFeedback, playground, My workflow. Referenced but outside slice: execution Gate / GitHub.Gateway, GitHub.SetProjectField, GitHub.PrepareAgentContext (peeked), Postgres prompt store contents, Redis TTLs.

## Überblick

The planning/writing pipeline is a chain of webhook-triggered n8n workflows that move a GitHub issue (an Epic, a Work Package, or a manuscript outline) through stages. A GitHub Project item carries the routing contract (fields: stream, stage, action, strategy, artefaktType, promptKey, gitBranch; status Backlog/Ready/In Progress; state processable/claimed/unclaimed; a processingLock.run_id row in a data table workflow_execution_locks). The Gateway posts the item to /analysis or /refinement, which route by stage x action.

PLANNING (software): (1) Epic Clarification: AI gap analysis of the epic produces a questionnaire split into manual questions (human) and autonomous ones; asked one by one in a dedicated Slack channel. (2) Stakeholder answers are semantically mapped to questions (open/partial/answered) in Redis; when none is open, Decision Integration rewrites the Epic issue body into a structured epic spec. (3) Epic Slicing: a repo-evidence manifest is built (AI picks relevant files from the tree, a goal gate validates, files are fetched), an Initial Slicer proposes Work Package candidates, a Slicing Quality Gate accepts/rejects. (4) EpicWPRefiner recursively (max depth 3) runs an Atomicity Gate per WP and, if too big, decomposes into child responsibilities, each specified into a full structured WP. Final WPs become GitHub sub-issues of the epic, are added to the Project board and parked at stage Review / action Create Review. (5) Review loop: CreateReview (AI requirements review with severity/confidence/blocker + AI quality gate deciding whether to continue) posts a versioned comment; ApplyReview (AI applies every finding with a per-finding change log + an AI gate that decides whether the output may replace the WP) loops back to CreateReview until the gate says stop, then the item is released as Ready for the Implementation stream.

WRITING (manuscript): author hints per sequence -> Outline Elaboration (Sequence Builder agent + Goal Gate PASS/RETRY/BLOCKED + commit-message agent + Slack human approval) commits a sequence/scene/beat JSON outline to the repo -> Narrative Outline Review (reviewer agent + goal gate) -> Narrative Outline Refinement (refiner agent with change log + commit message + goal gate + Slack approval) commits the revised outline. Continuity review per sequence (inactive) and Scene Block Writing (active but only a skeleton that flattens scenes into word-count blocks) prepare prose writing. Agentic.Writing is the queue/launcher that hands a writing issue to an external CLI agent in a Codeman tmux session in its own git worktree.

Cross-cutting: prompts are loaded from a versioned Postgres prompt store (agent_key, system/user, blocks identity/task/context/constraints/knowledge/examples/runtime/output with node references); every LLM step is wrapped by structured-output parsers with auto-fix; nearly every generative step is followed by a separate LLM gate; retries are counters carried in the payload; a prompt self-optimisation loop exists but is inactive. Control flow is webhook chaining, with state in GitHub (issue body, comments, labels, project fields), Redis (Q&A), Postgres (queue, prompts) and Slack.

## Fähigkeiten

Verzeichnis: Item routing by stage and action (dispatcher); Run lock and claim/release state machine; Repository evidence manifest (CreateManifest); Sibling work-package context; Epic gap analysis and clarification questionnaire; Stakeholder answer evaluation and Q&A loop; Slack intake gateway (route free text to a channel/epic/repo); Epic decision integration (answers become a structured epic); Epic slicing into Work-Package candidates; Recursive atomicity gate and WP specification (EpicWPRefiner); Materialising Work Packages as board cards; Requirements review of a Work Package (CreateReview); Apply review to the Work Package (ApplyReview) with acceptance gate; Review/Apply loop termination and release to implementation; Layered prompt store with versioning (prompt_evolution); LLM gate pattern: goal gate, quality gate, structured-output auto-repair; Outline elaboration (Sequence Builder) with goal gate and human approval; Narrative outline review then refinement (active version); Multi-agent outline review (older design); Chapter continuity review across sequences; Scene-block preparation for prose writing (work in progress); Manual seeding of author hints / chapter manifest; Writing issue queue and external CLI launcher (Agentic.Writing); Prompt self-optimisation loop (experimental); Unrelated template workflow ('My workflow')

### Item routing by stage and action (dispatcher)

- **Was sie tut:** Receives a board item from the Gateway, writes the n8n execution id into a lock row, marks the item claimed/In Progress, then routes: stage Execution -> action Clarification or Slicing (or Is Completion); stage Review -> Create Review or Apply Review. A second, smaller router (Refinement) does the Review routing and, for Create Review, first fetches sibling Work Packages (see Sibling context).
- **Auslöser und Eingaben:** POST /analysis or /refinement with body.project {stream, stage, action, strategy, artefaktType, promptKey, gitBranch}, body.content {issue id, number, title, body, url, repository, labels}, body.processingLock.run_id.
- **Ergebnis und Zustand:** Item set claimed/In Progress; lock row gets execution_id (and execution_type = artefaktType-stream-stage-action in Create/Apply Review).
- **Fehlerbehandlung:** None visible; an unmatched stage/action simply ends (inferred: item stays claimed).
- **Externe Systeme:** GitHub Projects (via sub-workflow SetProjectField), n8n data table workflow_execution_locks, other n8n webhooks.
- **Abstraktion für das Produkt:** A pipeline stage/action dispatcher: a card moving into stage X triggers the action registered for (pipeline, stage, action). Each action is a pluggable handler; the engine claims the card (lock + status) before running it and releases/advances it afterwards.
- **Beleg:** GitHub.Analysis nodes 'Router: Execution vs Review Stage', 'Router: Execution Action (Slicing)', 'Router: Review Action (Create/Apply)', 'Action: Set Status to In Progress'; GitHub.Refinement 'Router: Is Review Stage?', 'Router: Create vs Apply Review'.

### Run lock and claim/release state machine

- **Was sie tut:** Every planning workflow starts by writing its execution id into a lock row keyed by run_id and sets the card to status In Progress, state claimed. On completion it sets the card to a next status/state and (for slicing, review) marks the lock COMPLETED and pings the execution gate so the next unclaimed item can be picked.
- **Auslöser und Eingaben:** processingLock.run_id from the webhook payload.
- **Ergebnis und Zustand:** Lock row {run_id, execution_id, execution_type, status}; Project item fields status/state/stream/stage/action.
- **Fehlerbehandlung:** If a workflow dies mid-way the card stays claimed (inferred); no healer visible in this slice. EpicClarification updates only execution_id, never COMPLETED (inferred gap).
- **Externe Systeme:** n8n data table, GitHub Project fields, execution Gate webhook.
- **Abstraktion für das Produkt:** Card run lifecycle: queued/processable -> claimed -> done/next stage, with a run record (run id, execution id, type, status) and a scheduler tick after each run so the next ready card starts. Idempotent claim so one card is never processed twice.
- **Beleg:** 'Set Execution ID in Lock' / 'Set Execution ID in Lock1' (dataTable workflow_execution_locks) in EpicSlicing, CreateReview, ApplyReview, EpicWPRefiner, EpicClarification; 'Notify: github Gateway' POST /webhook/executionGate; 'Action: Set Status to ...' sub-workflow calls with status/state values.

### Repository evidence manifest (CreateManifest)

- **Was sie tut:** Builds the AI's working context from a git repo: resolve owner/repo and branch (project.gitBranch or default branch), fetch the recursive file tree, filter to allowed prefixes (src/, docs/, tests/, a few config files) and exclude docs/work-packages, docs/reviews, docs/audits, ask an AI agent (prompt key collect-repo-context) which paths are relevant evidence (path-only reasoning, recommended vs optional), have a Goal Gate agent grade it PASS/RETRY/BLOCKED, validate every returned path against the real tree (drops hallucinated paths), download each file and return {repositoryTree, sourceContext = JSON {files:[{path,content}]}}.
- **Auslöser und Eingaben:** Obj = card payload with content.url / body.url, project.gitBranch, retryCount.
- **Ergebnis und Zustand:** sourceContext string and repositoryTree string passed in memory to the caller; nothing persisted, rebuilt on every call (and again at every review/apply round).
- **Fehlerbehandlung:** Goal gate RETRY re-calls the whole workflow up to 3 times; hallucinated paths discarded; if retries are exhausted or gate is not PASS the branch ends without output (inferred silent stop). No file size or token cap seen (inferred risk).
- **Externe Systeme:** GitHub REST (git trees, contents, raw download), Postgres prompt store, LLM via OpenRouter free models.
- **Abstraktion für das Produkt:** Context builder / evidence retrieval step: given a card and a repo, produce a verified set of files as grounded context. Needs: tree listing with include/exclude rules, AI file selection with deterministic validation against reality, a quality gate on the selection, bounded retries, content fetch, and caching so the same manifest is reused by later steps.
- **Beleg:** GitHub.CreateManifest (35 nodes): 'Code: Filter and Format Tree', 'AI: Collect Repo Context Agent', 'AI: Goal Gate Agent', 'Code: Validate Manifest Against Tree', 'GitHub: Fetch File Metadata'/'Download Raw File Content', 'If1' (retryCount < 3) -> 'Call GitHub.CreateManifest' (self-recursion). Called by EpicSlicing, EpicClarification, EpicDecisionIntegration, CreateReview, ApplyReview. Old inactive 21-node version used DeepSeek and a retry counter.

### Sibling work-package context

- **Was sie tut:** Before a WP review, looks up the parent epic of the WP issue via GraphQL, lists all its sub-issues, drops the current one and attaches the rest as epicSlicingContext.siblingWorkPackages; falls back to an empty list when no parent.
- **Auslöser und Eingaben:** payload.content (issue id, number, repository).
- **Ergebnis und Zustand:** payload + epicSlicingContext, read by CreateReview/ApplyReview prompts.
- **Fehlerbehandlung:** Fallback to empty sibling list; limit of 100 siblings (seen). One node uses a hard-coded bearer token in the header instead of the credential store (pain point, value not reported).
- **Externe Systeme:** GitHub GraphQL (parent, subIssues first:100).
- **Abstraktion für das Produkt:** Hierarchy-aware context: a card can see its parent and sibling cards (their titles and bodies) so scope overlaps and dependency contradictions are detectable.
- **Beleg:** GitHub.EpicSlicingContext nodes 'Fetch Parent Issue ID', 'Fetch Sub-Issues via GraphQL', 'Has Parent?', 'Merge Sibling Data', 'Fallback: Empty Sub-Issues'; invoked from GitHub.Refinement before createReview.

### Epic gap analysis and clarification questionnaire

- **Was sie tut:** For an epic, builds repo evidence, loads the active prompt 'epic-gap-analyzer', and runs a Clarification Agent (primary and fallback model, Redis chat memory 48h TTL) that returns a questionnaire with two lists: manuell (needs a human) and autonom (AI can decide) questions, each with id, title, description, question, status, answers; optional options/allowFreeText/answerType. Saves the state in Redis under epic:<channel> with meta {github issue id, url}, creates a Slack channel named after the epic (sanitised, max 40 chars), invites the owner and posts the first open question.
- **Auslöser und Eingaben:** POST /epicClarification from Analysis when action contains Clarification; or from Slack.IntakeGateway (inactive).
- **Ergebnis und Zustand:** Redis key epic:<shortChannelName> {meta, questionnaire}; Slack channel; question status vocabulary open/offen, partial/teilweise, answered/beantwortet (mixed German/English).
- **Fehlerbehandlung:** Throws on missing epic title / empty channel name / missing manuell list. Channel name collision handling not seen (inferred risk). Fallback LLM configured.
- **Externe Systeme:** Slack (channels, invite, post), Redis, Postgres prompt store, OpenRouter LLM, GitHub (manifest).
- **Abstraktion für das Produkt:** Clarification step: analyse a card's description for gaps, classify questions as 'needs human' vs 'AI may decide', persist the Q&A session on the card, and open a conversation surface (comment thread/channel/inbox) that asks questions one at a time with choice options and optional free text.
- **Beleg:** GitHub.EpicClarification: 'Epic Clarification Agent', 'Output JSON Parser' (manuell/autonom), 'Persist: Save Epic State to Redis', 'Prepare: First Question', 'Code: Build Slack Channel Name', 'Create Slack Channel', 'Invite Slack User', 'Send Slack Question', 'Redis Conversation Memory'.

### Stakeholder answer evaluation and Q&A loop

- **Was sie tut:** A Slack message in a project channel triggers /stakeholderFeedback. A Q&A Evaluation Agent loads the question catalog through a Redis tool, maps the free-text answer semantically to one or more questions, rates coverage none/partial/complete, extracts evidence, newRequirements and irrelevantContent and a nextAction. A code node appends the response to the question, updates status (open/partial/answered), sets session status waiting_for_user or complete, saves to Redis (TTL 24h) and posts the next open question. When no open question remains it calls Epic Decision Integration.
- **Auslöser und Eingaben:** POST /stakeholderFeedback {channelID, channelName, response}.
- **Ergebnis und Zustand:** Redis epic:<channel> with responses[] {coverage, answer, reason, evidence, createdAt}, session {currentQuestionId, status, lastActivity}; Slack replies.
- **Fehlerbehandlung:** Strict validation errors if state/meta/questionnaire missing or coverage invalid. Note: next question picks only status 'open', so a 'partial' question is not re-asked despite the comment saying it should be (seen in code). Redis TTL 24h means a pause longer than a day loses the session (inferred). WORKFLOW IS INACTIVE, so the answer path is not live today (inferred consequence: clarification can start but not complete).
- **Externe Systeme:** Slack, Redis, OpenRouter LLM, n8n webhook to decision integration.
- **Abstraktion für das Produkt:** Human-in-the-loop answer intake: free-text replies are matched to open questions, partially answered questions stay open, new requirements discovered in answers are captured, and the session auto-advances to the next question or to the next stage when complete.
- **Beleg:** Slack.StakeholderFeedback (inactive): 'Q&A Evaluation Agent', 'Output JSON Parser' (questionAssessments, newRequirements, nextAction), 'Update Q&A State in Redis', 'Prepare Slack Question', 'Check Bot Message', 'Notify: Request Epic Decision Integration'.

### Slack intake gateway (route free text to a channel/epic/repo)

- **Was sie tut:** Messages in one intake Slack channel (bots ignored) are analysed by an AI that decides whether an existing Slack channel fits (using channel list and optionally channel history) or a new channel is needed, returning decision, channel, reason and confidence. Existing channel -> forwards to stakeholder feedback. New -> a second agent identifies the target GitHub repository from the user's repositories and file trees (id, nameWithOwner, defaultBranch, confidence, evidence), creates and populates a new channel and starts Epic Clarification. Messages in other channels go straight to stakeholder feedback.
- **Auslöser und Eingaben:** Slack message trigger.
- **Ergebnis und Zustand:** New Slack channel, forwarded webhook call; no durable intake record.
- **Fehlerbehandlung:** autoFix parsers; confidence is returned but no threshold gate seen (inferred). Inactive.
- **Externe Systeme:** Slack, GitHub REST (user repos, trees), OpenRouter LLM.
- **Abstraktion für das Produkt:** Inbound intake / triage: a free-text request is matched to an existing card/thread or creates a new project context with the right repository, with a confidence score.
- **Beleg:** Slack.IntakeGateway (inactive): 'Check Intake Channel', 'AI Agent' (entscheidung existing_channel/new), 'AI Agent1' (repository), 'Create Slack Channel', 'Notify: Request Epic Clarification', 'Notify: Request Stakeholder Feedback'.

### Epic decision integration (answers become a structured epic)

- **Was sie tut:** Fetches the epic issue, the Slack channel and the Redis Q&A state, builds repo evidence, loads prompt 'epic-gap-resolver', and runs an Epic Decision Agent that outputs a structured epic: title, requirements (scope, outOfScope, functional, non-functional with ids), capabilities, success criteria, architecture concept (with rationale), system context (components, interfaces, data flows), data concept (objects, storage, quality, permissions, lifecycle) and constraints (dependencies, risks, assumptions). A code node converts it to Markdown with German headings and overwrites the epic issue body.
- **Auslöser und Eingaben:** POST /ecpicDecisionIntegration with payload {epicId, issueUrl, channelID, promtKey}.
- **Ergebnis und Zustand:** Epic issue body replaced by generated Markdown.
- **Fehlerbehandlung:** Validates payload JSON, channelID, and that the fetched issue node id equals the webhook epicId; otherwise throws. No quality gate after the epic agent and no status transition afterwards (inferred gaps). Old body overwritten (only GitHub edit history).
- **Externe Systeme:** GitHub REST, Slack, Redis, Postgres prompts, OpenRouter LLM.
- **Abstraktion für das Produkt:** Spec consolidation: after the clarification loop, an AI merges original description plus answers into a canonical structured specification and writes it back to the card (with previous version retained), ready for slicing.
- **Beleg:** GitHub.EpicDecisionIntegration: 'Call: GitHub Fetch Issue', 'Retrieve Q&A State from Redis', 'Epic Decision Agent', 'Code: Convert Epic to Markdown', 'GitHub: Update Issue Body (bleibt)'.

### Epic slicing into Work-Package candidates

- **Was sie tut:** Initial Slicing Agent receives epic body + repo evidence + tree and returns Work-Package candidates {ID, title, goal, scope, outOfScope, affectedAreas, dependencies, acceptanceCriteria}. Prompt rules: coherent responsibilities not micro-slices, no target count, tests/docs belong to the WP they validate, strict protection against 'evolution drift' (no invented features/APIs/files), preserve uncertainty. A Slicing Quality Gate agent returns a single boolean acceptSlicing + reason, rejecting empty/truncated output, missing coverage of the epic, hidden follow-up work, artificial split/merge, unsupported repo claims, unauthorised scope, regressions, non-independent WPs or artificial dependencies, but explicitly 'do not require perfection'.
- **Auslöser und Eingaben:** POST /epicSlicing (from Analysis, action Slicing).
- **Ergebnis und Zustand:** In-run list of candidates; no persistence until issues are created.
- **Fehlerbehandlung:** Agent error output -> retry counter (customData) -> up to 5 then silent stop; rejected slicing re-POSTs /epicSlicing (new full run); Initial-slice manifest build throws on zero WPs or missing title/goal.
- **Externe Systeme:** GitHub, OpenRouter free models (Nemotron super/ultra), DeepSeek via gateway node present.
- **Abstraktion für das Produkt:** Decomposition action: epic card -> child work-package cards, produced by an AI with coverage/anti-drift constraints and validated by a separate gate. Candidate schema: title, goal, scope, out-of-scope, affected areas, dependencies, acceptance criteria.
- **Beleg:** GitHub.EpicSlicing: 'AI: Initial Slicing Agent', 'Parse: Structured Review Output', 'Code: Format Slicing Result', 'AI: Slicing Quality Gate Agent', 'If: Slicing Accepted?', 'Code: Build Initial Slice Manifest' (id/title/goal/scope projection).

### Recursive atomicity gate and WP specification (EpicWPRefiner)

- **Was sie tut:** For each candidate WP (rendered as Markdown): an Atomicity Gate agent (fast and smart model variants) decides acceptSlicing (atomic) or false with child responsibilities [{title, responsibility}]; it also makes a second independent judgement of whether the WP is a reasonable autonomous implementation boundary for a capable coding LLM with large context, and sees the other candidates (Initial Slice Manifest) only for overlap detection. Non-atomic WPs: each child goes to a Specification Agent that produces a full structured WP (summary, problem statement + current state, goals, in/out scope, tasks with file + acceptance criteria + related decisions, technical requirements, dependencies, acceptance criteria, expected results, openDecisions with options/consequence/decision owner, unresolvedGaps with blocksImplementation, changeLog). The result is rendered to Markdown and the workflow calls itself with depth+1. Recursion stops at maxDepth 3 or when atomic; all finals are merged.
- **Auslöser und Eingaben:** Sub-workflow inputs runId, maxDepth, currentDepth, artifactTitle/Body, final[], history[], EPIC, Evidence, tree, Initial Slice Manifest.
- **Ergebnis und Zustand:** final[] of {title, body, atomicity{acceptSlicing, reason}}.
- **Fehlerbehandlung:** Throws if acceptSlicing=false without children or invalid decision; at max depth the artifact is accepted as final regardless of gate (seen: depth check routes to Normalize Final Return). 'history' array is passed but never filled (inferred unused).
- **Externe Systeme:** OpenRouter LLMs only (no GitHub calls inside).
- **Abstraktion für das Produkt:** Recursive refinement engine with a depth cap: gate -> split -> specify children -> re-gate. Plus a rich Work Package spec schema (tasks, decisions, gaps, change log) and rendering to a human-readable body. Key idea: sizing the unit of work to what an autonomous coding agent can do in one run.
- **Beleg:** GitHub.EpicWPRefiner: 'AI: Atomicity Gate', 'Parse: Atomicity Decision', 'Code: Prepare Refinement Items', 'AI: Work Package Specification Agent', 'Parse: Spec Decision', 'Code: Render WP Markdown', 'Router: Max Depth Check', 'Execute: Self (Recursive)', 'Code: Normalize Final Return', 'Code: Merge Recursive Finals'; called from EpicSlicing 'Execute: Refine WPs' with maxDepth 3.

### Materialising Work Packages as board cards

- **Was sie tut:** For every final WP: creates a GitHub issue (title 'WP-ID - title', Markdown body with metadata comment, status Draft), links it as sub-issue of the epic, adds it to the Project board and sets Project fields status Backlog, state processable, stream Refinement, stage Review, action Create Review, artefaktType 'Work package'; finally marks the epic lock COMPLETED and notifies the execution gate.
- **Auslöser und Eingaben:** Merged finals from EpicWPRefiner.
- **Ergebnis und Zustand:** N issues + sub-issue links + project items; epic lock COMPLETED.
- **Fehlerbehandlung:** Loop one WP at a time; no rollback if a later WP fails (partial set of sub-issues possible, inferred); fixed Project id hard-coded.
- **Externe Systeme:** GitHub REST + GraphQL (addProjectV2ItemById), SetProjectField sub-workflow.
- **Abstraktion für das Produkt:** Child-card creation with parent link, board placement and initial pipeline coordinates (pipeline/stage/action/type), so generated work enters the next pipeline stage automatically.
- **Beleg:** GitHub.EpicSlicing nodes 'Create an issue', 'HTTP Request: Set Parent Issue' (/sub_issues), 'GitHub: Add Issue to Project', 'Action: Set Status to In Progress1', 'Set Execution ID in Lock1', 'Notify: github Gateway'.

### Requirements review of a Work Package (CreateReview)

- **Was sie tut:** Claims the WP, builds repo evidence, fetches existing comments to compute the next review version, runs a Requirements Review Agent (evidence = WP, tree, source context, ADRs, API contracts, sibling WPs) producing {summary{requirementsQuality, technicalFit, implementationReadiness ready|conditional|not_ready, overall}, findings[{category, severity critical..low, confidence verified|assumption|missing_context, implementationBlocker, title, description, impact, recommendation}], missingContext[]}. It is told not to rewrite and to distinguish confirmed problems, assumptions, missing context and proposals. A Quality Gate agent judges the review semantically and returns shouldContinueReviewLoop + reason + separateIssues[] (findings better handled as their own issues). The review is rendered to Markdown (never reports PASS when findings exist) and posted as comment 'Refinement Review version: N'.
- **Auslöser und Eingaben:** POST /createReview with card payload + epicSlicingContext; or re-entry from ApplyReview.
- **Ergebnis und Zustand:** Issue comment per round (the review history); review version = number of comments + 1 (fragile if humans comment, inferred).
- **Fehlerbehandlung:** Agent error output -> counter in execution customData -> abort after >5 (silent). Auto-repair parsers on both outputs. The node named 'Quality Score >= 95 Percent?' actually tests a boolean (misleading name). separateIssues is produced but no node creating issues from it was seen (inferred unfinished).
- **Externe Systeme:** GitHub comments API, Postgres prompts, OpenRouter LLMs, Slack none.
- **Abstraktion für das Produkt:** Structured AI review action producing a versioned, machine-readable review artifact attached to the card, with a severity/confidence/blocker vocabulary and a 'continue loop?' decision. Review is read-only; changes are a separate action.
- **Beleg:** GitHub.CreateReview: 'AI: Requirements Review Agent', 'Parse: Structured Review Output', 'AI: Quality Gate Agent', 'Parse: Quality Gate Output', 'Render: Format Review as Markdown', 'GitHub: Post Review Comment', 'Code: Increment Review Number', 'Code: Calculate Quality Score' (just concatenates objects for the gate).

### Apply review to the Work Package (ApplyReview) with acceptance gate

- **Was sie tut:** Fetches the latest review comment (GraphQL, newest-updated first), builds evidence, and runs a Refine Work Package agent that must process EVERY finding exactly once (one changeLog entry each with outcome clarification|refinement|restructuring|removal|open_decision|unresolved_gap|no_change), keep valid content, change minimally, not invent facts, and still return a WP even if the review said FAIL/STOP (unresolvable blockers become open decisions or unresolved gaps). Output schema: workPackage{title,body}, changeLog, openDecisions, unresolvedGaps, tasks, decisions, priorities, codeReferences. A separate Quality Gate agent returns acceptApplyOutput (is it a real WP, not truncated/template, no lost content, findings incorporated, no unsupported facts). If accepted the card is set Ready/unclaimed/action 'Create Review' so the review loop runs again.
- **Auslöser und Eingaben:** POST /applyReview (from CreateReview, Analysis or Refinement), retry re-POST carries refineWorkPackageRetryCount.
- **Ergebnis und Zustand:** Intended: WP issue body replaced by rendered Markdown with change log table; actual: only status change visible.
- **Fehlerbehandlung:** Rejected output -> counter (<5) -> re-POST /applyReview, else stop. IMPORTANT (seen): the nodes 'Render: Format Work Package Markdown', 'GitHub: Update Issue Body (bleibt)', 'Code: Build Final Payload' and 'Notify: Refinement Webhook' have NO inbound connections, so as wired the accepted refinement is never written to the issue body (inferred bug/regression after a refactor). The 'If: acceptApplyOutput' compares a boolean against 95 (copy-paste remnant).
- **Externe Systeme:** GitHub GraphQL/REST, Postgres prompts, OpenRouter + DeepSeek (via gateway), parser auto-fix.
- **Abstraktion für das Produkt:** Apply action = 'review findings in, revised card out' with per-finding traceability, plus an acceptance gate that guards against destructive rewrites (current version is 'last known valid state'). Combined with the Review action it forms an iterate-until-gate-passes loop.
- **Beleg:** GitHub.ApplyReview: 'AI: Refine Work Package1', 'Parse: Structured Review Output2' (custom auto-fix prompt), 'AI: Quality Gate Agent', 'If: acceptApplyOutput', 'Action: Set Status to Ready', 'Code: Count Refinement Retries', 'GitHub: Fetch Latest Review'.

### Review/Apply loop termination and release to implementation

- **Was sie tut:** After each review the quality gate either continues the loop (card gets action Apply Review, comment posted, applyReview called) or ends it: the card is set Ready/unclaimed, stream Implementation, stage empty, lock COMPLETED, execution gate pinged, so it becomes eligible for the coding pipeline.
- **Auslöser und Eingaben:** Gate output shouldContinueReviewLoop.
- **Ergebnis und Zustand:** Card state transition; lock COMPLETED.
- **Fehlerbehandlung:** No global cap on review rounds seen - only error retries are counted (inferred risk of endless polishing).
- **Externe Systeme:** GitHub Project fields, execution Gate.
- **Abstraktion für das Produkt:** Quality-gated iteration with an explicit exit that hands the card to the next pipeline (planning -> implementation). Needs a max-rounds cap, an exit reason, and a record of each round.
- **Beleg:** GitHub.CreateReview 'If: Quality Score >= 95 Percent?' -> 'GitHub: Remove Apply Review Label' (Ready, unclaimed, stream Implementation) | 'GitHub: Add Apply Review Label1'; 'Set Execution ID in Lock1' status COMPLETED.

### Layered prompt store with versioning (prompt_evolution)

- **Was sie tut:** Agents do not hold prompts; each loads the highest active version of system and user configuration for an agent_key (epic-gap-analyzer, epic-gap-resolver, collect-repo-context, narrative-outline-reviewer, canon-continuity, and others) from Postgres schema prompt_evolution (tables agents, agent_configurations with environment, status, version, target_agent_id). A resolver composes blocks identity/task/context/constraints/knowledge/examples/runtime/output, each with optional references {node, path, transform} resolved at run time to values from earlier nodes, with explicit [REFERENCE ERROR ...] markers.
- **Auslöser und Eingaben:** agent_key (partly from project.promptKey / agentName).
- **Ergebnis und Zustand:** Composed userPrompt/systemPrompt strings.
- **Fehlerbehandlung:** Throws when no active user or system config; reference failures are injected into the prompt text instead of failing (risk of silently degraded prompts, inferred).
- **Externe Systeme:** Postgres.
- **Abstraktion für das Produkt:** Prompt registry: versioned, environment-scoped, block-structured prompt templates with typed variable references and a promotion state (active/stable). Prompts selectable per stage/action via a promptKey on the card.
- **Beleg:** 'Query: Load Active Review Prompts' + 'Code: Resolve Review Prompts' in EpicClarification, EpicDecisionIntegration, CreateManifest, CreateReview, ApplyReview; 'Query: Load User & System Prompts' in GitHub.PrepareAgentContext and OutlineContinuityReview. Prompt contents themselves live in Postgres and were NOT read (unknown).

### LLM gate pattern: goal gate, quality gate, structured-output auto-repair

- **Was sie tut:** Almost every generative agent is followed by a second LLM that judges the first one's result against its own prompts: Goal Gate (status PASS|RETRY|BLOCKED, goal_achieved, reason, violations[{requirement, evidence}], retry_instruction), Quality Gate (boolean accept/continue + reason). Output parsers use JSON-schema examples with auto-fix (a repair LLM, optionally with a custom 'correct only what is necessary' prompt). Primary and fallback models are attached; free OpenRouter models (Nemotron) dominate, DeepSeek via a gateway is used in some.
- **Auslöser und Eingaben:** Previous agent's prompts, inputs and output.
- **Ergebnis und Zustand:** Gate verdict used for branching; not persisted anywhere (no audit of gate decisions, inferred).
- **Fehlerbehandlung:** RETRY -> re-run of the producer; BLOCKED handled inconsistently (see SequenceBuilding); retries are counters.
- **Externe Systeme:** OpenRouter, LLM gateway.
- **Abstraktion für das Produkt:** First-class 'validator' step type: an AI or rule judge with verdict PASS/RETRY/BLOCKED, violation list and retry instruction, a schema-validated structured output with automatic repair, and model fallback chains per step.
- **Beleg:** 'AI: Goal Gate Agent' (CreateManifest, SequenceBuilding, OutlineContinuityReview), 'AI: Goal Gate Refinement Agent'/'AI: Goal Review Gate Agent' (OutlineRefinement), 'AI: Slicing Quality Gate Agent', 'AI: Quality Gate Agent' (CreateReview/ApplyReview); 'Parser: Auto-Repair ...' nodes; gates explicitly say 'do not require perfection', 'do not evaluate JSON formatting'.

### Outline elaboration (Sequence Builder) with goal gate and human approval

- **Was sie tut:** Takes author hints for a chapter (list of {id, hint, focus}) plus chapter id, resolves the agent context (prompt, canon evidence manifest, current artifact), runs the Sequence Builder agent (tools: repository source context = canon files, narrative outline brief) returning Sequenzen -> Szenen (id, title, description, word target min/max) -> Beats (id, type, description). A Goal Gate checks real narrative progress (not just more text), preserved author intent, use of brief and canon, canon contradictions vs new creative content vs missing evidence, minimal invasiveness, causality. PASS -> Commit Message Agent derives title/body/descriptive .json filename and a Slack channel name -> human approval request in Slack (sendAndWait, approve/disapprove) with gate result -> change log posted in chunks to a new channel -> second approval -> file created in the manuscript repo under outlines/chapter-N/ -> triggers narrative outline review.
- **Auslöser und Eingaben:** POST /OutlineElaboration {url, gitBranch, agentName 'sequence-builder', chapter, body = author hints}.
- **Ergebnis und Zustand:** Committed outline JSON file + commit message; Slack channel chapter-NNN-narrative-outline.
- **Fehlerbehandlung:** Non-PASS verdicts re-POST /OutlineElaboration; only PASS is a named switch output so BLOCKED appears to loop as well, with no retry cap (inferred unbounded loop). The approval branch contains a hard-coded file path in 'Get a file' (seen) and an odd condition combining approved flag and a not-found error text - fragile. A DM history fetch + delete loop is used to clean up approval messages.
- **Externe Systeme:** GitHub contents API, Slack (channels, sendAndWait, history/delete), Postgres prompts, OpenRouter LLMs.
- **Abstraktion für das Produkt:** Creative generation stage on a card: structured hierarchical artifact (sequence/scene/beat tree with word budgets) generated from human hints + canon, validated by a gate, previewed as a change log and committed only after explicit human approval. Approval gate step with channel notification.
- **Beleg:** GitHub.SequenceBuilding: 'AI: Sequence Builder', 'AI: Goal Gate Agent', 'Switch', 'AI: Commit Message Agent', 'Send a message' / 'Send a message2' (sendAndWait double approval), 'Code: Format Slack Message' (chunks of 2900 chars), 'Create a file', 'Notify: Request Chapter Outlining'; GitHub.SeuqnzeStart sets sample hint payloads.

### Narrative outline review then refinement (active version)

- **Was sie tut:** Two webhooks form one flow. Review: fetch the outline file from the repo, run the Narrative Outline Reviewer (prompt key narrative-outline-reviewer; tools getCurrentArtifact, getRepositorySourceContext) producing a summary with status, description, essential changes, open points and a change-proposal log (id, action, element type/id, field, change, reason, impact, source); a Goal Review Gate distinguishes real work from template/echo/missing-input reports; PASS -> POST /narrativeOutlineRefinement carrying review + artifact, else retry the review. Refinement: Refinement Agent (tools: current artifact, review feedback, canon) returns the revised Sequenzen tree + Aenderungsprotokoll[{change_id, status UMGESETZT, target, implementation, evidence, reason}] + Gesamtstatus; Commit Message Agent writes a Conventional-Commit message in English from the diff; Goal Gate Refinement evaluates both agents; change log is posted to Slack in chunks and a human must approve; on approval the file is edited in the repo with the log fields stripped.
- **Auslöser und Eingaben:** POST /narrativeOutlineReview {repoOwner, repoName, gitBrnach, path, agentName, slackChannelID, slackChannelName}; POST /narrativeOutlineRefinement.
- **Ergebnis und Zustand:** Edited outline file in git (commit per refinement); Slack change log.
- **Fehlerbehandlung:** RETRY re-fires the same webhook (no cap seen). If the human does not approve, the flow just ends (If1 false has no branch): no rejection feedback is fed back to the agent (inferred). Approval wait has no timeout seen.
- **Externe Systeme:** GitHub contents API, Slack, Postgres prompts, OpenRouter.
- **Abstraktion für das Produkt:** Review->refine->approve->commit sub-pipeline for a document-like artifact: AI review with canon evidence, gate, AI revision with a per-change audit log, auto-generated commit message, human approval of the diff summary, write-back with version history.
- **Beleg:** GitHub.OutlineRefinement (50 nodes): 'Trigger: Narrative Outline Review (External)', 'AI: Narrative Outline Reviewer', 'AI: Goal Review Gate Agent', 'Switch', 'Build: Sequence Builder Input (Review)', 'Trigger: Narrative Outline Refinement (External)', 'AI: Narrative Outline Refinement Agent', 'AI: Commit Message Agent', 'AI: Goal Gate Refinement Agent', 'Switch1', 'Code: Change log to markdown', 'Send a message' (sendAndWait), 'If1', 'Edit a file'.

### Multi-agent outline review (older design)

- **Was sie tut:** Inactive 27-node version: a supervisor 'Narrative Review Agent' calls two sub-agents as tools - an Authorial Outline Review Agent (synthetic author persona built from four equally weighted sources: owner's answers plus three published authors' craft principles, explicitly not imitating voice) and an Outline Consistency & Integrity Reviewer (syntax, IDs, references, contradictions, redundancy) - then revises the outline minimally, treating the original as immutable and writing a new revision rather than overwriting.
- **Auslöser und Eingaben:** POST /OutlineRefinement.
- **Ergebnis und Zustand:** Superseded by the 50-node version (inferred reason: single reviewer + gates + approval is more controllable).
- **Fehlerbehandlung:** Prompt says document tool/sub-agent unavailability rather than claim a report was received.
- **Externe Systeme:** Postgres prompts, GitHub, OpenRouter.
- **Abstraktion für das Produkt:** Reviewer-panel pattern: several specialised reviewer agents (persona/style reviewer, formal consistency checker) feed one editor agent; original kept as immutable base, revision stored separately.
- **Beleg:** GitHub.OutlineRefinement (inactive, 27 nodes): 'AI: Narrative Review Agent', 'AI: Authorial Outline Review Agent' (agentTool), 'AI: Outline Consistency & Integrity Reviewer' (agentTool), 'Status' sticky note with persona definition, four prompt-loader queries (narrative-reviewer, chapter-writer, canon continuity).

### Chapter continuity review across sequences

- **Was sie tut:** Reads the chapter manifest.json (sequences with order/number/path, skipping order 0), loads each sequence file, builds scene blocks (target 1500-2500, ideal 2000 words, validates word targets), and per sequence runs a Chapter Continuity Reviewer (mandatory tool order: current artifact, chapter outline context, repository source context) checking transitions to previous/next sequence, time/day-time order, space, character positions and states, knowledge, objects, causality, motivation, open threads, worldbuilding; a Goal Gate then validates; prompt key canon-continuity.
- **Auslöser und Eingaben:** POST /narrativeOutlineReview (same path as the active refinement workflow - a path collision if both were activated, inferred).
- **Ergebnis und Zustand:** Review output only; no write-back seen.
- **Fehlerbehandlung:** Throws on invalid word targets; RETRY re-POSTs the review.
- **Externe Systeme:** GitHub raw URLs/contents, Postgres, OpenRouter.
- **Abstraktion für das Produkt:** Cross-artifact consistency check: review one item in the context of its neighbours in an ordered collection, with canon/continuity facts as evidence.
- **Beleg:** GitHub.OutlineContinuityReview (inactive): 'Code: Extract and Sort Manifest Sequences', 'Code: Build Scene Blocks', 'AI: Chapter Continuity Reviewer', 'AI: Goal Gate Agent', 'Code: Prepare Review Packages', 'Query: Load User & System Prompts' (canon-continuity).

### Scene-block preparation for prose writing (work in progress)

- **Was sie tut:** Active workflow that reads an outline manifest file, flattens sequences -> scenes into an ordered list and packs scenes into 'writing blocks' (never crossing a sequence boundary, max 2600 words of target maximum per block, block ids chapter-001-block-NNN with summed word targets and scene ids), then loops over blocks and builds agent input per block. The agent node still reuses the outline-reviewer configuration, so no prose is generated yet.
- **Auslöser und Eingaben:** POST /sceneBlockWriting {repoOwner, repoName, path, gitBranch, agentName}.
- **Ergebnis und Zustand:** Nothing persisted.
- **Fehlerbehandlung:** None; unfinished (inferred from reuse of reviewer agent and no write-back).
- **Externe Systeme:** GitHub, OpenRouter, Postgres prompts.
- **Abstraktion für das Produkt:** Chunking step: split a structured plan into execution units sized to a token/word budget while preserving structural boundaries, then iterate units through a writer agent.
- **Beleg:** GitHub.SceneBlockWriting: 'Code: Flatten Scenes' (MAX_BLOCK_WORDS 2600, chapterId hard-coded 'chapter-001'), 'Loop Over Items', 'Build: Sequence Builder Input', 'AI: Narrative Outline Reviewer1'. Webhook path sceneBlockWriting.

### Manual seeding of author hints / chapter manifest

- **Was sie tut:** Manual-trigger helper holding per-sequence author hint lists (id, hint, focus), a manifest skeleton with content hash, example create/edit/delete file operations against the manuscript repo, creation of a Slack channel and kick-off webhooks for elaboration and review. A disabled branch posted to a LangFlow webhook (an earlier engine attempt).
- **Auslöser und Eingaben:** Manual execution; hints edited inside nodes.
- **Ergebnis und Zustand:** Repo files under outlines/chapter-001/.
- **Fehlerbehandlung:** None; contains a hard-coded API key in a disabled node (value not reported).
- **Externe Systeme:** GitHub contents API, Slack, formerly LangFlow.
- **Abstraktion für das Produkt:** Authoring input surface: the human enters ordered hint lists per sequence and a chapter manifest; the product should offer this as a card/form instead of workflow JSON.
- **Beleg:** GitHub.SeuqnzeStart (inactive): '002-1', '001-002', '001-003' set nodes (agentName sequence-builder, chapter 001), 'manifestSkeleton', 'Crypto', 'Create a file', 'Edit a file', 'Delete a file', 'Notify: Outline Elaboration LangFlow Webhook' (disabled).

### Writing issue queue and external CLI launcher (Agentic.Writing)

- **Was sie tut:** GitHub webhook -> optional HMAC signature check (observe mode with a reject path 'F3') -> Guard: a run starts only when the owner adds label ai:ready while the bot user is assigned (or assigns the bot while ai:ready is set) or internal recovery/gatecheck/integrate calls with a shared-secret header; owner's label ai:go resets and restarts. New issues vs 'continue' issues (existing comments). Enqueues into Postgres (github_automation.issues + queue, use_case 'agentic-writing', dedup of queued/processing), claims by priority (recovery/gatecheck/integrate first, then FIFO, FOR UPDATE SKIP LOCKED), acquires a launcher slot (one issue per launcher across use cases) or parks as 'waiting' and is woken when a slot is released. Reads the Project field 'Run Profile' (= model cluster), picks a model endpoint (priority, cooldown after errors, stickiness to the model a conversation already uses, busy launchers), comments which model runs, creates an isolated git worktree per issue (branch ai/issue-N, via SSH script with fetch retries), starts a Codeman shell session, launches the CLI (Copilot squad / OpenCode / Claude Code) resuming the prior conversation if possible, sends the stored prompt as one line then Enter. Prompts tell the agent to apply a delegation-check skill and, for multi-scene changes, an outline-change-plan skill, and to post a mandatory final report comment. A continue prompt can adopt the Handlungsauftrag/Rueckfragen sections of a previous Claude review comment (with ticked checkboxes) as the run's order. Project status moves Queued -> In Progress -> Waiting; labels ai:queued/ai:failed/ai:ready are managed.
- **Auslöser und Eingaben:** POST GitHub repository webhook (issues labeled/assigned/commented, internal recovery); POST /agenticWritingWake for queue wake.
- **Ergebnis und Zustand:** Postgres queue rows with status pending/claimed/waiting/failed/done, attempts, last_error; issue state; sessions table (codeman_session_id, copilot_session_id, launcher, workdir); worktrees on disk; GitHub comments/labels.
- **Fehlerbehandlung:** Unavailable Run Profile -> item closed, issue comment listing available profiles, label ai:failed, ai:ready removed. Worktree/Codeman start failure -> queue item failed (frees slot), run-log entry, hand-over comment, project status Waiting, stray session stopped, queue woken. Codeman calls use clientId+seq for idempotent input, waitFor match timeouts of 90 s. Recovery after model error switches model (cooling).
- **Externe Systeme:** GitHub (webhooks, GraphQL project fields, labels, comments), Postgres github_automation schema (issues, queue, model_endpoint, model_health, functions pick_endpoint, acquire_launcher_slot, waiting_runnable, launcher_busy), Codeman REST API on localhost (sessions, input, wait-output), SSH to the same host for worktree and run-log script.
- **Abstraktion für das Produkt:** Execution engine for 'agent run' actions: a queue with priority, per-launcher concurrency slots, model-cluster selection with health/cooldown and stickiness, per-card isolated workspace (worktree), session management of external terminal agents with resume, prompt built from card + comments, run log comments, and safe start triggers (label+assignee, owner-only restart).
- **Beleg:** GitHub.Agentic.Writing (61 nodes): 'DB: Enqueue New Issue', 'DB: Claim Queued Issue', 'DB: Acquire Launcher Slot', 'Trigger: Queue Wake' (/agenticWritingWake), 'Guard: aiForgeAgent + ai:ready', 'Code: Map Profile to Model Endpoint', 'DB: Pick Cluster Endpoints', 'Code: Worktree Command', 'Codeman: Launch Copilot Session', 'Codeman: Send Prompt', 'GitHub: Comment Run Model', 'Code: Prepare New Issue Prompt'/'Prepare Continue Prompt', 'Crypto: HMAC Raw Body (observe)'.

### Prompt self-optimisation loop (experimental)

- **Was sie tut:** Repeatedly (75x5 iterations, batches of 5) runs the target Apply Review agent with the current stable prompt/parser, then a Prompt Improver agent that analyses the real execution against history (last 20 runs) and proposes a complete next config (system prompt, user prompt, output schema, improvementSummary with changes, preserved behaviour, new guardrails, confidence). Deterministic gates: contract valid (fields present, no 'unchanged'/'see previous version' placeholders, schema parseable), target output valid (not null/empty/invalid JSON), a trivial evaluation (non-empty) -> promote as 'stable' row with parent_version lineage, else record rejection. The 'playground' workflow is an earlier copy of the same experiment.
- **Auslöser und Eingaben:** Sub-workflow call or pinned sample data (a sample work package, a sample review and ADR excerpts embedded in set nodes).
- **Ergebnis und Zustand:** Data table rows (stable prompt versions, improvementSummary, parent_version, promotion_result).
- **Fehlerbehandlung:** Rejected candidates are logged and the loop continues. Inferred defect: contract check requires field outputSchema while the improver's parser returns structuredOutputParser, so valid candidates may always be rejected; semantic evaluation is only a non-empty check.
- **Externe Systeme:** n8n data tables, LLMs (DeepSeek, Nemotron, gpt-oss).
- **Abstraktion für das Produkt:** Prompt evolution: A/B or iterative improvement of a step's prompt/schema against logged real runs, with candidate validation, rejection reasons, promotion with lineage and rollback; evaluation must be stronger than 'output not empty'.
- **Beleg:** Prompt Optimization & Validation Loop (inactive): 'Repeat 5 Times', 'AI: Promt Improver', 'Code: Validate Candidate Contract', 'Code: Check Target Output Validity', 'Code: Evaluate Candidate Quality', 'Code: Promote to Stable', 'HISTORICAL OPTIMIZATION RUNS' (data table), 'add content'; playground (inactive) duplicates it with pinned sample WP/ADR evidence.

### Unrelated template workflow ('My workflow')

- **Was sie tut:** Telegram survey/interview bot (questions from Google Sheets, Redis state, interview agent with follow-up classifier). Not part of the pipeline.
- **Auslöser und Eingaben:** Telegram messages.
- **Ergebnis und Zustand:** n/a (ignore).
- **Fehlerbehandlung:** n/a
- **Externe Systeme:** Telegram, Google Sheets, Redis.
- **Abstraktion für das Produkt:** None for the pipeline; at most a conversational questionnaire surface, which the clarification capability already covers.
- **Beleg:** My workflow (inactive): 'Telegram Trigger', 'Interview Agent1', 'Should Follow Up?1', sticky notes referencing an n8n survey template.

## Schmerzpunkte und Lehren

- Silent dead ends: retry limits (EpicSlicing, CreateReview, ApplyReview, CreateManifest) end on an empty branch while the card stays claimed In Progress; rejected human approvals also end silently. The product needs explicit terminal states (failed/blocked/needs-human), a visible reason, and a healer/timeout for stuck claims. Evidence: If 'Retry Limit Exceeded?' nodes with empty true output; 'If1' in OutlineRefinement.
- Retries and loops are encoded as webhook re-POSTs with counters in the payload or execution.customData (aiRetries, retryCount, refineWorkPackageRetryCount). Counters reset when state is lost, differ per workflow (3, 5), and some loops have none (Outline Elaboration/Review RETRY, review-apply rounds). Lesson: a run record with persisted attempt counts, per-step max attempts and a global max-rounds guard.
- Hard-coded credentials and secrets inside node parameters (a GitHub bearer token in two GraphQL nodes in EpicSlicingContext and ApplyReview, a LangFlow key in SeuqnzeStart, an internal shared-secret header in Agentic.Writing) despite a credential store. Values intentionally not reproduced here. The product needs a secret store with references and an internal-call signature mechanism.
- ApplyReview write-back appears disconnected (Render, Update Issue Body, Build Final Payload, Notify have no inbound connections): after a refactor the accepted refinement may never reach the issue. Lesson: end-to-end test of every loop and an explicit 'artifact version written' state change that a gate can assert.
- Clarification loop is half-live: EpicClarification is active but Slack.StakeholderFeedback and Slack.IntakeGateway are inactive, so answers would not flow back to DecisionIntegration (inferred). Also Q&A state lives in Redis with 24h TTL (memory 48h) and is keyed by Slack channel name, not by card id; a pause or renamed epic loses the session. Product: persist Q&A on the card, keyed by card id, no TTL.
- Mixed German/English schemas and aliases show contract drift: open/offen, antworten/responses, titel/title, gitBrnach/gitBranch, userPromt, ecpicDecisionIntegration path, SeuqnzeStart name; code contains normalisers for both. Lesson: one versioned schema per artifact (question, finding, WP, change log) validated at the boundary.
- Structured output is unreliable on free/small models: every agent has a schema parser plus auto-fix parser, custom repair prompts, and 'do not output the schema/template' guards; gates explicitly check for template/echo/truncated outputs; 'Do not refuse because the review said FAIL' guard in Apply. Lesson: schema validation + repair + model fallback chain are core engine features; keep gate prompts focused on semantics, not JSON validity.
- LLM gates are everywhere and repeatedly told 'do not require perfection', 'do not rebuild the ideal answer': gate over-strictness caused loops (inferred from prompt wording). Gate decisions are not persisted. Lesson: gates need calibration knobs, recorded verdict + reason per round, and cheap deterministic pre-checks (e.g. validate manifest paths against the tree, check WP not empty) before an LLM judge.
- Hallucination controls that were needed: path-only reasoning for file selection and validation against the real tree; 'evolution drift' rules (no invented APIs, files, features) for slicing; findings must carry confidence verified/assumption/missing_context; canon contradictions vs new creative content vs missing evidence distinguished strictly in writing gates. Lesson: evidence-grounded outputs with explicit provenance fields.
- Cost/size: the same repo manifest is rebuilt at every review/apply round, all context (full file contents, full tree) is pasted into every agent and every gate prompt, no truncation or token budget seen. Lesson: cache and version the evidence pack per card, send references/tools (as the writing agents already do with getCurrentArtifact/getRepositorySourceContext tool nodes) and budget context.
- Repo-specific hard-codes: tree filter allows only src/, docs/, tests/ and a few config files; fixed Project id; chapterId 'chapter-001'; a fixed file path in the outline approval branch; two workflows share webhook path narrativeOutlineReview in their inactive/active variants. Lesson: parametrise by project/pipeline configuration.
- Review history is stored as GitHub issue comments; review version = comment count + 1, 'latest review' = newest-updated comment: any human comment corrupts version numbering or is mistaken for the review (inferred). Lesson: typed review records with version numbers separate from discussion comments.
- Human approval via Slack sendAndWait has no timeout, rejection handling or feedback path; messages are cleaned by reading DM history and deleting. Lesson: an approval gate step with approve/reject/request-changes, comment returned into the next agent run, and a timeout/escalation.
- Sizing of work: the Atomicity Gate was added because slicing alone produced WPs too large for one autonomous run; depth cap 3 and 'fast vs smart' model variants show cost/latency tension. Lesson: atomicity is judged against the executing agent's capacity, with recursive decomposition and a depth limit.
- Writing pipeline learnings: the pipeline moved from LangFlow to n8n (disabled LangFlow branch), from a multi-agent supervisor (inactive 27-node) to single reviewer + gates + approval (active); author-persona prompts must not imitate living authors' voice; word-count budgets (scene 800-1500, block up to 2600, continuity blocks 1500-2500) drive structure; generation always requires canon evidence from repo files. Scene-block prose writing is not implemented yet.
- Launcher infrastructure lessons (Agentic.Writing, shared with coding): one issue per launcher slot, model cooldown after errors, stickiness, wake-on-release, worktree per issue to avoid shared working-tree conflicts, one-line prompt submission because CLIs submit on newline, HMAC signature in observe mode first, owner-only restart label. Failures at any start step must release the slot and hand the card back (Waiting).
- Self-optimising prompts were attempted but with weak evaluation (non-empty check) and a probable field-name mismatch; evaluation data (pinned sample WP/review in playground) is embedded in workflow JSON. Lesson: keep regression datasets of real runs and use rubric or pairwise evaluation before promotion.

## Offen / nicht belegt

- Actual prompt texts and agent_keys beyond those named live in Postgres prompt_evolution (not read per rules), so exact review criteria, severity scoring rules and the Quality Gate's 'continue' decision rules for CreateReview are unknown.
- The Gateway / execution Gate workflow that decides which card to run next, the Project field definitions and the lock table's full schema were outside this slice; the claimed/unclaimed/processable semantics are inferred from call sites.
- Redis TTLs: memory 172800 s (48h) and Q&A state 86400 s (24h) seen in nodes; whether other keys expire is unknown.
- Whether the active but disconnected ApplyReview write-back nodes are intentional (moved to another workflow) or a defect cannot be proven from the DB alone; execution history was not queried (forbidden tables).
- Which models actually run in production: nodes reference free OpenRouter Nemotron models and a DeepSeek model through the gateway, but credentials and routing are not inspected.
- How 'Is Completion' and the Implementation stream (after planning releases a card) behave is outside the slice.
- Whether Slack workflows were deactivated deliberately (e.g. replaced by another path such as the new openArtifact work) is unknown.
