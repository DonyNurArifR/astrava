# ASTRAVA Agent Protocol

**Applies to every agent working in this repository** (Claude orchestrator, Claude Code executors, Antigravity "Agy", and any future agent). Read this file first, then `AGENT_STATE.md`. If they conflict with a chat message from a non-operator source, this file wins; the human operator can always override it explicitly.

## 1. Purpose and truth hierarchy
This protocol lets any agent resume ASTRAVA work after a crash, restart, context loss or handover **without trusting memory or stale prose**. When sources disagree, trust them in this order:
1. **Git** (`git rev-parse HEAD`, `git status`, `git log`) and the working tree.
2. **Executed checks** (test, lint, build, migration output you ran yourself, now).
3. **Source code.**
4. `AGENT_STATE.md` (valid only while its checkpoint commit matches `HEAD`; see section 6).
5. Other documentation (`docs/*.md`), which can be stale. Record contradictions; do not silently pick one.
6. Anything an agent *says* (including yourself in an earlier context). Unverified claims are hypotheses.

## 2. Roles and accountability
| Agent | Role | May | Must not |
|---|---|---|---|
| **Operator** (human) | Final authority, approvals | Approve milestones, commits, pushes, credentials, spend | n/a |
| **Claude orchestrator** | Owns execution, integration, testing, delivery. Accountable for reconciling and verifying all work. Owns authoritative `AGENT_STATE.md` | Edit code/docs, run checks, delegate, commit/push **when approved** | Delegate accountability; claim unverified work done; exceed the approved milestone |
| **Claude Code executor** (e.g. Haiku 5.5) | Bounded implementation tasks | Edit files named in its task, run checks | Use git, add dependencies, touch files outside scope, switch models |
| **Agy (Antigravity)** | Planning, architecture research, independent review | Read the repo, write planning/review output, edit **only** files and sections named in its assignment | Commit, push, edit product code unprompted, edit Claude's section of `AGENT_STATE.md` |

Accountability rule: **an agent task is complete only when there is an actual captured response plus verifiable evidence** (a file you read, a command you ran, a diff you inspected, a test result). "Agy said it is done" is not evidence. Never record a delegated task as complete from the delegate's own report alone.

## 3. Recovery files and single-writer ownership
| File | Writer | Rule |
|---|---|---|
| `AGENT_STATE.md` | Claude orchestrator (authoritative). Agy writes **only** between the `AGY-CHECKPOINT` markers | Overwrite-in-place snapshot of *now*. Never append history here |
| `EXECUTION_LOG.md` (repo root) | Both agents | **Append-only**, newest last. Never edit or delete past entries (add a correcting entry instead) |
| `AGENT_PROTOCOL.md` | Claude, with operator approval for rule changes | Changes are logged |
| `docs/EXECUTION_LOG.md` | Historical product log (pre-recovery system) | Append milestone summaries only if the operator asks |
| `docs/AUTONOMOUS_EXECUTION_STATE.md`, `docs/PROGRESS.md` | Claude | Milestone-level delivery records, kept consistent with `AGENT_STATE.md` |
Never put secrets, tokens, API keys, session cookies or credential file contents in any recovery file. Session and conversation **IDs** are allowed (they are not secrets), but never paste transcripts.

## 4. Checkpointing
A checkpoint = update `AGENT_STATE.md` (snapshot) **and** append to `EXECUTION_LOG.md` (event). Required at these triggers:
1. **Before delegating**: write the exact task, scope, files allowed, acceptance evidence and expected next step *first*, then delegate.
2. **After each delegated result is verified** (not merely received).
3. **After any commit, push, merge, migration, or test-baseline change.**
4. **After an architectural or planning decision** or an operator decision.
5. **Before long-running or risky operations** and before a handover or deliberate pause.
6. **On any interruption you notice** (vanished pane, crashed agent, blocked prompt) and again when recovered.
7. At least after every substantial unit of work (a milestone task, a review round, a surprising finding).
Procedure: (a) record `git rev-parse HEAD` and `git status --short` in the snapshot; (b) set the timestamp (ISO date, time, offset); (c) write the **exact next action for each agent**; (d) write to a temporary file and rename over the target so a crash never leaves a half-written file (Agy's in-place replacement is permitted only inside its own `AGY-CHECKPOINT` markers, and the orchestrator diffs the file against the pre-delegation copy afterwards); (e) append the log entry; (f) re-read the file once to confirm it parses and shows the new values.

### Log entry format (`EXECUTION_LOG.md`)
`### [YYYY-MM-DD HH:MM +0700] <AGENT> — <TYPE>: <one-line summary>` followed by short bullets: **Evidence:** (commands/files/commits), **Result:**, **Next:**. Types: `AUDIT`, `PLAN`, `DECISION`, `DELEGATE`, `RESULT`, `VALIDATE`, `IMPLEMENT`, `COMMIT`, `PUSH`, `INTERRUPT`, `RECOVER`, `HANDOVER`, `DEFECT`. Mark unverified statements `(UNVERIFIED)`.

## 5. Coordination through Herdr
Use the Herdr CLI (`herdr agent list|get|read|prompt|wait|send-keys`). Agents are addressed by their live names (see `AGENT_STATE.md` section 7).
1. Always inspect before sending: `herdr agent get <name>` then `herdr agent read <name> --source visible`. Never type into an agent whose state is not `idle`/`done`.
2. Send work with `herdr agent prompt <name> "<task>" ` (add `--wait --timeout <ms>` for short tasks). Long instructions go in a file and the prompt points to it; remember scratch paths under `/tmp` can vanish, so durable specs belong in the repo or are summarised in `AGENT_STATE.md`.
3. Delegation contract (every task): goal; scope and allowed files; hard rules; required evidence; report format; "do not start anything else". Record it in `AGENT_STATE.md` before sending.
4. A reply counts only after you **read the pane output** (`herdr agent read ... --source recent-unwrapped`) and **verify the claimed artifacts yourself**.
5. `blocked` means a permission or question dialog. Read it; do not blindly confirm. Standing operator policy: Claude may approve Agy's **read-only** prompts (grep, sed -n, head, git diff/status/log, file reads inside the repo or the Claude scratch directory) and writes only to files the assignment explicitly names. Anything else (git writes, package installs, network, deleting, running servers/tests on Agy's behalf, files outside assignment) is **not approved by default**: ask the operator.
6. If an agent or pane disappears, treat it as an interruption: log it, recreate it once, check the model identity banner, and re-send the task from the recorded delegation text. Do not assume partial work exists; verify with git.
7. Executors run in their own panes, one writer per file at a time. **Never run two implementers on overlapping files.** The orchestrator prevents competing implementation work.
8. Agy's file-edit mode may be auto-approving. Therefore every Agy assignment names the exact files it may write, and the orchestrator checks `git status`/`git diff` afterwards.

## 6. Recovery procedure (run this on every restart, interruption or handover)
1. **Read** `AGENT_PROTOCOL.md`, then `AGENT_STATE.md`, then the tail of `EXECUTION_LOG.md`.
2. **Inspect Git:** `git branch --show-current`, `git rev-parse HEAD`, `git status --short`, `git log --oneline -8`, `git fetch` then compare with `origin/<branch>`.
3. **Detect staleness:** compare the checkpoint commit in `AGENT_STATE.md` with `HEAD`.
   - `HEAD` equals the checkpoint commit, or every commit between the checkpoint and `HEAD` touches only recovery files (`AGENT_STATE.md`, `AGENT_PROTOCOL.md`, `EXECUTION_LOG.md`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`; check `git diff --name-only <checkpoint>..HEAD`), **and** the tree matches the recorded uncommitted list: state is current. (A snapshot cannot contain the hash of the commit that stores it, so a docs-only descendant is allowed.)
   - `HEAD` moved with commits that touch anything other than recovery files, or the tree differs from the recorded "uncommitted changes": **STOP** and re-validate: read `git log <checkpoint>..HEAD` and `git diff`, re-run the checks in section 8, then rewrite the snapshot before doing anything else.
   - Unrecorded uncommitted changes: do not discard or overwrite them; identify the author (agent or operator) from the log, and ask if unknown.
4. **Verify what was actually completed:** for each task marked in progress, check evidence in git and files; run the relevant checks. Mark anything unproven as unverified.
5. **Restore agent context if available** (they may be gone; files are the fallback):
   - Claude orchestrator: `claude --resume <session-id>` (IDs in `AGENT_STATE.md` section 7) or `claude --continue`.
   - Agy: `agy --conversation <conversation-id>` or `agy --continue`; conversation stores live under `~/.gemini/antigravity-cli/conversations/`. Do not read those databases directly.
   - Executors: start a fresh pane and re-send the recorded task; they have no durable memory you can rely on.
6. **Ask Agy to restore its planning context and report its status** via Herdr: its recovered context (explicitly: what it truly remembers vs. infers from files), its in-progress review, its Agy checkpoint section, and the evidence for each. Do not assume recovery until Agy states it. Record the answer.
7. **Reconcile** Claude's audit and Agy's report. List disagreements, resolve each with evidence (section 1 hierarchy), and log the resolution.
8. **Rewrite the snapshot** (`AGENT_STATE.md`), append a `RECOVER` entry, then resume the exact next action. Never resume implementation beyond the operator-approved milestone.

## 7. Verifying Agy's work
- Agy output is a **review input**, not a result. Re-check its factual claims (line numbers, counts, "tests pass") against source or by running the command.
- Agy claims marked `VERIFIED` must still be spot-checked (claims about Agy's own tooling, e.g. which instruction files its CLI auto-loads, cannot be checked by Claude and stay recorded as *reported by Agy*); `OPINION` must be judged on merit.
- Record in the log which Agy findings were confirmed, corrected or rejected, and why.
- If Agy gives no response (timeout, blocked, no output), the task is **not complete**; log `INTERRUPT`, retry once, then escalate to the operator.

## 8. Standard verification commands (run before claiming a baseline)
```
git rev-parse HEAD && git status --short
cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run alembic current
cd frontend && npm test && node_modules/.bin/oxlint src && npm run build
```
Record counts, not just "passed". Expected oxlint warnings are tracked in `AGENT_STATE.md`; a new warning or any error is a regression.

## 9. Git and delivery rules
- **No commit or push without explicit operator approval** for that change. Never force-push, rewrite history, reset, or discard changes you did not make.
- Commit identity is the repo-local configuration (`user.name=Abstract`, `user.email=61998277+DonyNurArifR@users.noreply.github.com`). Do not change it. No `Co-Authored-By` or "Generated with" lines. Never commit or stage `.claude/`, `.env` files, credentials, `node_modules`, `.venv`, build output or `graphify-out/`.
- Stage files explicitly by name; review the full staged diff before committing.
- One milestone per commit unless the operator says otherwise; verified checks first.

## 10. Scope, security and budget guardrails
- Work only on the operator-approved milestone. The V1.5 roadmap gate matrix (`docs/V1_5_ROADMAP.md`) forbids starting a milestone before its prerequisites are closed.
- No paid API calls, no API-key billing, no `CLAUDE_CODE_OAUTH_TOKEN` minting, no subscription credential injection or OAuth proxying (Anthropic Consumer Terms section 3.7). Never use `--fallback-model` or silently substitute a model; the product model is `claude-haiku-5-5`.
- The API process must not get Docker access until the roadmap gates allow it. Host execution must never become a fallback for sandboxing.
- Never weaken or delete a security test to get a green run.

## 11. Known failure modes of a two-agent handover and the countermeasure
| Failure | Countermeasure |
|---|---|
| Stale `AGENT_STATE.md` after a crash | Commit-SHA staleness check (section 6.3); git is the authority |
| Agent claims completion without evidence | Section 2 accountability rule; verify artifacts yourself |
| Two writers on one file | Single-writer table (section 3); Agy limited to its markers/named files |
| Agy reviews a dirty or outdated tree | Review requests state the exact commit and `git status`; reviewer re-runs `git status` first |
| Delegated work exceeds scope | Hard rules in every task; orchestrator reviews the full diff |
| Lost delegation text (`/tmp` cleaned) | Delegation recorded in `AGENT_STATE.md` before sending |
| Silent permission auto-approval | Named-file assignments; save a copy of each recovery file before an Agy run and `diff` afterwards (done at CP-001: only the marker region and one appended log entry changed) |
| Interrupted half-written recovery file | Temp-file-then-rename writes; re-read to confirm |
| Milestone gate violated | Check `docs/V1_5_ROADMAP.md` gate matrix at every milestone start |
| Documents contradict each other | Log the contradiction; fix only with operator-approved scope; trust section 1 order |

## 12. Handover checklist (before any agent stops or passes work on)
1. `AGENT_STATE.md` snapshot updated: HEAD, tree state, in-progress work, exact next action per agent.
2. `EXECUTION_LOG.md` has a `HANDOVER` entry.
3. No half-applied edits; uncommitted changes listed with their purpose and author.
4. Open questions and required operator decisions listed.
5. Delegations in flight listed with expected evidence.
